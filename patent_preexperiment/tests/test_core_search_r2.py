"""CORE-SEARCH R2 单元测试：pilot 轨迹重建 / response_fraction / R2-P0-B0 三区门。

用合成事件验证逻辑正确性（不依赖外部数据）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.r2_config import R2P0B0Config, R2P0B0Gate
from patent_preexperiment.core_search.r2_response import (
    attach_pilot_trace,
    compute_down_response_fraction,
    evaluate_r2_p0b0_gate,
    max_pilot_deviation,
)


def _events(
    n: int,
    *,
    pilot_after: list[float] | None = None,
    actual_before: list[float] | None = None,
    actual_1m: list[float] | None = None,
    actual_5m: list[float] | None = None,
) -> pd.DataFrame:
    pa = pilot_after or [3.0] * n
    ab = actual_before or [6.0] * n
    a1 = actual_1m or [4.0] * n
    a5 = actual_5m or [4.0] * n
    return pd.DataFrame({
        "event_id": [f"e{i}" for i in range(n)],
        "session_id": [f"S{i}" for i in range(n)],
        "station_id": [f"ST{i % 2}" for i in range(n)],
        "timestamp": pd.date_range("2020-06-01", periods=n, freq="1min", tz="UTC"),
        "pilot_after_a": pa,
        "pilot_after_kw": pa,
        "actual_before_kw": ab,
        "actual_1min_kw": a1,
        "actual_3min_kw": a1,
        "actual_5min_kw": a5,
        "step_magnitude_bin": ["small"] * n,
    })


def _lookup(events: pd.DataFrame, pilot_series: list[list[float]]) -> pd.DataFrame:
    rows = []
    for _, e in events.iterrows():
        for k in range(1, 6):
            rows.append({
                "session_id": e["session_id"],
                "timestamp_utc": e["timestamp"] + pd.Timedelta(minutes=k),
                "pilot_a": pilot_series[int(e["event_id"][1:])][k - 1],
            })
    return pd.DataFrame(rows)


def test_attach_pilot_trace_reconstructs_pilot():
    ev = _events(2)
    # pilot at t+1..t+5: event0 stable at 3.0; event1 rises
    lookup = _lookup(ev, [[3.0, 3.0, 3.0, 3.0, 3.0], [3.0, 3.5, 4.0, 5.0, 6.0]])
    out = attach_pilot_trace(ev, lookup, horizon_min=5)
    assert out["pilot_1"].iloc[0] == 3.0
    assert out["pilot_5"].iloc[1] == 6.0


def test_max_pilot_deviation():
    ev = _events(2)
    lookup = _lookup(ev, [[3.0, 3.0, 3.0, 3.0, 3.0], [3.0, 3.5, 4.0, 5.0, 6.0]])
    out = attach_pilot_trace(ev, lookup, horizon_min=5)
    dev = max_pilot_deviation(out, 5)
    assert dev.iloc[0] == 0.0
    assert dev.iloc[1] == 3.0  # 6.0 - 3.0


def test_compute_down_response_fraction():
    ev = _events(1, pilot_after=[3.0], actual_before=[6.0], actual_1m=[4.0], actual_5m=[4.5])
    out = compute_down_response_fraction(ev, (1, 5), (0.0, 2.0))
    # r_1m = (6-4)/(6-3) = 2/3; r_5m = (6-4.5)/3 = 0.5
    assert np.isclose(out["r_1m"].iloc[0], 2 / 3)
    assert np.isclose(out["r_5m"].iloc[0], 0.5)


def _cfg() -> R2P0B0Config:
    return R2P0B0Config(
        primary_max_dev_a=1.0,
        sensitivity_max_dev_a=2.0,
        horizon_min=5,
        lag_min=(1, 3, 5),
        clip=(0.0, 2.0),
        gate=R2P0B0Gate(
            under_delivery_threshold=0.8,
            closed_under80_max=0.10,
            closed_p10_min=0.90,
            cond_under80_low=0.10,
            cond_under80_high=0.20,
            cond_p10_low=0.80,
            cond_p10_high=0.90,
            open_under80_min=0.20,
            open_p10_max=0.80,
            sensitivity_no_reversal=True,
        ),
        results_root="results/raw/core_search/r2_p0b0",
        report_path="reports/core_search/CORE_SEARCH_R2_P0B0.md",
    )


def _stable_df(r1m_values: list[float], n_sens: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    primary = pd.DataFrame({"r_1m": r1m_values})
    sensitivity = pd.DataFrame({"r_1m": [1.0] * n_sens})
    return primary, sensitivity


def test_gate_closed_when_no_under_delivery():
    primary, sensitivity = _stable_df([1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9])
    v = evaluate_r2_p0b0_gate(primary, sensitivity, _cfg())
    assert v.verdict == "CLOSED"
    assert v.primary_under80 == 0.0
    assert v.primary_p10 >= 0.90


def test_gate_open_when_much_under_delivery():
    primary, sensitivity = _stable_df([0.5, 0.5, 0.6, 0.6, 0.9, 1.0, 1.0, 1.1, 1.1, 1.2])
    v = evaluate_r2_p0b0_gate(primary, sensitivity, _cfg())
    assert v.verdict == "OPEN"


def test_gate_conditional_in_gray_zone():
    # under80 ≤ 0.10 且 p10 ∈ [0.80, 0.90) → 灰区（CONDITIONAL）
    primary, sensitivity = _stable_df(
        [0.82, 0.85, 0.90, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.1]
    )
    v = evaluate_r2_p0b0_gate(primary, sensitivity, _cfg())
    assert v.verdict == "CONDITIONAL"
