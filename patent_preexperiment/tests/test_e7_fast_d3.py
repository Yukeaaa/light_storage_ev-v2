"""E7-FAST D3 园区系统验证单测：5 核心量 / 4 arm / 6 指标 / Go 门。

合成已知 shortfall/bess/pcc 的事件验证逻辑正确性。
"""

from __future__ import annotations

import pandas as pd
import pytest

from patent_preexperiment.e7_fast.config import load_e7_fast_config
from patent_preexperiment.e7_fast.event_replay import replay_arm
from patent_preexperiment.e7_fast.system_arms import SYSTEM_ARMS
from patent_preexperiment.e7_fast.system_metrics import (
    evaluate_system_gate,
)
from patent_preexperiment.phase3_p2.schema import M2

_CFG = load_e7_fast_config()


def _mk_events(rows: list[dict]) -> pd.DataFrame:
    base = {
        "event_id": [], "session_id": [], "station_id": [], "site": [],
        "timestamp": [], "month": [], "split": [], "info_mode_before": [],
        "direction": [],
        "actual_before_kw": [], "pilot_after_kw": [], "delta_pilot_kw": [],
        "actual_5min_kw": [], "history_q95_before_kw": [],
    }
    for i, r in enumerate(rows):
        for k in base:
            default = (f"v{i}" if k in ("event_id", "session_id", "station_id",
                       "site", "timestamp", "month", "split", "info_mode_before",
                       "direction") else 0)
            base[k].append(r.get(k, default if k not in ("info_mode_before", "direction")
                                 else (M2 if k == "info_mode_before" else "up")))
    return pd.DataFrame(base)


def test_core_quantities_s0_unrestricted():
    # S0: accepted = park_requested = delta_pilot
    # actual_before=4, pilot_after=7.2, q95=5.6, delta_pilot=3, actual_5min=5
    # observed_support = max(5-4,0)=1; accepted=3; realized=min(3,1)=1
    # shortfall = max(3-1,0)=2; planned_bess = 3-3=0
    # bess_avail = 0.5*4=2; unplanned_bess = min(2,2)=2; pcc_residual = 2-2=0
    evs = _mk_events([{
        "actual_before_kw": 4.0, "pilot_after_kw": 7.2, "delta_pilot_kw": 3.0,
        "actual_5min_kw": 5.0, "history_q95_before_kw": 5.6,
    }])
    r = replay_arm("S0_unrestricted", evs)
    assert r["ev_accepted_delta"].iloc[0] == pytest.approx(3.0)
    assert r["ev_observed_support"].iloc[0] == pytest.approx(1.0)
    assert r["ev_realized_delta"].iloc[0] == pytest.approx(1.0)
    assert r["unexpected_ev_shortfall"].iloc[0] == pytest.approx(2.0)
    assert r["planned_bess_delta"].iloc[0] == pytest.approx(0.0)
    assert r["unplanned_bess_correction"].iloc[0] == pytest.approx(2.0)
    assert r["pcc_residual"].iloc[0] == pytest.approx(0.0)


def test_core_quantities_s1_conservative():
    # S1: accepted=0 → realized=0, shortfall=0, planned_bess=3, unplanned=0, pcc=0
    evs = _mk_events([{
        "actual_before_kw": 4.0, "pilot_after_kw": 7.2, "delta_pilot_kw": 3.0,
        "actual_5min_kw": 5.0, "history_q95_before_kw": 5.6,
    }])
    r = replay_arm("S1_conservative", evs)
    assert r["ev_accepted_delta"].iloc[0] == pytest.approx(0.0)
    assert r["ev_realized_delta"].iloc[0] == pytest.approx(0.0)
    assert r["unexpected_ev_shortfall"].iloc[0] == pytest.approx(0.0)
    assert r["planned_bess_delta"].iloc[0] == pytest.approx(3.0)
    assert r["unplanned_bess_correction"].iloc[0] == pytest.approx(0.0)


def test_core_quantities_s2_vs_s3_shortfall():
    # pilot_after=10 远大于 q95=5.6 → S3=min(10,5.6)-4=1.6 == S2=5.6-4=1.6 → 同 shortfall
    evs = _mk_events([{
        "actual_before_kw": 4.0, "pilot_after_kw": 10.0, "delta_pilot_kw": 3.0,
        "actual_5min_kw": 5.0, "history_q95_before_kw": 5.6,
    }])
    r2 = replay_arm("S2_rolling_q95", evs)
    r3 = replay_arm("S3_our_scheme", evs)
    assert r2["ev_accepted_delta"].iloc[0] == pytest.approx(1.6)
    assert r3["ev_accepted_delta"].iloc[0] == pytest.approx(1.6)
    assert r2["unexpected_ev_shortfall"].iloc[0] == r3["unexpected_ev_shortfall"].iloc[0]


def test_core_quantities_s3_better_than_s2():
    # pilot_after=4.5 < q95=9 → S3=min(4.5,9)-4=0.5; S2=9-4=5
    # observed_support = max(4.3-4,0)=0.3
    # S2 shortfall = max(5-0.3,0)=4.7; S3 shortfall = max(0.5-0.3,0)=0.2 → S3 better
    evs = _mk_events([{
        "actual_before_kw": 4.0, "pilot_after_kw": 4.5, "delta_pilot_kw": 3.0,
        "actual_5min_kw": 4.3, "history_q95_before_kw": 9.0,
    }])
    r2 = replay_arm("S2_rolling_q95", evs)
    r3 = replay_arm("S3_our_scheme", evs)
    assert r3["unexpected_ev_shortfall"].iloc[0] < r2["unexpected_ev_shortfall"].iloc[0]
    assert r3["unplanned_bess_correction"].iloc[0] <= r2["unplanned_bess_correction"].iloc[0]


def test_planned_bess_not_counted_as_unplanned():
    # planned_bess = park_requested - accepted；unplanned 只算 accepted - support
    # S1: accepted=0, planned=3, unplanned=0（即使 park_requested=3）
    evs = _mk_events([{
        "actual_before_kw": 4.0, "pilot_after_kw": 7.2, "delta_pilot_kw": 3.0,
        "actual_5min_kw": 4.0, "history_q95_before_kw": 5.6,  # support=0
    }])
    r = replay_arm("S1_conservative", evs)
    assert r["planned_bess_delta"].iloc[0] == pytest.approx(3.0)
    assert r["unplanned_bess_correction"].iloc[0] == pytest.approx(0.0)
    # total_bess = planned + unplanned = 3（但 unplanned=0 是关键）


def test_pcc_residual_when_bess_insufficient():
    # bess_avail=0.5*4=2; shortfall=3 > 2 → pcc_residual=1
    evs = _mk_events([{
        "actual_before_kw": 4.0, "pilot_after_kw": 10.0, "delta_pilot_kw": 5.0,
        "actual_5min_kw": 4.0, "history_q95_before_kw": 9.0,  # S2 accepted=5, support=0
    }])
    r = replay_arm("S2_rolling_q95", evs)
    assert r["unexpected_ev_shortfall"].iloc[0] == pytest.approx(5.0)
    assert r["bess_fast_available_power"].iloc[0] == pytest.approx(2.0)
    assert r["unplanned_bess_correction"].iloc[0] == pytest.approx(2.0)
    assert r["pcc_residual"].iloc[0] == pytest.approx(3.0)


def test_system_gate_go():
    # 构造 S3 严格优于 S2：pilot<q95，S3 少 shortfall，S3 flex>S1
    rows = []
    for i in range(60):
        rows.append({
            "event_id": f"e{i}", "session_id": f"s{i}", "station_id": f"st{i%5}",
            "site": "caltech", "month": f"2020-{(i%3)+6:02d}", "split": "train",
            "actual_before_kw": 4.0, "pilot_after_kw": 4.5, "delta_pilot_kw": 3.0,
            "actual_5min_kw": 4.3, "history_q95_before_kw": 9.0,
        })
    evs = _mk_events(rows)
    from patent_preexperiment.e7_fast.event_replay import replay_all_arms
    replay = replay_all_arms(evs)
    _per, v = evaluate_system_gate(replay, _CFG)
    assert v.level == "GO", v.reason
    assert v.unexpected_shortfall_reduction_pct > 10.0
    assert v.unplanned_bess_reduction_pct > 10.0
    assert v.pcc_residual_not_worsened
    assert v.s3_flex_significantly_higher_than_s1


def test_system_gate_fail_when_s3_equals_s2():
    # pilot_after 远大于 q95 → S3==S2 → 无改善 → FAIL
    rows = []
    for i in range(60):
        rows.append({
            "event_id": f"e{i}", "session_id": f"s{i}", "station_id": f"st{i%5}",
            "site": "caltech", "month": f"2020-{(i%3)+6:02d}", "split": "train",
            "actual_before_kw": 4.0, "pilot_after_kw": 10.0, "delta_pilot_kw": 3.0,
            "actual_5min_kw": 5.0, "history_q95_before_kw": 5.6,
        })
    evs = _mk_events(rows)
    from patent_preexperiment.e7_fast.event_replay import replay_all_arms
    replay = replay_all_arms(evs)
    _per, v = evaluate_system_gate(replay, _CFG)
    assert v.level == "FAIL", v.reason
    assert v.unexpected_shortfall_reduction_pct == pytest.approx(0.0, abs=1e-6)


def test_all_four_arms_present():
    evs = _mk_events([{
        "actual_before_kw": 4.0, "pilot_after_kw": 4.5, "delta_pilot_kw": 3.0,
        "actual_5min_kw": 4.3, "history_q95_before_kw": 9.0,
    }])
    from patent_preexperiment.e7_fast.event_replay import replay_all_arms
    replay = replay_all_arms(evs)
    assert set(replay["arm"].unique()) == set(SYSTEM_ARMS)
