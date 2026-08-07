"""K1.2-E 最小回归测试（审查结论2，2026-08-07）。

覆盖边界：
- 跨会话滚动历史污染不得出现（会话 B 紧接会话 A）；
- 数据缺口/缺失周期→冷启动（历史失效，不沿用陈旧值）；
- 当前周期跨越 0.5kW 阈值或置 NaN 不改变已生成预算代理；
- 当前周期 pilot 后半段变化不进入周期开始时预算（决策时点=上一周期）；
- A2 严格等于上一连续 5min 周期，而非上一活跃周期；
- E1 事件在 core/mid 边界切断，各段重新执行持续>=T_event；
- eligible_mask 精确配对：各代理在完全相同 session 集合上评估。
- K1.2.1：bootstrap 分母与点估计同母体；done 能量按 post/tail/mid 拆分。
- K1.2.2：置换事件分子强制限制在 core_sessions 母体（审查结论4）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patent_preexperiment.allocation.opportunity import (
    build_cycles,
    compute_pool_stats,
    compute_proxies,
    eligible_mask,
)
from patent_preexperiment.metrics.bootstrap import bootstrap_session_diff_ci, core_run_session_ids
from patent_preexperiment.metrics.permutation import permutation_negative_control
from patent_preexperiment.response.done import add_done_phases, done_anchored_summary
from patent_preexperiment.response.events import GapThresholds, classify, detect_gap_events

PHASE_CORE = "core_run_segment"
PHASE_MID = "pre_done_mid"
SEED = 42


def _minutes(
    sess: str, start: str, actual: list[float], pilot: list[float] | None = None,
) -> pd.DataFrame:
    actual = np.asarray(actual, dtype=float)
    n = len(actual)
    idx = pd.date_range(start, periods=n, freq="min")
    p = np.full(n, np.nan) if pilot is None else np.asarray(pilot, dtype=float)
    return pd.DataFrame(
        {
            "session_id": sess,
            "station_id": f"st_{sess}",
            "site": "caltech",
            "garage": "CG1",
            "timestamp_utc": idx,
            "actual_power_kw": actual,
            "pilot_power_kw": p,
        }
    )


def _prox(df: pd.DataFrame) -> pd.DataFrame:
    cyc = build_cycles(df)
    pool = compute_pool_stats(cyc)
    return compute_proxies(cyc, pool)


def _prox_row(prox: pd.DataFrame, sess: str, start: str) -> pd.Series:
    sub = prox[(prox["session_id"] == sess) & (prox["cycle"] == pd.Timestamp(start))]
    assert len(sub) == 1, f"期望 {sess}@{start} 恰 1 行，实际 {len(sub)}"
    return sub.iloc[0]


# ---------- K1.2-A ----------


def test_no_cross_session_contamination() -> None:
    """会话 B 紧接会话 A：B 的滚动历史不得继承 A 的功率。"""
    a = _minutes("A", "2018-11-01 10:00", [6.0] * 60, pilot=[6.0] * 60)
    b = _minutes("B", "2018-11-01 11:00", [2.0] * 60, pilot=[4.0] * 60)
    prox = _prox(pd.concat([a, b], ignore_index=True))

    first = _prox_row(prox, "B", "2018-11-01 11:00")
    assert pd.isna(first["A2_prev_actual"]), "B 首周期必须冷启动（无历史）"
    assert pd.isna(first["actual_rollmax"]), "B 首周期滚动历史必须为 NaN"

    pb = prox[prox["session_id"] == "B"]
    assert float(pb["actual_rollmax"].max()) <= 2.0 + 1e-9, "B 滚动上界不得混入 A 的 6kW"

    third = _prox_row(prox, "B", "2018-11-01 11:10")
    assert third["actual_rollmax"] == pytest.approx(2.0, abs=1e-9)


def test_cold_start_after_data_gap() -> None:
    """中间停充 60 分钟：缺口后历史失效，恢复后只用自身历史。"""
    pre = _minutes("S", "2018-11-01 10:00", [3.0] * 20)
    post = _minutes("S", "2018-11-01 11:20", [2.0] * 20)
    prox = _prox(pd.concat([pre, post], ignore_index=True))

    assert _prox_row(prox, "S", "2018-11-01 10:05")["A2_prev_actual"] == pytest.approx(
        3.0, abs=1e-9
    )
    after = _prox_row(prox, "S", "2018-11-01 11:20")
    assert pd.isna(after["A2_prev_actual"]), "缺口后第一周期必须冷启动"
    assert pd.isna(after["actual_rollmax"])
    third = _prox_row(prox, "S", "2018-11-01 11:30")
    assert third["actual_rollmax"] == pytest.approx(2.0, abs=1e-9)


def test_current_cycle_crossing_threshold_does_not_change_proxies() -> None:
    """当前周期 3kW→0.1kW（跨越 0.5kW 活跃阈值）不改变已生成预算代理。"""
    df = _minutes("A", "2018-11-01 10:00", [3.0] * 60, pilot=[6.0] * 60)
    prox0 = _prox(df)
    t0 = pd.Timestamp("2018-11-01 10:30")
    b0 = _prox_row(prox0, "A", "2018-11-01 10:30")

    df2 = df.copy()
    m = (df2["timestamp_utc"] >= t0) & (df2["timestamp_utc"] < t0 + pd.Timedelta("5min"))
    df2.loc[m, "actual_power_kw"] = 0.1
    prox1 = _prox(df2)
    b1 = _prox_row(prox1, "A", "2018-11-01 10:30")

    for col in ("A0_avg", "A1_pilot", "A2_prev_actual", "A3_rolling_quantile",
                "A4_min_pilot_quantile", "actual_rollmax"):
        assert b0[col] == pytest.approx(b1[col], abs=1e-9), f"当前周期阈值跨越改变了 {col}"


def test_missing_current_cycle_expires_history() -> None:
    """当前周期置 NaN（整体缺失）：下一周期冷启动，不得沿用陈旧历史。"""
    df = _minutes("A", "2018-11-01 10:00", [3.0] * 60, pilot=[6.0] * 60)
    t0 = pd.Timestamp("2018-11-01 10:30")
    keep = ~((df["timestamp_utc"] >= t0) & (df["timestamp_utc"] < t0 + pd.Timedelta("5min")))
    df2 = df[keep].copy()
    prox1 = _prox(df2)

    nxt = t0 + pd.Timedelta("5min")
    after = prox1[(prox1["session_id"] == "A") & (prox1["cycle"] == nxt)]
    assert len(after) == 1
    assert pd.isna(after.iloc[0]["A2_prev_actual"]), "断档后 A2 必须失效，而非沿用 10:25 的 3.0"
    assert pd.isna(after.iloc[0]["actual_rollmax"])


def test_current_cycle_pilot_second_half_not_in_budget() -> None:
    """当前周期 pilot 后半段变化不进入周期开始时预算（决策时点=上一周期 pilot）。"""
    df = _minutes("A", "2018-11-01 10:00", [3.0] * 60, pilot=[6.0] * 60)
    prox0 = _prox(df)
    t0 = pd.Timestamp("2018-11-01 10:30")
    b0 = _prox_row(prox0, "A", "2018-11-01 10:30")

    df2 = df.copy()
    m = (df2["timestamp_utc"] >= t0 + pd.Timedelta("2min")) & (
        df2["timestamp_utc"] < t0 + pd.Timedelta("5min")
    )
    df2.loc[m, "pilot_power_kw"] = 10.0
    prox1 = _prox(df2)
    b1 = _prox_row(prox1, "A", "2018-11-01 10:30")

    for col in ("A1_pilot", "A4_min_pilot_quantile"):
        assert b0[col] == pytest.approx(b1[col], abs=1e-9), f"当前周期后半段 pilot 改变了 {col}"
    assert b1["A1_pilot"] == pytest.approx(6.0, abs=1e-9)


def test_a2_is_previous_continuous_cycle_not_previous_active() -> None:
    """A2 严格=上一连续 5min 周期实际功率，而非上一活跃周期。"""
    actual = [6.0] * 5 + [0.1] * 5 + [2.0] * 5
    df = _minutes("A", "2018-11-01 10:00", actual, pilot=[6.0] * 15)
    prox = _prox(df)

    r2 = _prox_row(prox, "A", "2018-11-01 10:05")
    assert r2["A2_prev_actual"] == pytest.approx(6.0, abs=1e-9)
    r3 = _prox_row(prox, "A", "2018-11-01 10:10")
    assert r3["active"] == True  # noqa: E712  当前周期活跃（评价标签）
    assert r3["A2_prev_actual"] == pytest.approx(0.1, abs=1e-9), "必须取上一连续周期 0.1，而非 6.0"


# ---------- K1.2-B ----------


def _gap_session_minutes(done_ts: pd.Timestamp, periods: int = 80) -> pd.DataFrame:
    idx = pd.date_range("2018-11-01 10:00", periods=periods, freq="min")
    return pd.DataFrame(
        {
            "session_id": "A",
            "station_id": "st_A",
            "site": "caltech",
            "garage": "CG1",
            "timestamp_utc": idx,
            "actual_power_kw": 3.0,
            "pilot_power_kw": 6.0,
            "current_a": 10.0,
            "connected_elapsed_min": 120.0,
            "minutes_from_end": 120.0,
            "gap_flag": False,
            "pilot_available": True,
            "pilot_a": 10.0,
            "done_charging_time": done_ts,
            "power_source": "measured",
        }
    )


def _thr() -> GapThresholds:
    return GapThresholds(
        p_on_kw=0.5, delta_r=0.25, delta_p_kw=0.5, t_event_min=5,
        initial_exclusion_min=5, tail_exclusion_min=10, pilot_active_min_a=1.0,
    )


def test_events_cut_at_phase_boundary() -> None:
    """连续 gap 跨越 core→mid 边界：切成两段，各段重新过 >=T_event。"""
    thr = _thr()
    df = _gap_session_minutes(pd.Timestamp("2018-11-01 13:00"))
    labeled = classify(df, thr)
    labeled = add_done_phases(labeled, thr.p_on_kw)
    ev = detect_gap_events(labeled, thr, phase_col="phase")

    core = ev[ev["phase"] == PHASE_CORE]
    mid = ev[ev["phase"] == PHASE_MID]
    n_core, n_mid = len(core), len(mid)
    assert n_core == 1 and n_mid == 1, f"期望 core 1 段 + mid 1 段，实际 {n_core}/{n_mid}"
    assert core.iloc[0]["duration_min"] == 60
    assert mid.iloc[0]["duration_min"] == 20
    assert ev["duration_min"].sum() == 80


def test_phase_segment_below_tevent_dropped() -> None:
    """mid 段 <T_event(5min) 时丢弃，不计入事件。"""
    thr = _thr()
    df = _gap_session_minutes(pd.Timestamp("2018-11-01 13:00"), periods=63)
    labeled = classify(df, thr)
    labeled = add_done_phases(labeled, thr.p_on_kw)
    ev = detect_gap_events(labeled, thr, phase_col="phase")

    core = ev[ev["phase"] == PHASE_CORE]
    mid = ev[ev["phase"] == PHASE_MID]
    assert len(core) == 1 and len(mid) == 0, "3min mid 段必须被丢弃"
    assert core.iloc[0]["duration_min"] == 60


# ---------- K1.2-C ----------


def test_eligible_mask_exact_session_intersection() -> None:
    """精确配对：含 pilot 代理时交集只剩有 pilot 会话；所有代理在完全同一会话集合上评估。"""
    a = _minutes("A", "2018-11-01 10:00", [3.0] * 60, pilot=[6.0] * 60)
    b = _minutes("B", "2018-11-01 10:00", [2.0] * 60)  # 无 pilot
    prox = _prox(pd.concat([a, b], ignore_index=True))

    assert prox.loc[prox["session_id"] == "B", "A4_min_pilot_quantile"].isna().all()

    el = eligible_mask(prox, ["A0_avg", "A2_prev_actual", "A3_rolling_quantile",
                              "A4_min_pilot_quantile"])
    sub = prox[el]
    assert set(sub["session_id"].unique()) == {"A"}, "含 pilot 代理时 B 必须被排除"
    for p in ("A0_avg", "A2_prev_actual", "A3_rolling_quantile", "A4_min_pilot_quantile"):
        assert sub[p].notna().all(), f"{p} 在精确交集内必须全部可计算"

    el2 = eligible_mask(prox, ["A2_prev_actual", "A3_rolling_quantile"])
    sub2 = prox[el2]
    assert set(sub2["session_id"].unique()) == {"A", "B"}, "仅实际类代理时 A、B 都应可计算"


# ---------- K1.2.1（审查结论3） ----------


def _core_labeled(sess: str, start: str, hours: int, pilot_kw: float = 6.0) -> pd.DataFrame:
    """构造有核心运行窗口的分钟表（done 在 hours 小时后，pilot 恒定>actual）。"""
    n = hours * 60
    done = pd.Timestamp(start) + pd.Timedelta(hours=hours)
    idx = pd.date_range(start, periods=n, freq="min")
    return pd.DataFrame(
        {
            "session_id": sess,
            "station_id": f"st_{sess}",
            "site": "caltech",
            "garage": "CG1",
            "timestamp_utc": idx,
            "actual_power_kw": 3.0,
            "pilot_power_kw": pilot_kw,
            "current_a": 10.0,
            "connected_elapsed_min": np.arange(n, dtype=float),
            "minutes_from_end": np.arange(n, 0, -1, dtype=float),
            "gap_flag": False,
            "pilot_available": True,
            "pilot_a": pilot_kw * 10.0,
            "done_charging_time": done,
            "power_source": "measured",
        }
    )


def _non_core_labeled(sess: str, start: str) -> pd.DataFrame:
    """构造无核心运行窗口的会话（done 在 60 min 内，全部属于 mid/tail）。"""
    thr = _thr()
    df = _gap_session_minutes(pd.Timestamp(start) + pd.Timedelta("60min"), periods=60)
    df["session_id"] = sess
    df["station_id"] = f"st_{sess}"
    labeled = classify(df, thr)
    return add_done_phases(labeled, thr.p_on_kw)


def test_permutation_bootstrap_uses_core_sessions_denominator() -> None:
    """K1.2.1-P0-1：bootstrap 母体=有核心运行窗口的会话，不是全部合格会话。"""
    thr = _thr()
    core = _core_labeled("C", "2018-11-01 10:00", hours=6)
    core_l = add_done_phases(classify(core, thr), thr.p_on_kw)
    non_core = _non_core_labeled("N", "2018-11-01 10:00")

    combined = pd.concat([core_l, non_core], ignore_index=True)
    ids = core_run_session_ids(combined)
    assert "C" in set(ids)
    assert "N" not in set(ids), "无核心运行窗口的会话不得进入 bootstrap 母体"

    # 点估计与 bootstrap 同分母：真实-置换差值的点估计应落在 bootstrap CI 内。
    real_rate = 1.0  # 单核心会话有事件，点估计=1/1
    perm_rate = 0.0  # 置换后无事件
    real_has = np.array([True])
    perm_has = np.array([[False]])
    lo, hi = bootstrap_session_diff_ci(real_has, perm_has, seed=SEED, n_boot=2000)
    point = real_rate - perm_rate
    assert lo <= point <= hi, "点估计必须落在 bootstrap CI 内（同分母要求）"


def test_done_anchored_energy_split() -> None:
    """K1.2.1-P1-1：energy_kwh_post_done 只含 post 能量，不再混入 tail。"""
    events = pd.DataFrame(
        {
            "event_phase": ["post_done", "post_done", "pre_done_tail", "pre_done_mid"],
            "gap_energy_kwh": [0.0, 0.0, 5.0, 3.0],
        }
    )
    s = done_anchored_summary(events)
    assert s["energy_kwh_post_done"] == pytest.approx(0.0, abs=1e-9)
    assert s["energy_kwh_pre_done_tail"] == pytest.approx(5.0, abs=1e-9)
    assert s["energy_kwh_pre_done_mid"] == pytest.approx(3.0, abs=1e-9)
    assert s["n_post_done"] == 2
    assert s["n_pre_done_tail"] == 1


# ---------- K1.2.2（审查结论4） ----------


def _core_hot_session(sess: str, start: str, hours: int) -> pd.DataFrame:
    """核心窗口会话：core 阶段持续高功率（真实有 core 事件），pilot 恒定>actual。"""
    n = hours * 60
    done = pd.Timestamp(start) + pd.Timedelta(hours=hours)
    idx = pd.date_range(start, periods=n, freq="min")
    return pd.DataFrame(
        {
            "session_id": sess,
            "station_id": f"st_{sess}",
            "site": "caltech",
            "garage": "CG1",
            "timestamp_utc": idx,
            "actual_power_kw": 1.0,
            "pilot_power_kw": 6.0,
            "current_a": 10.0,
            "connected_elapsed_min": np.arange(n, dtype=float),
            "minutes_from_end": np.arange(n, 0, -1, dtype=float),
            "gap_flag": False,
            "pilot_available": True,
            "pilot_a": 60.0,
            "done_charging_time": done,
            "power_source": "measured",
        }
    )


def _core_cold_hybrid_session(sess: str, start: str, hours: int) -> pd.DataFrame:
    """母体外会话：真实 core 阶段不活跃（0.1kW），但其他阶段有大量 1.0kW 分钟。

    置换后高概率把 1.0kW 移到 core 阶段 → 若不加母体过滤会在置换分子中出现，
    但该会话不在 core_run_session_ids（core 阶段无 charging_active 分钟）。
    """
    n = hours * 60
    done = pd.Timestamp(start) + pd.Timedelta(hours=hours)
    idx = pd.date_range(start, periods=n, freq="min")
    mtd = (done - idx).total_seconds() / 60.0
    core_mask = mtd > 120.0
    return pd.DataFrame(
        {
            "session_id": sess,
            "station_id": f"st_{sess}",
            "site": "caltech",
            "garage": "CG1",
            "timestamp_utc": idx,
            "actual_power_kw": np.where(core_mask, 0.1, 1.0),
            "pilot_power_kw": 6.0,
            "current_a": 10.0,
            "connected_elapsed_min": np.arange(n, dtype=float),
            "minutes_from_end": np.arange(n, 0, -1, dtype=float),
            "gap_flag": False,
            "pilot_available": True,
            "pilot_a": 60.0,
            "done_charging_time": done,
            "power_source": "measured",
        }
    )


def test_permutation_control_excludes_out_of_population_sessions() -> None:
    """K1.2.2-P0-1：真实 _permutation_control 路径下，置换分子强制限制在 core 母体。

    断言：
    1. bootstrap_n_sessions == core_denom（core_run_session_ids 行数）；
    2. 点估计、每种子置换率、diff 全部由 _real_has/_perm_has 同一布尔矩阵计算；
    3. 构造"真实 core 阶段不活跃、置换后可能在 core 阶段活跃"的母体外会话 X，
       确认它被过滤（不进入置换分子），且过滤前后计数一致（diagnostics）。
    """
    thr = _thr()
    c = _core_hot_session("C", "2018-11-01 10:00", hours=6)
    x = _core_cold_hybrid_session("X", "2018-11-01 10:00", hours=4)
    combined = pd.concat([c, x], ignore_index=True)
    labeled = add_done_phases(classify(combined, thr), thr.p_on_kw)

    sessions = core_run_session_ids(labeled)
    assert "C" in set(sessions)
    assert "X" not in set(sessions), "X 的真实 core 阶段不活跃，不得在 core 母体"

    real_events = _events_of(labeled, thr, PHASE_CORE)
    assert "X" not in set(real_events["session_id"]), "X 真实无 core 事件"
    res = permutation_negative_control(
        labeled, thr, real_events, perm_seeds=[42, 2024, 777],
        bootstrap_seed=SEED, n_boot=500,
    )

    real_has = res["_real_has"]
    perm_has = res["_perm_has"]

    # schema 统一：正常路径与不可评估路径均含 evaluable/reason
    assert res["evaluable"] is True
    assert res["reason"] is None

    # 1) bootstrap 母体 == core_denom
    assert res["bootstrap_n_sessions"] == len(sessions)
    # 2) 点估计/每种子置换率/diff 均来自同一布尔矩阵
    assert res["real_core_session_rate"] == pytest.approx(float(real_has.mean()), abs=1e-12)
    for i, seed_rec in enumerate(res["perm_rate_per_seed"]):
        assert seed_rec["core_session_rate"] == pytest.approx(
            float(perm_has[i].mean()), abs=1e-12
        ), f"seed {seed_rec['seed']} 置换率必须来自 perm_has 行均值"
    assert res["diff_real_minus_perm"] == pytest.approx(
        float(real_has.mean() - perm_has.mean(axis=1).mean()), abs=1e-12
    )
    # 3) 母体外会话 X 不进入置换分子；诊断计数与布尔矩阵逐种子一致
    for i, seed_rec in enumerate(res["perm_rate_per_seed"]):
        assert seed_rec["n_perm_event_sessions_after_population_filter"] == int(
            perm_has[i].sum()
        ), f"seed {seed_rec['seed']} 过滤后会话数必须等于 perm_has 行和"
    assert res["n_perm_event_sessions_after_population_filter_total"] == int(
        perm_has.sum()
    )
    x_in_pop = np.isin(sessions, ["X"])
    assert not perm_has[:, x_in_pop].any(), "母体外会话 X 不得进入置换分子"
    # 过滤确实做了实际工作：至少一个种子在过滤前捕获了 X（否则断言不成立需改构造）
    assert res["n_perm_event_sessions_before_population_filter_total"] > \
        res["n_perm_event_sessions_after_population_filter_total"], \
        "期望置换在过滤前捕获到母体外会话 X"


def _events_of(labeled: pd.DataFrame, thr: GapThresholds, phase: str) -> pd.DataFrame:
    ev = detect_gap_events(labeled, thr, phase_col="phase")
    if not len(ev):
        ev["event_phase"] = pd.Series(dtype=str)
    else:
        ev["event_phase"] = ev["phase"]
    return ev[ev["event_phase"] == phase]


def test_permutation_control_nocore_returns_evaluable_false() -> None:
    """E0-Full 健壮性（审查结论5）：无核心窗口会话时返回 evaluable=False，不产生 NaN。

    分池/月份子集可能遇到零合格会话；此时必须跳过而非对空数组求均值。
    """
    thr = _thr()
    non_core = _non_core_labeled("N", "2018-11-01 10:00")
    sessions = core_run_session_ids(non_core)
    assert len(sessions) == 0, "无 core 会话是前置条件"

    res = permutation_negative_control(
        non_core, thr, _events_of(non_core, thr, PHASE_CORE),
        perm_seeds=[42, 2024, 777], bootstrap_seed=SEED, n_boot=200,
    )
    assert res["evaluable"] is False
    assert res["reason"] == "no_core_sessions"
    assert res["bootstrap_n_sessions"] == 0
    assert res["real_core_session_rate"] == 0.0
    assert res["perm_rate_mean"] == 0.0
    assert res["diff_real_minus_perm"] == 0.0
    assert res["diff_bootstrap_ci95"] == [0.0, 0.0]
    assert len(res["_real_has"]) == 0
    assert res["_perm_has"].shape == (3, 0)
