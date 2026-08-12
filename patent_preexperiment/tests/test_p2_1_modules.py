"""P2.1A 模块单测（v1.3 §7 [4] synthetic/invariant tests，非 formal exposure）。

覆盖：risk_set / outcome / triggers / b3_map / metrics / bootstrap / sufficiency / gate。
只用合成池（_p2_helpers），不触真实数据、不碰 sentinel。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from patent_preexperiment.phase3_p2.schema import load_schema
from patent_preexperiment.phase3_p2_1.b3_map import _b3_selected_cycle_rows, build_b3_map
from patent_preexperiment.phase3_p2_1.bootstrap import (
    bootstrap_delta_distributions,
    percentile_ci,
    seed_from_string,
)
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

    d1 = bootstrap_delta_distributions(table, n_boot=100)
    d2 = bootstrap_delta_distributions(table, n_boot=100)
    assert np.array_equal(d1["delta_b1"], d2["delta_b1"], equal_nan=True)
    assert d1["n_boot"] == 100
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
    dist = bootstrap_delta_distributions(table, n_boot=50)
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


def test_gate_pass_all_five() -> None:
    point = _point_fixture()
    cis = {"delta_b1": (0.2, 0.4), "delta_b3": (0.2, 0.4), "delta_b2": (0.05, 0.2)}
    g = a_gate_verdict(point, cis)
    assert g.verdict == "PASS"
    assert all(g.conditions.values())
    assert g.b4_dominance is True  # 0.8 > 0.5


def test_gate_fail_when_ci_lower_nonpositive() -> None:
    point = _point_fixture()
    cis = {"delta_b1": (-0.1, 0.2), "delta_b3": (0.2, 0.4), "delta_b2": (0.05, 0.2)}
    g = a_gate_verdict(point, cis)
    assert g.verdict == "FAIL"
    assert g.conditions["c1_delta_b1"] is False
    assert "c1_delta_b1" in g.failed_conditions


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
