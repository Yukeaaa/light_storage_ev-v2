"""CORE-SEARCH Round 4 data-gate pure function tests."""

from __future__ import annotations

import pandas as pd

from patent_preexperiment.core_search.r4_decision import choose_r4_route
from patent_preexperiment.core_search.r4a0b_rwth import _data_level
from patent_preexperiment.core_search.r4c0_evse import _eventize_fault_rows, _fault_family, _gate


def test_r4c_fault_family_mapping():
    abnormal = {
        "hard_disabled": ["DISABLED CHARGER"],
        "pilot_violation": ["DISABLED PILOT VIOLATION", "PILOT VIOLATION"],
    }
    assert _fault_family("DISABLED CHARGER", abnormal) == "hard_disabled"
    assert _fault_family("PILOT VIOLATION", abnormal) == "pilot_violation"
    assert _fault_family("CHARGING", abnormal) is None


def test_r4c_eventize_same_station_family_gap():
    rows = pd.DataFrame({
        "station_id": ["A", "A", "A", "A", "B"],
        "fault_family": [
            "hard_disabled",
            "hard_disabled",
            "hard_disabled",
            "pilot_violation",
            "hard_disabled",
        ],
        "timestamp_utc": pd.to_datetime([
            "2020-01-01T00:00:00Z",
            "2020-01-01T00:02:00Z",
            "2020-01-01T00:05:00Z",
            "2020-01-01T00:06:00Z",
            "2020-01-01T00:07:00Z",
        ], utc=True),
    })
    out = _eventize_fault_rows(rows, max_gap_min=2)
    assert out["event_id"].tolist() == [1, 1, 2, 3, 4]


def test_r4c_gate_go_requires_spread_loss_and_concurrency():
    summary = pd.DataFrame({
        "station_id": [f"S{i}" for i in range(10)],
        "loss_fraction_l1_max": [0.2] * 10,
        "active_at_onset_l1": [True] * 10,
    })
    concurrency = pd.DataFrame({"disabled_station_count": [2] * 10})
    gate = _gate(summary, concurrency, {
        "stop": {
            "max_top2_event_share": 0.80,
            "min_l1_loss_fraction_p50": 0.05,
            "min_active_fault_event_share": 0.20,
        },
        "go": {
            "min_station_count": 5,
            "min_l1_loss_fraction_event_share_ge_15pct": 0.20,
            "min_concurrent_multi_station_minutes": 10,
        },
    })
    assert gate["verdict"] == "GO"


def test_r4_decision_priority():
    assert choose_r4_route({"verdict": "GO"}, {"data_level": "A"})["decision"] == "R4-C_MAIN"
    assert choose_r4_route({"verdict": "STOP"}, {"data_level": "A"})["decision"] == "R4-A_MAIN"
    assert (
        choose_r4_route({"verdict": "STOP"}, {"data_level": "B"})["decision"]
        == "R4-A_TRACKING_HOLD"
    )
    assert choose_r4_route({"verdict": "STOP"}, {"data_level": "DATA_PENDING"})[
        "decision"
    ] == "ROUND4_STOP_OR_DATA_PENDING"


def test_r4a0b_level_b_requires_aligned_schedule():
    fields = {
        "actual_bess_power": {"present": True},
        "dispatch_schedule": {"present": True},
        "soc": {"present": True},
        "temperature": {"present": False},
        "charge_discharge_limit": {"present": False},
        "alarms_status": {"present": False},
    }
    assert _data_level(fields, [{"raw_timestamp_aligned": True}], 4, 4) == "B"
    assert _data_level(fields, [{"raw_timestamp_aligned": False}], 4, 4) == "C"
