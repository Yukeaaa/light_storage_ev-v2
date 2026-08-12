"""P2.1A 模块单测（v1.3 §7 [4] synthetic/invariant tests，非 formal exposure）。

覆盖：risk_set / outcome / triggers / b3_map / metrics / bootstrap / sufficiency / gate。
只用合成池（_p2_helpers），不触真实数据、不碰 sentinel。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from patent_preexperiment.phase3_p2.schema import load_schema
from patent_preexperiment.phase3_p2_1.b3_map import _b3_selected_cycle_rows, build_b3_map
from patent_preexperiment.phase3_p2_1.bootstrap import (
    bootstrap_delta_distributions,
    percentile_ci,
    seed_from_string,
)
from patent_preexperiment.phase3_p2_1.frozen import FROZEN
from patent_preexperiment.phase3_p2_1.gate import a_gate_verdict
from patent_preexperiment.phase3_p2_1.metrics import (
    build_trigger_counts,
    build_trigger_table,
    point_metrics,
)
from patent_preexperiment.phase3_p2_1.outcome import compute_y
from patent_preexperiment.phase3_p2_1.risk_set import (
    build_boundary_frame_sorted,
    build_eligible_risk_set,
    eligible_mask,
)
from patent_preexperiment.phase3_p2_1.sufficiency import evaluate_sufficiency
from patent_preexperiment.phase3_p2_1.triggers import (
    B0,
    B1,
    B2A,
    B2B,
    B3,
    B4,
    trigger_masks,
)
from tests._p2_helpers import make_session

PP = Path(__file__).resolve().parents[1]
SCFG = load_schema(PP / "configs" / "phase3_p2_action_schema.yaml")

CONSTANT = 5.0


def _pool(sessions: list[pd.DataFrame]) -> pd.DataFrame:
    return pd.concat(sessions, ignore_index=True)


def _stable_session(sid: str, n_minutes: int = 35, actual: float = CONSTANT) -> pd.DataFrame:
    return make_session(
        sid, site="jpl", field_mode="current_only", n_minutes=n_minutes, actual=actual
    )


# ---------------------------------------------------------------------------
# risk_set
# ---------------------------------------------------------------------------

def test_eligible_rows_constant_session() -> None:
    pool = _pool([_stable_session("s01")])  # 35 min，constant 5.0
    bf = build_boundary_frame_sorted(pool, SCFG)
    elig = build_eligible_risk_set(pool, SCFG)

    # 单 run；eligible = 5..24（history>=5 且 post-window t+10 <= 34）
    assert bf["run_id"].nunique() == 1
    assert len(elig) == 20
    assert (elig["protective_bound"] == CONSTANT).all()
    assert (elig["history_sufficient"] == True).all()  # noqa: E712
    assert (elig["post_window_ok"] == True).all()  # noqa: E712
    assert elig["segment_id"].nunique() == 1
    assert elig["segment_id"].iloc[0] == "s01#1"
    # eligible index 是 bf 的子集
    assert set(elig.index).issubset(set(bf.index))


def test_eligible_excludes_history_insufficient() -> None:
    pool = _pool([_stable_session("s02")])
    bf = build_boundary_frame_sorted(pool, SCFG)
    elig = build_eligible_risk_set(pool, SCFG)
    # 前 5 行 history 不足 → 不在 eligible
    assert not (bf.index[:5].isin(elig.index)).any()


def test_severe_gap_splits_run_and_blocks_window() -> None:
    severe = [False] * 12 + [True] + [False] * 22
    pool = _pool(
        [make_session("s03", "jpl", "current_only", 35, actual=CONSTANT, severe_gap=severe)]
    )
    bf = build_boundary_frame_sorted(pool, SCFG)
    assert bf["run_id"].nunique() == 2
    elig = build_eligible_risk_set(pool, SCFG)
    # run 起点行（index 12）不 eligible（post_window_ok=False）
    assert 12 not in elig.index


def test_nan_actual_excluded() -> None:
    actual = [5.0] * 10 + [np.nan] + [5.0] * 24
    pool = _pool(
        [make_session("s04", "jpl", "current_only", 35, actual=actual)]
    )
    elig = build_eligible_risk_set(pool, SCFG)
    assert 10 not in elig.index  # NaN actual 行不 eligible


# ---------------------------------------------------------------------------
# outcome
# ---------------------------------------------------------------------------

def test_y_positive_constant_and_negative_on_drop() -> None:
    const_bf = build_boundary_frame_sorted(_pool([_stable_session("s05")]), SCFG)
    y_const = compute_y(const_bf)
    assert y_const.loc[5] == 1.0
    assert y_const.loc[7] == 1.0

    actual = [6.0] * 12 + [0.5] * 30
    drop_bf = build_boundary_frame_sorted(
        _pool([make_session("s06", "jpl", "current_only", 42, actual=actual)]), SCFG
    )
    y_drop = compute_y(drop_bf)
    assert y_drop.loc[12] == 0.0  # post-window rows 13..22 全 0.5 < 0.9×pb(6.0)
    assert y_drop.loc[20] == 0.0


def test_y_nan_outside_post_window_ok() -> None:
    bf = build_boundary_frame_sorted(_pool([_stable_session("s07")]), SCFG)
    y = compute_y(bf)
    assert np.isnan(y.loc[len(bf) - 1])  # 末行无 post-window
    elig = build_eligible_risk_set(_pool([_stable_session("s07")]), SCFG)
    y_elig = compute_y(bf).loc[elig.index]
    assert y_elig.notna().all()


# ---------------------------------------------------------------------------
# triggers
# ---------------------------------------------------------------------------

def test_b0_triggers_after_3_sustained_cycles() -> None:
    pool = _pool([_stable_session("s08")])
    bf = build_boundary_frame_sorted(pool, SCFG)
    masks = trigger_masks(bf, SCFG)
    b0 = masks[B0].to_numpy(dtype=bool)
    # pb 自 row5 有值 → cond row5 起；连续 3 → row7 起
    assert not b0[:6].any()
    assert bool(b0[7])
    assert b0[8:].all()


def test_b0_off_when_actual_drops_below_0_95pb() -> None:
    actual = [6.0] * 15 + [1.0] * 25
    pool = _pool([make_session("s09", "jpl", "current_only", 40, actual=actual)])
    bf = build_boundary_frame_sorted(pool, SCFG)
    masks = trigger_masks(bf, SCFG)
    b0 = masks[B0].to_numpy(dtype=bool)
    # actual=1.0 < 0.95×pb(≈6.0) → B0 关闭；直到 pb 自适应到 1.0 后才重开（row 32+）
    assert not b0[15:32].any()


def test_b1_persistence_on_constant() -> None:
    pool = _pool([_stable_session("s10")])
    bf = build_boundary_frame_sorted(pool, SCFG)
    masks = trigger_masks(bf, SCFG)
    b1 = masks[B1].to_numpy(dtype=bool)
    assert not b1[:2].any()
    assert b1[2:].all()  # constant → max−min=0 ≤ 5%×median


def test_b1_off_when_varying() -> None:
    actual = [5.0, 1.0, 8.0] * 12
    pool = _pool([make_session("s11", "jpl", "current_only", 36, actual=actual)])
    bf = build_boundary_frame_sorted(pool, SCFG)
    masks = trigger_masks(bf, SCFG)
    b1 = masks[B1].to_numpy(dtype=bool)
    assert not b1.any()  # 每个 3 窗都 >5% 变化


def test_b2_rolling_shift_causal() -> None:
    pool = _pool([_stable_session("s12")])
    bf = build_boundary_frame_sorted(pool, SCFG)
    masks = trigger_masks(bf, SCFG)
    b2a = masks[B2A].to_numpy(dtype=bool)
    b2b = masks[B2B].to_numpy(dtype=bool)
    # shift(1) + min_periods=1 → row1 起有滚动值；连续 3 → row3 起
    assert not b2a[:2].any() and not b2b[:2].any()
    assert b2a[3:].all() and b2b[3:].all()


def test_b4_lag_shuffle_equals_b0_on_constant() -> None:
    pool = _pool([_stable_session("s13")])
    bf = build_boundary_frame_sorted(pool, SCFG)
    masks = trigger_masks(bf, SCFG)
    # constant 下 lag1(actual)==actual → B4 与 B0 一致
    assert (masks[B4].to_numpy() == masks[B0].to_numpy()).all()


def test_trigger_masks_not_crossing_run() -> None:
    severe = [False] * 7 + [True] + [False] * 27
    pool = _pool(
        [make_session("s14", "jpl", "current_only", 35, actual=CONSTANT, severe_gap=severe)]
    )
    bf = build_boundary_frame_sorted(pool, SCFG)
    masks = trigger_masks(bf, SCFG)
    b0 = masks[B0].to_numpy(dtype=bool)
    # 连续 3 不跨 run；run2 从 row7 起，pb 需 5 历史样本 → row12 起有 pb，b0 row14 起连续 3
    assert not b0[8]  # run2 前 2 行不足 3 连续
    assert not b0[13]  # pb 刚建立但不足 3 连续
    assert bool(b0[14])


# ---------------------------------------------------------------------------
# b3_map
# ---------------------------------------------------------------------------

def test_b3_map_deterministic_and_one_per_segment() -> None:
    pool = _pool([_stable_session(f"s15_{i}") for i in range(6)])
    elig = build_eligible_risk_set(pool, SCFG)
    m1 = build_b3_map(elig)
    m2 = build_b3_map(elig)
    assert m1.equals(m2)  # C2：确定性 realization
    assert len(m1) == elig["segment_id"].nunique() == 6
    assert m1["segment_id"].nunique() == 6
    # 每 segment 的 trigger 行必须来自该 segment 的 eligible 行
    rows = _b3_selected_cycle_rows(elig, m1)
    assert len(rows) == 6
    assert set(rows["segment_id"]) == set(elig["segment_id"])


def test_b3_map_no_builtin_hash() -> None:
    """C2：B3 map 用稳定 md5 映射；同一 segment 两次调用得到同一 realization。"""
    pool = _pool([_stable_session("s16")])
    elig = build_eligible_risk_set(pool, SCFG)
    m = build_b3_map(elig)
    first = m["timestamp_utc"].iloc[0]
    m_again = build_b3_map(elig)
    assert m_again["timestamp_utc"].iloc[0] == first


def test_build_or_load_b3_map_once_only(tmp_path) -> None:
    """C2 一次生成、永久固定：已存在则 load+校验、不覆盖；不同则 hard fail。"""
    from patent_preexperiment.phase3_p2_1.b3_map import build_or_load_b3_map

    pool = _pool([_stable_session(f"bl_{i}") for i in range(3)])
    elig = build_eligible_risk_set(pool, SCFG)
    apath = tmp_path / "b3.parquet"

    first = build_or_load_b3_map(elig, apath)
    assert apath.exists()
    first_bytes = apath.read_bytes()

    # 第二次：eligible 相同 → 复用，不覆盖
    second = build_or_load_b3_map(elig, apath)
    assert apath.read_bytes() == first_bytes  # 文件未被重写
    assert second.equals(first)

    # eligible 变化（多一个 session）→ hard fail
    pool2 = _pool([_stable_session(f"bl_{i}") for i in range(4)])
    elig2 = build_eligible_risk_set(pool2, SCFG)
    with pytest.raises(RuntimeError, match="C2 漂移"):
        build_or_load_b3_map(elig2, apath)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def test_trigger_counts_step0_safe_no_y() -> None:
    pool = _pool([_stable_session(f"s17_{i}") for i in range(6)])
    bf = build_boundary_frame_sorted(pool, SCFG)
    elig = bf.loc[eligible_mask(bf)].copy()
    masks = {m: s.reindex(elig.index) for m, s in trigger_masks(bf, SCFG).items()}
    b3_map = build_b3_map(elig)
    counts = build_trigger_counts(elig, masks, b3_map)
    assert "y" not in counts.columns  # Step-0 隔离：无 Y
    assert counts["method"].nunique() == 6
    # constant 会话全部触发：每 method 每 segment 1 行
    assert len(counts) == 6 * 6


def test_build_trigger_table_merges_y() -> None:
    sessions = [_stable_session(f"s18_{i}", actual=5.0) for i in range(2)]
    sessions.append(
        make_session(
            "s18_drop", "jpl", "current_only", 42, actual=[6.0] * 12 + [0.5] * 30
        )
    )
    pool = _pool(sessions)
    bf = build_boundary_frame_sorted(pool, SCFG)
    elig = bf.loc[eligible_mask(bf)].copy()
    masks = {m: s.reindex(elig.index) for m, s in trigger_masks(bf, SCFG).items()}
    b3_map = build_b3_map(elig)
    counts = build_trigger_counts(elig, masks, b3_map)
    y = compute_y(bf).loc[elig.index]
    table = build_trigger_table(counts, elig, y)
    assert "y" in table.columns
    assert table["y"].dtype == bool
    # drop 会话的 B0 trigger（首个 B0 在行 7，Y=0）
    row = table[(table["session_id"] == "s18_drop") & (table["method"] == B0)]
    assert len(row) == 1
    assert bool(row["y"].iloc[0]) is False


def test_point_metrics_gain_delta() -> None:
    sessions = [_stable_session(f"s19_{i}") for i in range(6)]
    pool = _pool(sessions)
    bf = build_boundary_frame_sorted(pool, SCFG)
    elig = bf.loc[eligible_mask(bf)].copy()
    masks = {m: s.reindex(elig.index) for m, s in trigger_masks(bf, SCFG).items()}
    b3_map = build_b3_map(elig)
    counts = build_trigger_counts(elig, masks, b3_map)
    y = compute_y(bf).loc[elig.index]
    table = build_trigger_table(counts, elig, y)
    n_seg = int(elig["segment_id"].nunique())
    pm = point_metrics(table, n_seg)
    # constant：所有 trigger Y=1 → gain=1.0
    assert pm["gains"][B0] == 1.0
    assert pm["coverage"][B0] == 1.0
    assert pm["delta_b1"] == 0.0
    assert pm["delta_b3"] == 0.0
    assert pm["n_eligible_segments"] == n_seg


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------

def test_seed_from_string_stable() -> None:
    assert seed_from_string("20260813_B") == seed_from_string("20260813_B")
    assert isinstance(seed_from_string("20260813_B"), int)


def test_bootstrap_deterministic_and_ci() -> None:
    pool = _pool([_stable_session(f"s20_{i}") for i in range(8)])
    bf = build_boundary_frame_sorted(pool, SCFG)
    elig = bf.loc[eligible_mask(bf)].copy()
    masks = {m: s.reindex(elig.index) for m, s in trigger_masks(bf, SCFG).items()}
    b3_map = build_b3_map(elig)
    counts = build_trigger_counts(elig, masks, b3_map)
    y = compute_y(bf).loc[elig.index]
    table = build_trigger_table(counts, elig, y)

    eligible_sessions = elig["session_id"].unique()
    d1 = bootstrap_delta_distributions(table, eligible_sessions, n_boot=100)
    d2 = bootstrap_delta_distributions(table, eligible_sessions, n_boot=100)
    assert np.array_equal(d1["delta_b1"], d2["delta_b1"], equal_nan=True)
    assert d1["n_boot"] == 100
    assert d1["n_sessions"] == len(eligible_sessions)
    for name in ("delta_b1", "delta_b3", "delta_b2"):
        lo, hi = percentile_ci(d1[name])
        assert lo <= hi


def test_bootstrap_functional_delta_b2_per_replicate() -> None:
    """Δ(B2) 在 replicate 内取 max(gain(B2a), gain(B2b))。"""
    # 构造触发表：B0/B2a 全 Y=1；B2b 全 Y=0 → functional max 总是 B2a → Δ=0
    n = 40
    sessions = [f"s21_{i}" for i in range(n)]
    rows = []
    for sid in sessions:
        for method, yy in ((B0, 1), (B2A, 1), (B2B, 0)):
            rows.append({"session_id": sid, "segment_id": f"{sid}#1",
                         "method": method, "cycle_index": 3, "y": bool(yy)})
    table = pd.DataFrame(rows)
    eligible_sessions = np.asarray(sessions)
    dist = bootstrap_delta_distributions(table, eligible_sessions, n_boot=50)
    # 每 replicate：gain(B2a)=1 → best=1 → Δ(B2)=gain(B0)−1=0
    assert np.allclose(np.nan_to_num(dist["delta_b2"]), 0.0, atol=1e-12)


# ---------------------------------------------------------------------------
# sufficiency
# ---------------------------------------------------------------------------

def test_sufficiency_sufficient_with_many_sessions() -> None:
    sessions = [_stable_session(f"s22_{i}") for i in range(120)]
    pool = _pool(sessions)
    bf = build_boundary_frame_sorted(pool, SCFG)
    elig = bf.loc[eligible_mask(bf)].copy()
    masks = {m: s.reindex(elig.index) for m, s in trigger_masks(bf, SCFG).items()}
    b3_map = build_b3_map(elig)
    counts = build_trigger_counts(elig, masks, b3_map)
    suff = evaluate_sufficiency(elig, counts)
    assert suff.sufficient is True
    assert suff.n_eligible_segments >= 100
    for m in (B0, B1, B2A, B2B, B3, B4):
        assert suff.trigger_sessions[m] >= 30


def test_sufficiency_insufficient_with_few_sessions() -> None:
    sessions = [_stable_session(f"s23_{i}") for i in range(5)]
    pool = _pool(sessions)
    bf = build_boundary_frame_sorted(pool, SCFG)
    elig = bf.loc[eligible_mask(bf)].copy()
    masks = {m: s.reindex(elig.index) for m, s in trigger_masks(bf, SCFG).items()}
    b3_map = build_b3_map(elig)
    counts = build_trigger_counts(elig, masks, b3_map)
    suff = evaluate_sufficiency(elig, counts)
    assert suff.sufficient is False
    assert "eligible_segments" in suff.failed


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------

def _point_fixture() -> dict:
    gains = {B0: 0.8, B1: 0.5, B2A: 0.6, B2B: 0.7, B3: 0.5, B4: 0.5}
    cov = {B0: 0.5, B1: 0.4, B2A: 0.5, B2B: 0.5, B3: 1.0, B4: 0.5}
    lat = {B0: 5.0, B1: 4.0, B2A: 3.0, B2B: 3.0, B3: 5.0, B4: 5.0}
    return {
        "gains": gains,
        "delta_b1": gains[B0] - gains[B1],
        "delta_b3": gains[B0] - gains[B3],
        "delta_b2": gains[B0] - max(gains[B2A], gains[B2B]),
        "best_rolling": max(gains[B2A], gains[B2B]),
        "coverage": cov,
        "latency": lat,
        "n_triggers": {m: 10 for m in (B0, B1, B2A, B2B, B3, B4)},
        "n_eligible_segments": 10,
    }


def test_gate_pass_all_six() -> None:
    point = _point_fixture()
    cis = {"delta_b1": (0.2, 0.4), "delta_b3": (0.2, 0.4), "delta_b2": (0.05, 0.2)}
    g = a_gate_verdict(point, cis)
    assert g.verdict == "PASS"
    assert len(g.conditions) == 6  # c1..c6（c3=gain(B0)>gain(B4) 现为正式条件）
    assert all(g.conditions.values())
    assert g.conditions["c3_b4_dominance"] is True  # gain(B0)=0.8 > gain(B4)=0.5


def test_gate_fail_when_b4_not_dominant() -> None:
    """Blocker 1：gain(B0)<=gain(B4) 是正式 FAIL 条件 c3。"""
    point = _point_fixture()
    point["gains"][B4] = 0.85  # gain(B4) > gain(B0)=0.8
    cis = {"delta_b1": (0.2, 0.4), "delta_b3": (0.2, 0.4), "delta_b2": (0.05, 0.2)}
    g = a_gate_verdict(point, cis)
    assert g.verdict == "FAIL"
    assert g.conditions["c3_b4_dominance"] is False
    assert "c3_b4_dominance" in g.failed_conditions


def test_gate_fail_when_ci_lower_nonpositive() -> None:
    point = _point_fixture()
    cis = {"delta_b1": (-0.1, 0.2), "delta_b3": (0.2, 0.4), "delta_b2": (0.05, 0.2)}
    g = a_gate_verdict(point, cis)
    assert g.verdict == "FAIL"
    assert g.conditions["c1_delta_b1"] is False
    assert "c1_delta_b1" in g.failed_conditions


def test_gate_fail_when_delta_b2_ci_nonpositive() -> None:
    point = _point_fixture()
    cis = {"delta_b1": (0.2, 0.4), "delta_b3": (0.2, 0.4), "delta_b2": (-0.05, 0.05)}
    g = a_gate_verdict(point, cis)
    assert g.verdict == "FAIL"
    assert g.conditions["c6_delta_b2"] is False
    assert "c6_delta_b2" in g.failed_conditions


def test_gate_fail_when_ci_nan() -> None:
    point = _point_fixture()
    cis = {"delta_b1": (np.nan, np.nan), "delta_b3": (0.2, 0.4), "delta_b2": (0.05, 0.2)}
    g = a_gate_verdict(point, cis)
    assert g.verdict == "FAIL"


def test_gate_fail_coverage_or_latency_ni() -> None:
    point = _point_fixture()
    point["coverage"][B0] = 0.1  # 0.1 < 0.8×0.4=0.32
    cis = {"delta_b1": (0.2, 0.4), "delta_b3": (0.2, 0.4), "delta_b2": (0.05, 0.2)}
    g = a_gate_verdict(point, cis)
    assert g.verdict == "FAIL"
    assert g.conditions["c4_coverage_ni"] is False

    point2 = _point_fixture()
    point2["latency"][B0] = 10.0  # 10 > 4+3=7
    g2 = a_gate_verdict(point2, cis)
    assert g2.verdict == "FAIL"
    assert g2.conditions["c5_latency_ni"] is False


# ---------------------------------------------------------------------------
# runner sentinel 治理（Blocker 4 / 6）——纯治理逻辑，monkeypatch 掉真实数据/git
# ---------------------------------------------------------------------------

def _write_synthetic_sentinel(root: Path, **over: Any) -> None:
    """写一个符合 v1.3 身份的合成 sentinel（便于治理测试）。"""
    base = {
        "experiment_id": FROZEN.experiment_id,
        "protocol_version": FROZEN.protocol_version,
        "frozen_protocol_commit_sha": FROZEN.frozen_protocol_commit_sha,
        "frozen_protocol_blob_sha": FROZEN.frozen_protocol_blob_sha,
        "status": "UNCONSUMED",
        "once_only": True,
    }
    base.update(over)
    (root / "results" / "raw" / "phase3_p2_1").mkdir(parents=True, exist_ok=True)
    (root / "results" / "raw" / "phase3_p2_1" / "p2_1a_sentinel.json").write_text(
        json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_sentinel_strict_rejects_missing(tmp_path) -> None:
    from patent_preexperiment.phase3_p2_1.runner import _read_sentinel_strict

    with pytest.raises(RuntimeError, match="sentinel 缺失"):
        _read_sentinel_strict(tmp_path)


def test_sentinel_strict_rejects_identity_drift(tmp_path) -> None:
    from patent_preexperiment.phase3_p2_1.runner import _read_sentinel_strict

    _write_synthetic_sentinel(tmp_path, frozen_protocol_blob_sha="tampered")
    with pytest.raises(RuntimeError, match="身份字段 frozen_protocol_blob_sha 漂移"):
        _read_sentinel_strict(tmp_path)


def test_step0_rejects_consumed_sentinel(tmp_path) -> None:
    """Blocker 4：CONSUMED sentinel 不能再跑 Step-0（防复活）。"""
    from patent_preexperiment.phase3_p2_1.runner import run_step0

    _write_synthetic_sentinel(tmp_path, status="CONSUMED")
    with pytest.raises(RuntimeError, match="拒绝"):
        run_step0(tmp_path)


def test_step0_rejects_when_impl_sha_not_locked(tmp_path) -> None:
    """Blocker 6：Step-0 前必须先 --lock-impl。"""
    from patent_preexperiment.phase3_p2_1.runner import run_step0

    _write_synthetic_sentinel(tmp_path)  # 无 implementation_code_sha
    with pytest.raises(RuntimeError, match="implementation_code_sha 未锁"):
        run_step0(tmp_path)


def test_step0_does_not_write_status(tmp_path, monkeypatch) -> None:
    """Blocker 4：Step-0 只附加 sufficiency，不写 status（保持 UNCONSUMED）。"""
    from patent_preexperiment.phase3_p2_1 import runner

    _write_synthetic_sentinel(tmp_path, implementation_code_sha="abc123")

    monkeypatch.setattr(runner, "git_provenance", lambda _r: {
        "code_sha": "abc123", "worktree_clean": True,
    })
    # Step-0 数据管线 monkeypatch：构造最小 eligible/trigger_counts 让 sufficiency 通过
    elig = pd.DataFrame({
        "session_id": [f"s{i}" for i in range(120)],
        "segment_id": [f"s{i}#1" for i in range(120)],
    })
    counts_rows = []
    for i in range(120):
        for m in (B0, B1, B2A, B2B, B3, B4):
            counts_rows.append({"session_id": f"s{i}", "segment_id": f"s{i}#1",
                                "method": m, "cycle_index": 7})
    counts = pd.DataFrame(counts_rows)

    def fake_artifacts(_root):
        out = tmp_path / "results" / "raw" / "phase3_p2_1"
        out.mkdir(parents=True, exist_ok=True)
        paths = {
            "boundary_frame": out / "bf.parquet",
            "eligible": out / "elig.parquet",
            "b3_map": out / "b3.parquet",
            "trigger_counts": out / "tc.parquet",
        }
        elig.to_parquet(paths["eligible"], index=False)
        counts.to_parquet(paths["trigger_counts"], index=False)
        pd.DataFrame().to_parquet(paths["boundary_frame"], index=False)
        pd.DataFrame().to_parquet(paths["b3_map"], index=False)
        return {"paths": {k: str(v.as_posix()) for k, v in paths.items()},
                "sha256": {k: "x" for k in paths}}

    monkeypatch.setattr(runner, "_step0_artifacts", fake_artifacts)
    runner.run_step0(tmp_path)

    s_after = json.loads(
        (tmp_path / "results" / "raw" / "phase3_p2_1" / "p2_1a_sentinel.json").read_text()
    )
    assert s_after["status"] == "UNCONSUMED"  # Step-0 不改 status
    assert s_after["step0_data_sufficiency_status"] == "SUFFICIENT"


def test_formal_rejects_when_artifact_sha_drifts(tmp_path, monkeypatch) -> None:
    """Blocker 5：formal 逐个 SHA256 校验 step0 artifact；漂移 → fail-closed。"""
    from patent_preexperiment.phase3_p2_1 import runner

    _write_synthetic_sentinel(
        tmp_path, implementation_code_sha="abc123",
        step0_data_sufficiency_status="SUFFICIENT",
        step0_summary_sha256="will_be_set",
        step0_artifacts={
            "boundary_frame": "results/raw/phase3_p2_1/bf.parquet",
            "eligible": "results/raw/phase3_p2_1/elig.parquet",
            "b3_map": "results/raw/phase3_p2_1/b3.parquet",
            "trigger_counts": "results/raw/phase3_p2_1/tc.parquet",
        },
        step0_artifact_sha256={
            "boundary_frame": "deadbeef",  # 故意错的 sha
            "eligible": "deadbeef",
            "b3_map": "deadbeef",
            "trigger_counts": "deadbeef",
        },
    )
    out = tmp_path / "results" / "raw" / "phase3_p2_1"
    out.mkdir(parents=True, exist_ok=True)
    for name in ("bf", "elig", "b3", "tc"):
        (out / f"{name}.parquet").write_bytes(b"data")
    step0 = {
        "sufficiency": {"sufficient": True},
        "artifacts": {
            "paths": {
                "boundary_frame": "results/raw/phase3_p2_1/bf.parquet",
                "eligible": "results/raw/phase3_p2_1/elig.parquet",
                "b3_map": "results/raw/phase3_p2_1/b3.parquet",
                "trigger_counts": "results/raw/phase3_p2_1/tc.parquet",
            },
            "sha256": {
                "boundary_frame": "deadbeef",
                "eligible": "deadbeef",
                "b3_map": "deadbeef",
                "trigger_counts": "deadbeef",
            },
        },
    }
    (out / "p2_1a_step0.json").write_text(json.dumps(step0), encoding="utf-8")
    # 修正 sentinel 里的 step0_summary_sha256 为真实值
    true_step0_sha = runner._file_sha256(out / "p2_1a_step0.json")
    s = runner._read_sentinel_strict(tmp_path)
    s["step0_summary_sha256"] = true_step0_sha
    runner._write_sentinel(tmp_path, s)

    monkeypatch.setattr(runner, "git_provenance", lambda _r: {
        "code_sha": "abc123", "worktree_clean": True,
    })
    monkeypatch.setattr(runner, "_assert_evidence_only_diff", lambda *_a, **_k: None)

    with pytest.raises(RuntimeError, match="artifact integrity"):
        runner.run_formal_test(tmp_path)


def test_assert_d3_trigger_params_match_called_in_load_pool(tmp_path, monkeypatch) -> None:
    """Blocker 3：_load_pool 必须调用 assert_d3_trigger_params_match。"""
    from patent_preexperiment.phase3_p2_1 import runner

    called = {"n": 0}

    class _FakeScfg:
        history_quantile = 0.95
        history_window_min = 15
        history_min_samples = 5
        min_history_samples = 5
        recovery_ratio = 0.95
        recovery_sustained_cycles = 3

    def fake_load_schema(_p):
        return _FakeScfg()

    def fake_assert(scfg):
        called["n"] += 1

    monkeypatch.setattr(runner, "load_schema", fake_load_schema)
    monkeypatch.setattr(
        "patent_preexperiment.phase3_p2_1.runner.assert_d3_trigger_params_match", fake_assert
    )
    # registry/pool 也要 patch 避免 IO
    monkeypatch.setattr(runner.pd, "read_parquet", lambda _p: pd.DataFrame())
    monkeypatch.setattr(runner, "load_pool_minutes", lambda *_a, **_k: pd.DataFrame())
    runner._load_pool(tmp_path)
    assert called["n"] == 1
