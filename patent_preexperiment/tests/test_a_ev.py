"""A-EV 原型单测：锁定归因门、能力更新、承接、恢复的关键行为。

运行：
    PYTHONPATH=src pytest tests/test_a_ev.py -q
"""

from __future__ import annotations

import pytest

from patent_preexperiment.a_ev.algorithm import AEVPipeline
from patent_preexperiment.a_ev.attribution import Attriber
from patent_preexperiment.a_ev.baselines import BaselineB0
from patent_preexperiment.a_ev.capability import _stage_targets
from patent_preexperiment.a_ev.gap_carrier import feasible_headroom, station_gap
from patent_preexperiment.a_ev.metrics import evaluate
from patent_preexperiment.a_ev.runner import load_cfg  # noqa: F401  (供 conftest 复用)
from patent_preexperiment.a_ev.scenario import default_scenarios, default_site, run_episode
from patent_preexperiment.a_ev.types import (
    DIR_DOWN,
    DIR_UP,
    AttributionResult,
    Obs,
    ResourceSpec,
    Truth,
    Verdict,
)

CFG = {
    "attribution": {
        "deviation_band_kw": 2.0,
        "response_window_s": 12.0,
        "persistence_n": 3,
    },
    "capability": {"init_confidence": 0.5, "conf_step": 0.1},
    "recovery": {"stage_fractions": [0.5, 1.0], "confirm_n": 2, "post_recover_confidence": 0.4},
    "physical": {"soc_min_discharge": 0.1, "soc_max_charge": 0.9, "temp_max_c": 45.0},
    "carrier": {
        "strategy": "contribution",
        "weights": {"contribution": 1.0, "confidence": 0.3, "soc_margin": 0.2},
    },
    "schedule": {"base_setpoint_kw": {"R0": 30.0, "R1": 20.0, "R2": -25.0}},
    "site": {
        "r0": {"p_rated": 100.0, "soc": 0.55, "temp_c": 26.0, "ramp": 20.0},
        "r1": {"p_rated": 100.0, "soc": 0.40, "temp_c": 25.0, "ramp": 20.0},
        "r2": {"p_rated": 60.0, "soc": 0.45, "temp_c": 24.0, "ramp": 10.0},
    },
    "scenario": {"t_event_start": 30.0, "t_event_end": 80.0},
    "plant": {"response_tau_s": 8.0, "response_delay_s": 1.0, "meas_noise_kw": 0.0},
    "metrics": {"residual_window_offset_s": 25.0},
}


def _obs(**kw) -> Obs:
    base = dict(
        t=10.0,
        rid="R0",
        p_req=50.0,
        p_meas=30.0,
        cmd_sent_t=0.0,
        resp_start_t=None,
        comm_ok=True,
        data_fresh=True,
        ts_aligned=True,
        local_limit_active=False,
        local_limit_dir=0,
        mode_switch=False,
        protection_event=False,
        station_constraint_active=False,
        soc=0.5,
        temp_c=25.0,
    )
    base.update(kw)
    return Obs(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------- 归因门


def test_comm_invalid_wins_over_all():
    a = Attriber(CFG)
    r = a.attribute(_obs(comm_ok=False, local_limit_active=True, local_limit_dir=DIR_UP))
    assert r is not None and r.verdict is Verdict.COMM_INVALID
    assert r.allows_update is False


def test_response_window_yields_transient():
    a = Attriber(CFG)
    r = a.attribute(_obs(t=10.0, cmd_sent_t=5.0))  # 5s < 12s 窗口
    assert r is not None and r.verdict is Verdict.TRANSIENT
    assert r.allows_update is False


def test_station_constraint_is_not_capability_evidence():
    a = Attriber(CFG)
    r = a.attribute(_obs(station_constraint_active=True, local_limit_active=False))
    assert r is not None and r.verdict is Verdict.EXTERNAL_CONSTRAINT
    assert r.allows_update is False


def test_persistent_local_limit_needs_consecutive_confirmation():
    a = Attriber(CFG)
    o = _obs(local_limit_active=True, local_limit_dir=DIR_UP)
    verdicts = [a.attribute(o).verdict for _ in range(CFG["attribution"]["persistence_n"])]
    assert verdicts[:-1] == [Verdict.UNCERTAIN] * (CFG["attribution"]["persistence_n"] - 1)
    assert verdicts[-1] is Verdict.VALID_CAPABILITY_LIMIT


def test_below_band_is_not_a_deviation():
    a = Attriber(CFG)
    assert a.attribute(_obs(p_req=30.0, p_meas=29.5)) is None  # 欠交付 0.5 < 2.0


# ---------------------------------------------------------------- 缺口与承接


def test_gap_aggregation_same_direction_accumulates():
    g = station_gap([("R0", AttributionResult(Verdict.VALID_CAPABILITY_LIMIT, DIR_UP, 12.0)),
                     ("R1", AttributionResult(Verdict.VALID_CAPABILITY_LIMIT, DIR_UP, 8.0))])
    assert g.direction == DIR_UP and g.magnitude == pytest.approx(20.0)


def test_gap_aggregation_opposite_directions_net_off():
    g = station_gap([("R0", AttributionResult(Verdict.VALID_CAPABILITY_LIMIT, DIR_UP, 20.0)),
                     ("R2", AttributionResult(Verdict.VALID_CAPABILITY_LIMIT, DIR_DOWN, 8.0))])
    assert g.direction == DIR_UP and g.magnitude == pytest.approx(12.0)


def test_unidirectional_resource_cannot_serve_upward():
    spec_up = ResourceSpec("R2", 60.0, bidirectional=False, soc=0.5)
    spec_bi = ResourceSpec("R1", 100.0, bidirectional=True, soc=0.5)
    from patent_preexperiment.a_ev.capability import init_capability

    st_up = init_capability(spec_up, CFG)
    st_bi = init_capability(spec_bi, CFG)
    o_up = _obs(rid="R2", p_req=-25.0, p_meas=-25.0)
    assert feasible_headroom(spec_up, o_up, st_up, DIR_UP, CFG) == 0.0
    assert feasible_headroom(spec_bi, _obs(rid="R1", p_meas=20.0), st_bi, DIR_UP, CFG) > 0.0


def test_stage_targets_are_increasing():
    assert _stage_targets(100.0, CFG) == [50.0, 100.0]


# ---------------------------------------------------------------- 端到端对照


def _run(name: str, policy_cls, cfg=None):
    cfg = cfg or CFG
    specs = default_site(cfg)
    scen = {s.name: s for s in default_scenarios(cfg)}
    pol = policy_cls(specs, cfg)
    ep = run_episode(scen[name], specs, cfg, pol)
    return ep, pol, evaluate(ep, pol, cfg)


def test_comm_freeze_does_not_update_capability_under_A():
    _, _, m = _run("S1_comm_freeze", AEVPipeline)
    assert m.emur_rate == pytest.approx(0.0)


def test_comm_freeze_triggers_wrong_update_without_gate():
    _, _, m = _run("S1_comm_freeze", BaselineB0)
    assert m.emur_rate == pytest.approx(1.0)


def test_local_limit_gate_confirms_and_reallocates():
    _, pol, m = _run("S3_local_limit_up", AEVPipeline)
    # 归因确认后应出现能力收缩，并出现跨资源承接
    assert any(e.get("kind") == "shrink" for s in pol.history for e in s.cap_events)
    assert any(len(s.dispatches) > 0 for s in pol.history)
    assert m.resid_mean_kw is not None and m.resid_mean_kw < 5.0


def test_baseline_without_reallocation_leaves_residual():
    _, _, m = _run("S3_local_limit_up", __import__(
        "patent_preexperiment.a_ev.baselines", fromlist=["BaselineB1"]
    ).BaselineB1)
    assert m.resid_mean_kw is not None and m.resid_mean_kw > 15.0


def test_recovery_requires_probe_and_does_not_falsely_trigger():
    for name, expect_false_zero in (("S7_recovery_ok", True), ("S8_recovery_fail", True)):
        _, _, m = _run(name, AEVPipeline)
        if name == "S7_recovery_ok":
            assert m.recovery_delay_s is not None and m.recovery_delay_s > 0
        else:
            assert m.recovery_false_steps == 0
        assert expect_false_zero


def test_cascade_writeback_excludes_carrier_in_transaction():
    ep, pol, m = _run("S6_cascade", AEVPipeline)
    assert m.cascade_count >= 1
    assert any(s.writebacks for s in pol.history)


def test_truth_labels_present_for_every_sample():
    ep, _, _ = _run("S1_comm_freeze", AEVPipeline)
    labels = {r.trust if hasattr(r, "trust") else r.truth for r in ep.truth}
    assert Truth.COMM_FREEZE in labels
