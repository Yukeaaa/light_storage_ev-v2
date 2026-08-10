"""P1 正式代码测试（Phase 3 v1.0.2）：三态映射、穷尽 ratio 语义、quartile direction、
cluster bootstrap、once-only state machine、test loader 隔离。

全部用合成 office001 分钟数据；不读取任何真实 test outcome。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from patent_preexperiment.p1.bootstrap import cluster_bootstrap_rate_diff_ci
from patent_preexperiment.p1.features import (
    MIN_RECENT_SAMPLES,
    cycle_observables,
    e1_event_start_cycles,
)
from patent_preexperiment.p1.rates import (
    RateResult,
    exhaustive_ratio,
    p1_verdict,
    quartile_direction,
    state_rates,
)
from patent_preexperiment.p1.states import (
    assign_states,
    fit_quartile_edges,
    fit_train_q50,
)

S1, S2, S3 = "S1", "S2", "S3"


def _minutes_df(
    n_cycles: int = 10,
    start: str = "2019-06-01 08:00:00",
    amplitude_s1: float = 0.5,
    amplitude_s2: float = 3.0,
) -> pd.DataFrame:
    """构造 office001 分钟表：两个会话跨全部 cycle，S1 低波动、S2 高波动。"""
    t0 = pd.Timestamp(start, tz="UTC")
    rows: list[dict] = []
    for c in range(n_cycles):
        cycle_start = t0 + pd.Timedelta(minutes=5 * c)
        amp = amplitude_s1 if c % 2 == 0 else amplitude_s2
        for m in range(5):
            ts = cycle_start + pd.Timedelta(minutes=m)
            for sid in ("off_s1_0000", "off_s2_0000"):
                rows.append({
                    "session_id": sid,
                    "station_id": "PL-0",
                    "site": "office001",
                    "garage": "Parking_Lot_01",
                    "field_mode": "measured_pilot",
                    "match_status": "matched",
                    "timestamp_utc": ts,
                    "actual_power_kw": float(amp + np.sin(c + m) * 0.1),
                    "pilot_power_kw": 6.0,
                    "current_a": 5.0,
                    "pilot_a": 32.0,
                    "pilot_available": True,
                    "connected_elapsed_min": float(m),
                    "gap_flag": False,
                    "severe_gap_before": False,
                    "disconnect_time": t0 + pd.Timedelta(minutes=5 * n_cycles + 1),
                    "done_charging_time": t0 + pd.Timedelta(minutes=5 * n_cycles),
                })
    return pd.DataFrame(rows)


def _events_df(cycle_idxs: list[int], start: str = "2019-06-01 08:00:00") -> pd.DataFrame:
    t0 = pd.Timestamp(start, tz="UTC")
    rows = []
    for c in cycle_idxs:
        rows.append({
            "session_id": "off_0000",
            "site": "office001",
            "start_utc": t0 + pd.Timedelta(minutes=5 * c + 1),
            "end_utc": t0 + pd.Timedelta(minutes=5 * c + 4),
            "duration_min": 3,
        })
    return pd.DataFrame(rows)


def test_cycle_observables_produces_cycles():
    df = _minutes_df(n_cycles=12)
    obs = cycle_observables(df)
    assert len(obs) == 12
    assert "median_recent_actual_var" in obs.columns
    # 交替 S1/S2 波动 → 存在可分离的 recent_var 取值
    assert obs["median_recent_actual_var"].nunique() > 1
    # 前 2 个 cycle 因 shift(1)+rolling(min_periods=2) 无可评估历史 → NaN
    assert obs["median_recent_actual_var"].iloc[:2].isna().all()


def test_min_recent_samples_frozen():
    assert MIN_RECENT_SAMPLES == 2


def test_e1_event_start_cycles_floor_5min():
    ev = _events_df([0, 1])
    cycles = e1_event_start_cycles(ev)
    t0 = pd.Timestamp("2019-06-01 08:00:00", tz="UTC")
    assert cycles == {("office001", t0), ("office001", t0 + pd.Timedelta(minutes=5))}
    assert e1_event_start_cycles(_events_df([])) == set()


def test_train_q50_and_assign_states():
    df = _minutes_df(n_cycles=20)
    obs = cycle_observables(df)
    q50 = fit_train_q50(obs)
    assert isinstance(q50, float) and math.isfinite(q50)
    states = assign_states(obs, q50)
    assert set(states["state"].unique()) <= {S1, S2, S3}
    # S1/S2 均出现
    assert "S1" in set(states["state"]) and "S2" in set(states["state"])
    # S3 只允许在最开始的 2 个 cycle（rolling min_periods 未满足），之后不得出现
    s3_idx = states.index[states["state"] == S3]
    assert all(i <= 1 for i in s3_idx)


def test_assign_states_s3_for_nan():
    obs = pd.DataFrame({
        "site": ["office001"] * 3,
        "cycle": pd.to_datetime([
            "2019-06-01 08:00:00", "2019-06-01 08:05:00", "2019-06-01 08:10:00",
        ]),
        "median_recent_actual_var": [1.0, np.nan, 2.0],
    })
    states = assign_states(obs, 1.5)
    assert list(states["state"]) == [S1, S3, S2]


def test_fit_quartile_edges_duplicate_rule():
    obs = pd.DataFrame({
        "site": ["office001"] * 20,
        "cycle": pd.date_range("2019-06-01", periods=20, freq="5min"),
        "median_recent_actual_var": list(np.linspace(0.1, 2.0, 20)),
    })
    edges, prov = fit_quartile_edges(obs)
    assert not edges["insufficient_bin_resolution"]
    assert edges["effective_bins"] >= 2
    assert edges["edges"][0] == -np.inf and edges["edges"][-1] == np.inf
    assert prov["n_nonnull"] == 20


def test_fit_quartile_edges_insufficient_bins():
    obs = pd.DataFrame({
        "site": ["office001"] * 20,
        "cycle": pd.date_range("2019-06-01", periods=20, freq="5min"),
        "median_recent_actual_var": [0.5] * 20,
    })
    edges, prov = fit_quartile_edges(obs)
    assert edges["insufficient_bin_resolution"]
    assert edges["reason"] == "duplicate_edge_insufficient_bins"


def test_state_rates_s2_higher():
    cycles = pd.date_range("2019-06-01", periods=8, freq="5min")
    obs = pd.DataFrame({
        "site": ["office001"] * 8,
        "cycle": cycles,
        "state": [S1, S1, S1, S1, S2, S2, S2, S2],
    })
    e1_cycles = {("office001", cycles[4]), ("office001", cycles[5]), ("office001", cycles[6])}
    r = state_rates(obs, e1_cycles)
    assert r.n_s1 == 4 and r.n_s2 == 4
    assert r.n_e1_s1 == 0 and r.n_e1_s2 == 3
    assert r.rate_s1 == 0.0 and r.rate_s2 == pytest.approx(0.75)
    assert r.rate_diff == pytest.approx(0.75)


def test_exhaustive_ratio_zero_zero_na():
    r = RateResult(n_s1=10, n_s2=10, n_e1_s1=0, n_e1_s2=0, rate_s1=0.0, rate_s2=0.0, rate_diff=0.0)
    ratio = exhaustive_ratio(r)
    assert ratio.ratio is None
    assert ratio.ratio_kind == "na_zero_zero"
    assert not ratio.state_missing


def test_exhaustive_ratio_positive_infinity():
    r = RateResult(n_s1=10, n_s2=10, n_e1_s1=0, n_e1_s2=2, rate_s1=0.0, rate_s2=0.2, rate_diff=0.2)
    ratio = exhaustive_ratio(r)
    assert ratio.ratio_kind == "positive_infinity"
    assert ratio.ratio == float("inf")


def test_exhaustive_ratio_state_missing():
    r = RateResult(n_s1=0, n_s2=10, n_e1_s1=0, n_e1_s2=1, rate_s1=0.0, rate_s2=0.1, rate_diff=0.1)
    ratio = exhaustive_ratio(r)
    assert ratio.state_missing
    assert ratio.ratio_kind == "state_missing"


def test_exhaustive_ratio_finite():
    r = RateResult(n_s1=10, n_s2=10, n_e1_s1=2, n_e1_s2=6, rate_s1=0.2, rate_s2=0.6, rate_diff=0.4)
    ratio = exhaustive_ratio(r)
    assert ratio.ratio_kind == "finite"
    assert ratio.ratio == pytest.approx(3.0)


def test_p1_verdict_go():
    r = RateResult(n_s1=10, n_s2=10, n_e1_s1=2, n_e1_s2=6, rate_s1=0.2, rate_s2=0.6, rate_diff=0.4)
    ratio = exhaustive_ratio(r)
    ci = (0.1, 0.5)
    quartile = {
        "direction": "Q4>Q1",
        "rate_q1": 0.1,
        "rate_q4": 0.4,
        "insufficient_bin_resolution": False,
    }
    v = p1_verdict(r, ratio, ci, quartile, pretest_ok=True)
    assert v["verdict"] == "Go"


def test_p1_verdict_nogo_equality():
    r = RateResult(
        n_s1=10, n_s2=10, n_e1_s1=3, n_e1_s2=3,
        rate_s1=0.3, rate_s2=0.3, rate_diff=0.0,
    )
    ratio = exhaustive_ratio(r)
    v = p1_verdict(
        r, ratio, (0.0, 0.0),
        {"direction": "Q4>Q1", "insufficient_bin_resolution": False},
        True,
    )
    assert v["verdict"] == "No-Go"
    assert "equality" in v["reason"]


def test_p1_verdict_not_evaluable():
    r = RateResult(
        n_s1=0, n_s2=10, n_e1_s1=0, n_e1_s2=1,
        rate_s1=0.0, rate_s2=0.1, rate_diff=0.1,
    )
    ratio = exhaustive_ratio(r)
    v = p1_verdict(
        r, ratio, (0.0, 0.1),
        {"direction": "Q4>Q1", "insufficient_bin_resolution": False},
        True,
    )
    assert v["verdict"] == "NOT_EVALUABLE"
    assert v["patent_route"] == "Conditional"


def test_p1_verdict_na_zero_zero_nogo():
    r = RateResult(
        n_s1=10, n_s2=10, n_e1_s1=0, n_e1_s2=0,
        rate_s1=0.0, rate_s2=0.0, rate_diff=0.0,
    )
    ratio = exhaustive_ratio(r)
    v = p1_verdict(
        r, ratio, (0.0, 0.0),
        {"direction": "Q4>Q1", "insufficient_bin_resolution": False},
        True,
    )
    assert v["verdict"] == "No-Go"
    assert "NA" in v["reason"]


def test_quartile_direction_ok():
    cycles = pd.date_range("2019-06-01", periods=8, freq="5min")
    obs = pd.DataFrame({
        "site": ["office001"] * 8,
        "cycle": cycles,
        "median_recent_actual_var": [0.5, 0.6, 0.7, 0.8, 3.0, 3.1, 3.2, 3.3],
    })
    edges = {
        "edges": [-np.inf, 1.0, 2.0, 2.5, np.inf],
        "labels": ["Q1", "Q2", "Q3", "Q4"],
        "insufficient_bin_resolution": False,
    }
    e1_cycles = {("office001", cycles[6]), ("office001", cycles[7])}
    q = quartile_direction(obs, edges, e1_cycles)
    assert q["direction"] == "Q4>Q1"
    assert q["rate_q4"] > q["rate_q1"]
    assert not q["insufficient_bin_resolution"]


def test_quartile_direction_insufficient():
    obs = pd.DataFrame({
        "site": ["office001"] * 20,
        "cycle": pd.date_range("2019-06-01", periods=20, freq="5min"),
        "median_recent_actual_var": [0.5] * 20,
    })
    edges, _ = fit_quartile_edges(obs)
    q = quartile_direction(obs, edges, set())
    assert q["insufficient_bin_resolution"]
    assert q["direction"] == "insufficient_bin_resolution"


def test_cluster_bootstrap_ci_positive():
    rows: list[dict] = []
    e1: set[tuple[str, pd.Timestamp]] = set()
    for day in range(4):
        day_start = pd.Timestamp(f"2019-06-{day + 1:02d} 08:00:00")
        for k in range(6):
            cycle = day_start + pd.Timedelta(minutes=5 * k)
            st = S1 if k % 2 == 0 else S2
            rows.append({"site": "office001", "cycle": cycle, "state": st})
            if st == S2:
                e1.add(("office001", cycle))
    obs = pd.DataFrame(rows)
    ci = cluster_bootstrap_rate_diff_ci(obs, e1, seed=1, n_boot=200)
    assert ci[0] > 0.0


def test_cluster_bootstrap_ci_raises_without_days():
    obs = pd.DataFrame({
        "site": ["office001"] * 3,
        "cycle": pd.to_datetime([
            "2019-06-01 08:00:00", "2019-06-01 08:05:00", "2019-06-01 08:10:00",
        ]),
        "state": [S3, S3, S3],
    })
    with pytest.raises(RuntimeError, match="bootstrap"):
        cluster_bootstrap_rate_diff_ci(obs, set(), seed=1, n_boot=50)
