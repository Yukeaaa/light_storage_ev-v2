"""R1 E1 fidelity 机器门（审查结论26/27 P1）：锁定 e1_stats 对 K1 冻结样本的复现。

任何人修改 src/patent_preexperiment/response/e1_stats.py 后运行本测试，
若 K1 冻结数值（core_denom 2941 / rate 0.118667 / median 1.2794 /
置换 CI [0.035249, 0.057577]）漂移则测试失败。
另锁 session_id 集合 identity hash（审查结论27 P1）：数对但集合不对也失败。

依赖 datasets/lite_session_minute.parquet（仓库外，gitignored）；缺失则跳过，
与本仓库其他真实数据审计测试口径一致。绝不触碰 E1 test 数据。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.response.e1_stats import core_stats, negative_controls, process
from patent_preexperiment.response.events import GapThresholds

PP = Path(__file__).resolve().parents[1]
LITE_TABLE = PP / "datasets" / "lite_session_minute.parquet"
K1_CFG_YAML = PP / "configs" / "k1_preregister.yaml"

PERM_SEEDS = [42, 2024, 777]
BOOT_SEED = 42
N_BOOT = 2000

FROZEN = {
    "n_main_sessions": 5961,
    "session_id_set_sha256": "29517fcc615aa0b6bc718ebaa13dfd799f41de862e1cbc24a3a5b3cb490f349d",
    "denominator_sessions_with_core_run": 2941,
    "event_session_rate": 0.11866712002720163,
    "median_gap_kw": 1.2793999999999999,
    "diff_bootstrap_ci95_lower": 0.03524878159356229,
    "diff_bootstrap_ci95_upper": 0.057576787940609775,
}
ATOL = 1e-6


def _frozen_main() -> pd.DataFrame:
    cfg = load_yaml(K1_CFG_YAML)
    df = pd.read_parquet(LITE_TABLE)
    df["cycle_month"] = df["timestamp_utc"].astype(str).str[:7]
    frozen = set(cfg["sample_roles"]["main_set"]["months"])
    df = df[df["cycle_month"].isin(frozen)]
    pilot_sess = df[df["pilot_available"]]["session_id"].unique()
    return df[df["session_id"].isin(pilot_sess)].copy()


def _session_id_set_sha256(df: pd.DataFrame) -> str:
    ids = sorted(df["session_id"].unique().astype(str))
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()


def _actual() -> dict:
    cfg = load_yaml(K1_CFG_YAML)
    thr = GapThresholds.from_cfg(cfg)
    df = _frozen_main()
    labeled, events, session_summary = process(df, thr)
    core = core_stats(events, labeled, thr)
    core_events = events[events["event_phase"] == "core_run_segment"]
    neg = negative_controls(
        labeled, events, thr, session_summary, core_events,
        perm_seeds=PERM_SEEDS, bootstrap_seed=BOOT_SEED, n_boot=N_BOOT,
    )
    perm = neg["time_permutation_core"]
    return {
        "n_main_sessions": int(labeled["session_id"].nunique()),
        "session_id_set_sha256": _session_id_set_sha256(labeled),
        "denominator_sessions_with_core_run": core["denominator_sessions_with_core_run"],
        "event_session_rate": core["event_session_rate"],
        "median_gap_kw": core["median_gap_kw"],
        "diff_bootstrap_ci95_lower": float(perm["diff_bootstrap_ci95"][0]),
        "diff_bootstrap_ci95_upper": float(perm["diff_bootstrap_ci95"][1]),
    }


@pytest.mark.skipif(
    not LITE_TABLE.exists(), reason="datasets/lite_session_minute.parquet 不存在（仓库外数据）"
)
def test_e1_stats_fidelity_to_frozen_k1() -> None:
    """e1_stats 必须逐位复现 K1 冻结样本（审查结论4 K1.2.2 最终版）。"""
    actual = _actual()
    for key, frozen_val in FROZEN.items():
        if isinstance(frozen_val, str):
            assert actual[key] == frozen_val, (
                f"e1_stats 漂移：{key} frozen={frozen_val!r} actual={actual[key]!r}"
            )
        else:
            assert abs(actual[key] - frozen_val) <= ATOL, (
                f"e1_stats 漂移：{key} frozen={frozen_val!r} actual={actual[key]!r} "
                f"（差 {abs(actual[key] - frozen_val):.2e}）"
            )


@pytest.mark.skipif(
    not LITE_TABLE.exists(), reason="datasets/lite_session_minute.parquet 不存在（仓库外数据）"
)
def test_e1_stats_fidelity_k1_sample_size() -> None:
    """冻结样本合格会话数不变（5,961）——母体没被悄悄换。"""
    df = _frozen_main()
    assert df["session_id"].nunique() == 5_961
