"""R1 E1 fidelity machine check（审查结论26 P1）：锁死 e1_stats 对 K1 冻结样本的复现。

只跑 K1 冻结样本（lite 主表 ∩ caltech CG1 冻结 6 月 ∩ pilot 会话），不碰 E1 test。
任何人修改 src/patent_preexperiment/response/e1_stats.py 后运行本脚本，
若 K1 冻结数值（core_denom/rate/median_gap/置换 CI）漂移则退出码非 0。
输出 results/raw/E1F/R1_E1_fidelity.json（可提交证据）。

冻结值来源：results/raw/E1L/e1_lite_summary.json（K1.2.2 最终冻结版）：
  n_main_sessions = 5961
  session_id_set_sha256 = 29517fcc615aa0b6bc718ebaa13dfd799f41de862e1cbc24a3a5b3cb490f349d
  denominator_sessions_with_core_run = 2941
  event_session_rate = 0.11866712002720163
  median_gap_kw = 1.2793999999999999
  diff_bootstrap_ci95 = [0.03524878159356229, 0.057576787940609775]
种子按 e1_lite/run.py：permutation=[42,2024,777]，bootstrap_seed=42，n_boot=2000。
session_id_set_sha256 = sha256("\n".join(sorted(冻结 K1 样本 session_id)))，防止母体
被悄悄换人（数对但集合不对）。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.response.e1_stats import core_stats, negative_controls, process
from patent_preexperiment.response.events import GapThresholds

IMPL = Path(__file__).resolve().parents[2]  # patent_preexperiment
OUT = IMPL / "results" / "raw" / "E1F"
LITE_TABLE = IMPL / "datasets" / "lite_session_minute.parquet"
K1_CFG = load_yaml(IMPL / "configs" / "k1_preregister.yaml")

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


def load_frozen_main(cfg: dict) -> pd.DataFrame:
    """复刻 e1_lite._load_main：lite 主表 ∩ 冻结 6 个月 ∩ pilot 会话（CG1 已在表中）。"""
    df = pd.read_parquet(LITE_TABLE)
    df["cycle_month"] = df["timestamp_utc"].astype(str).str[:7]
    frozen = set(cfg["sample_roles"]["main_set"]["months"])
    df = df[df["cycle_month"].isin(frozen)]
    pilot_sess = df[df["pilot_available"]]["session_id"].unique()
    return df[df["session_id"].isin(pilot_sess)].copy()


def _session_id_set_sha256(df: pd.DataFrame) -> str:
    ids = sorted(df["session_id"].unique().astype(str))
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()


def run_fidelity() -> dict:
    thr = GapThresholds.from_cfg(K1_CFG)
    df = load_frozen_main(K1_CFG)
    labeled, events, session_summary = process(df, thr)
    core = core_stats(events, labeled, thr)
    core_events = events[events["event_phase"] == "core_run_segment"]
    neg = negative_controls(
        labeled, events, thr, session_summary, core_events,
        perm_seeds=PERM_SEEDS, bootstrap_seed=BOOT_SEED, n_boot=N_BOOT,
    )
    perm = neg["time_permutation_core"]

    actual = {
        "n_main_sessions": int(labeled["session_id"].nunique()),
        "session_id_set_sha256": _session_id_set_sha256(labeled),
        "denominator_sessions_with_core_run": core["denominator_sessions_with_core_run"],
        "event_session_rate": core["event_session_rate"],
        "median_gap_kw": core["median_gap_kw"],
        "diff_bootstrap_ci95_lower": float(perm["diff_bootstrap_ci95"][0]),
        "diff_bootstrap_ci95_upper": float(perm["diff_bootstrap_ci95"][1]),
    }
    mismatches: list[str] = []
    for key, frozen_val in FROZEN.items():
        if key not in actual:
            mismatches.append(f"{key}: missing in actual")
            continue
        if isinstance(frozen_val, str):
            if actual[key] != frozen_val:
                mismatches.append(
                    f"{key}: frozen={frozen_val!r} actual={actual[key]!r}"
                )
        elif abs(actual[key] - frozen_val) > ATOL:
            mismatches.append(
                f"{key}: frozen={frozen_val!r} actual={actual[key]!r} "
                f"diff={abs(actual[key] - frozen_val):.2e}"
            )
    return {
        "experiment": "R1_E1_fidelity",
        "frozen_source": "results/raw/E1L/e1_lite_summary.json (K1.2.2 最终冻结版)",
        "seeds": {"permutation": PERM_SEEDS, "bootstrap_seed": BOOT_SEED, "n_boot": N_BOOT},
        "threshold": {
            k: getattr(thr, k)
            for k in ("p_on_kw", "delta_r", "delta_p_kw", "t_event_min",
                      "initial_exclusion_min", "tail_exclusion_min", "pilot_active_min_a")
        },
        "frozen": FROZEN,
        "actual": actual,
        "pass": not mismatches,
        "mismatches": mismatches,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    result = run_fidelity()
    (OUT / "R1_E1_fidelity.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
