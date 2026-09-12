"""A-EV 原型单测：锁定归因门、统一符号约定、能力更新、承接、恢复与消融的关键行为。

运行：
    PYTHONPATH=src pytest tests/test_a_ev.py -q
"""

from __future__ import annotations

import json
import pathlib

import pytest

from patent_preexperiment.a_ev.algorithm import AEVPipeline
from patent_preexperiment.a_ev.attribution import Attriber
from patent_preexperiment.a_ev.baselines import ANoState, ANoWriteback, BaselineB0
from patent_preexperiment.a_ev.capability import (
    _stage_targets,
    apply_capability_update,
    init_capability,
)
from patent_preexperiment.a_ev.gap_carrier import feasible_headroom, station_gap
from patent_preexperiment.a_ev.metrics import evaluate
from patent_preexperiment.a_ev.runner import (  # noqa: F401
    LockError,
    config_hash,
    freeze,
    load_cfg,
    resolve_thresholds,
)
from patent_preexperiment.a_ev.scenario import (
    default_scenarios,
    default_site,
    run_episode,
)
from patent_preexperiment.a_ev.thresholds import build_thresholds
from patent_preexperiment.a_ev.types import (
    DIR_DOWN,
    DIR_UP,
    AttributionResult,
    LimitDir,
    Obs,
    ResourceSpec,
    Truth,
    Verdict,
    deviation_of,
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
    "experiment": {"phase": "synthetic_regression"},
}

SPECS = default_site(CFG)
THR = build_thresholds(CFG, SPECS)


def _obs(**kw: object) -> Obs:
    base: dict[str, object] = dict(
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
        local_limit_dir=LimitDir.UNKNOWN,
        mode_switch=False,
        protection_event=False,
        station_constraint_active=False,
        soc=0.5,
        temp_c=25.0,
    )
    base.update(kw)
    return Obs(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------- 统一符号约定


def test_signed_deviation_normal_underdelivery():
    d = deviation_of(50.0, 30.0)
    assert d.req_dir == DIR_UP
    assert d.signed == pytest.approx(20.0)
    assert d.gap_direction == DIR_UP
    assert d.deficit == pytest.approx(20.0)
    assert d.delivered_in_req_dir == pytest.approx(30.0)


def test_signed_deviation_over_execution_needs_down_compensation():
    """要求 +20、实际 +40：站级多注入 20 → 下向缺口；但要求方向已足额 → 不构成能力证据。"""
    d = deviation_of(20.0, 40.0)
    assert d.signed == pytest.approx(-20.0)
    assert d.gap_direction == DIR_DOWN
    assert d.gap_magnitude == pytest.approx(20.0)
    assert d.deficit == pytest.approx(0.0)
    assert d.evidences_limitation is False


def test_signed_deviation_opposite_execution_is_not_invisible():
    """要求 +20、实际 −20：旧口径 |20|−|−20| = 0（完全看不见）；新口径 |e| = 40。"""
    d = deviation_of(20.0, -20.0)
    assert d.gap_magnitude == pytest.approx(40.0)
    assert d.gap_direction == DIR_UP
    assert d.delivered_in_req_dir == pytest.approx(0.0)
    assert d.deficit == pytest.approx(20.0)


def test_zero_requirement_yields_no_capability_evidence():
    d = deviation_of(0.0, -30.0)   # 未要求出力却吸收了 30
    assert d.deficit == pytest.approx(0.0)
    assert d.gap_direction == DIR_UP  # 站级仍缺 30（缺口存在，但不作为能力证据）


# ---------------------------------------------------------------- 归因门


def test_comm_invalid_wins_over_all():
    a = Attriber(THR)
    r = a.attribute(_obs(comm_ok=False, local_limit_active=True, local_limit_dir=LimitDir.UP))
    assert r is not None and r.verdict is Verdict.COMM_INVALID
    assert r.allows_update is False and r.admissible is False


def test_response_window_yields_transient():
    a = Attriber(THR)
    r = a.attribute(_obs(t=10.0, cmd_sent_t=5.0))  # 5s < 12s 窗口
    assert r is not None and r.verdict is Verdict.TRANSIENT
    assert r.allows_update is False


def test_station_constraint_is_not_capability_evidence():
    a = Attriber(THR)
    r = a.attribute(_obs(station_constraint_active=True, local_limit_active=False))
    assert r is not None and r.verdict is Verdict.EXTERNAL_CONSTRAINT
    assert r.allows_update is False


def test_persistent_local_limit_needs_consecutive_confirmation():
    a = Attriber(THR)
    o = _obs(local_limit_active=True, local_limit_dir=LimitDir.UP)
    verdicts = [a.attribute(o).verdict for _ in range(CFG["attribution"]["persistence_n"])]
    assert verdicts[:-1] == [Verdict.UNCERTAIN] * (CFG["attribution"]["persistence_n"] - 1)
    assert verdicts[-1] is Verdict.VALID_CAPABILITY_LIMIT


def test_unknown_limit_dir_is_never_positive_evidence():
    """V0.2 修正：local_limit_dir=UNKNOWN 不得作为正向能力证据。"""
    a = Attriber(THR)
    o = _obs(local_limit_active=True, local_limit_dir=LimitDir.UNKNOWN, p_req=50.0, p_meas=30.0)
    for _ in range(CFG["attribution"]["persistence_n"] + 2):
        r = a.attribute(o)
        assert r is not None and r.verdict is Verdict.UNCERTAIN
        assert r.allows_update is False


def test_both_direction_limit_counts_as_positive_evidence():
    a = Attriber(THR)
    o = _obs(local_limit_active=True, local_limit_dir=LimitDir.BOTH)
    out = [a.attribute(o).verdict for _ in range(CFG["attribution"]["persistence_n"])]
    assert out[-1] is Verdict.VALID_CAPABILITY_LIMIT


def test_opposite_direction_limit_is_not_positive_evidence():
    a = Attriber(THR)
    o = _obs(local_limit_active=True, local_limit_dir=LimitDir.DOWN, p_req=50.0, p_meas=30.0)
    r = a.attribute(o)
    assert r is not None and r.verdict is Verdict.UNCERTAIN


def test_below_band_is_not_a_deviation():
    a = Attriber(THR)
    assert a.attribute(_obs(p_req=30.0, p_meas=29.5)) is None  # 欠交付 0.5 < 2.0


def test_over_execution_is_admissible_but_does_not_update():
    a = Attriber(THR)
    r = a.attribute(_obs(p_req=20.0, p_meas=40.0))
    assert r is not None and r.verdict is Verdict.VALID_EXECUTION_DEVIATION
    assert r.admissible is True and r.allows_update is False
    assert r.gap_direction == DIR_DOWN and r.gap_magnitude == pytest.approx(20.0)


# ---------------------------------------------------------------- 缺口与承接


def _res(verdict: Verdict, p_req: float, p_meas: float) -> AttributionResult:
    return AttributionResult.of(verdict, p_req, p_meas)


def test_gap_aggregation_same_direction_accumulates():
    g = station_gap(
        [
            ("R0", _res(Verdict.VALID_CAPABILITY_LIMIT, 50.0, 38.0)),
            ("R1", _res(Verdict.VALID_CAPABILITY_LIMIT, 28.0, 20.0)),
        ]
    )
    assert g.direction == DIR_UP and g.magnitude == pytest.approx(20.0)


def test_gap_aggregation_opposite_directions_net_off():
    g = station_gap(
        [
            ("R0", _res(Verdict.VALID_CAPABILITY_LIMIT, 50.0, 30.0)),
            ("R2", _res(Verdict.VALID_CAPABILITY_LIMIT, -25.0, -17.0)),
        ]
    )
    assert g.direction == DIR_UP and g.magnitude == pytest.approx(12.0)


def test_unidirectional_resource_cannot_serve_upward():
    spec_up = ResourceSpec("R2", 60.0, bidirectional=False, soc=0.5)
    spec_bi = ResourceSpec("R1", 100.0, bidirectional=True, soc=0.5)
    st_up = init_capability(spec_up, CFG)
    st_bi = init_capability(spec_bi, CFG)
    o_up = _obs(rid="R2", p_req=-25.0, p_meas=-25.0)
    assert feasible_headroom(spec_up, o_up, st_up, DIR_UP, CFG) == 0.0
    assert feasible_headroom(spec_bi, _obs(rid="R1", p_meas=20.0), st_bi, DIR_UP, CFG) > 0.0


def test_stage_targets_are_increasing():
    assert _stage_targets(100.0, CFG) == [50.0, 100.0]


# ---------------------------------------------------------------- 能力更新方向


def test_capability_update_uses_evidence_level_of_requested_direction():
    """要求 +20、实际 −20 → 上向边界收缩到 0（该方向实际交付为 0）。"""
    st = init_capability(ResourceSpec("R0", 100.0), CFG)
    r = _res(Verdict.VALID_CAPABILITY_LIMIT, 20.0, -20.0)
    ev = apply_capability_update(st, r, _obs(p_req=20.0, p_meas=-20.0), CFG)
    assert ev is not None and ev["side"] == "up" and st.up_bound == pytest.approx(0.0)


def test_capability_update_down_direction():
    """要求 −25、实际 −5 → 下向边界收缩到 5。"""
    st = init_capability(ResourceSpec("R2", 60.0, bidirectional=False), CFG)
    r = _res(Verdict.VALID_CAPABILITY_LIMIT, -25.0, -5.0)
    ev = apply_capability_update(st, r, _obs(rid="R2", p_req=-25.0, p_meas=-5.0), CFG)
    assert ev is not None and ev["side"] == "down" and st.down_bound == pytest.approx(5.0)


# ---------------------------------------------------------------- 端到端对照


def _run(name: str, policy_cls: type, cfg: dict | None = None) -> tuple:
    cfg = cfg or CFG
    specs = default_site(cfg)
    scen = {s.name: s for s in default_scenarios(cfg)}
    pol = policy_cls(specs, cfg)
    ep = run_episode(scen[name], specs, cfg, pol)
    return ep, pol, evaluate(ep, pol, cfg)


def test_comm_freeze_does_not_update_capability_under_A():
    """非能力原因：不更新能力边界（EMUR=0）；RESID 只在真实能力受限 episode 上统计。"""
    _, _, m = _run("S1_comm_freeze", AEVPipeline)
    assert m.emur_rate == pytest.approx(0.0)
    assert m.resid_full_mean_kw is None


def test_comm_freeze_triggers_wrong_update_without_gate():
    _, _, m = _run("S1_comm_freeze", BaselineB0)
    assert m.emur_rate == pytest.approx(1.0)


def test_local_limit_gate_confirms_and_reallocates():
    _, pol, m = _run("S3_local_limit_up", AEVPipeline)
    assert any(e.get("kind") == "shrink" for s in pol.history for e in s.cap_events)
    assert any(len(s.dispatches) > 0 for s in pol.history)
    assert m.resid_steady_mean_kw is not None and m.resid_steady_mean_kw < 5.0


def test_baseline_without_reallocation_leaves_residual():
    from patent_preexperiment.a_ev.baselines import BaselineB1

    _, _, m = _run("S3_local_limit_up", BaselineB1)
    assert m.resid_steady_mean_kw is not None and m.resid_steady_mean_kw > 15.0


def test_recovery_requires_probe_and_does_not_falsely_trigger():
    _, _, m_ok = _run("S7_recovery_ok", AEVPipeline)
    assert m_ok.recovery_delay_s is not None and m_ok.recovery_delay_s > 0
    _, _, m_fail = _run("S8_recovery_fail", AEVPipeline)
    assert m_fail.recovery_false_steps == 0


def test_cascade_writeback_excludes_carrier_in_transaction():
    _, pol, m = _run("S6_cascade", AEVPipeline)
    assert m.cascade_count >= 1
    assert any(s.writebacks for s in pol.history)


# ---------------------------------------------------------------- 消融


def test_ablation_no_state_is_memoryless():
    _, pol, m = _run("S3_local_limit_up", ANoState)
    assert all(s.bounds == {} for s in pol.history)     # 不上报边界 → EMUR 空真
    assert m.emur_rate is None or m.emur_numer == 0


def test_ablation_no_writeback_loses_cascade():
    _, pol_a, m_a = _run("S6_cascade", AEVPipeline)
    _, _, m_nw = _run("S6_cascade", ANoWriteback)
    assert m_a.cascade_count >= 1
    assert m_nw.cascade_count == 0
    # 不回写 ⇒ 不会排除失效承接资源 ⇒ 剩余缺口不低于完整 A
    assert (m_nw.resid_steady_mean_kw or 0.0) >= (m_a.resid_steady_mean_kw or 0.0)


def test_truth_labels_present_for_every_sample():
    ep, _, _ = _run("S1_comm_freeze", AEVPipeline)
    labels = {r.truth for r in ep.truth}
    assert Truth.COMM_FREEZE in labels


# ---------------------------------------------------------------- 场景集分离与阈值规则


def test_commissioning_scenarios_are_separated():
    from patent_preexperiment.a_ev.scenario import commissioning_scenarios

    ev = {s.name for s in default_scenarios(CFG)}
    cm = {s.name for s in commissioning_scenarios(CFG)}
    assert not (ev & cm)
    assert all(s.phase == "commissioning" for s in commissioning_scenarios(CFG))


def test_robustness_matrix_respects_preregistration():
    from patent_preexperiment.a_ev.scenario import robustness_scenarios

    cfg = dict(CFG)
    cfg["robustness"] = {
        "enabled": True,
        "directions": ["up", "down"],
        "magnitudes_pct": [0.1, 0.2],
        "resources": {"up": ["R0"], "down": ["R2"]},
        "repeats": 2,
        "seed": 5,
        "extra_coverage": ["ts_misalign"],
        "extra_coverage_target": "R0",
    }
    names = [s.name for s in robustness_scenarios(cfg)]
    assert len(names) == (1 * 2 * 2) + (1 * 2 * 2) + 1      # up + down + extra
    assert len(set(names)) == len(names)                    # 顺序随机但无重复


def test_threshold_rule_is_per_resource():
    cfg = dict(CFG)
    cfg["thresholds_provenance"] = {
        "data_dt_s": 1.0,
        "deviation_band": {
            "meter_resolution_kw": 0.1,
            "k_sigma": 3.0,
            "noise_sigma_kw": 0.25,
            "alpha": 0.02,
        },
        "response_window": {"p95_step_response_time_s": None, "margin_s": 3.0},
        "persistence": {"persistence_min_s": 5.0},
        "recovery_confirm": {"confirm_min_s": 4.0},
    }
    thr = build_thresholds(cfg, SPECS)
    assert thr.band("R0") == pytest.approx(2.0)      # α·100
    assert thr.band("R2") == pytest.approx(1.2)      # α·60 —— 异构资源各有各的门槛
    assert thr.persistence_n == 5
    assert thr.confirm_n == 4
    assert thr.window_s == pytest.approx(12.0)       # p95 未落定 → 回落标量


def test_response_delay_holds_output_before_first_order_response():
    """V0.2：response_delay_s 真实作用于 plant——暂态场景在纯延迟内输出保持原值。"""
    ep, _, _ = _run("S2_transient", AEVPipeline)
    t0 = CFG["scenario"]["t_event_start"]
    rows = {round(r.t, 3): r for r in ep.plant if r.rid == "R0"}
    base = CFG["schedule"]["base_setpoint_kw"]["R0"]
    assert rows[round(t0, 3)].p_meas_true == pytest.approx(base)
    # 越过延迟后应已开始一阶响应（偏离原值）
    later = round(t0 + CFG["plant"]["response_delay_s"] + 1.0, 3)
    assert rows[later].p_meas_true != pytest.approx(base)


def test_config_hash_is_stable_and_ignores_lock_fields():
    cfg_a = load_cfg("configs/a_ev_v0.yaml")
    cfg_b = load_cfg("configs/a_ev_v0.yaml")
    assert config_hash(cfg_a) == config_hash(cfg_b)
    cfg_b["lock"] = "whatever"
    cfg_b.setdefault("experiment", {})["config_hash"] = "x"
    assert config_hash(cfg_a) == config_hash(cfg_b)


# ---------------------------------------------------------------- 锁闭环（formal 唯一阈值来源）

CONFIG_PATH = pathlib.Path("configs/a_ev_v0.yaml")


def test_config_hash_ignores_governance_flags():
    """治理位（phase / 加锁标志 / 锁字段）不参与内容哈希：冻结后切 formal 不使锁失效。"""
    cfg = load_cfg(CONFIG_PATH)
    h0 = config_hash(cfg)
    exp = cfg.setdefault("experiment", {})
    exp["thresholds_locked"] = True
    exp["phase"] = "formal"
    exp["locked_at"] = "2026-09-12T00:00:00+00:00"
    exp["config_hash"] = "x"
    cfg["lock"] = {"anything": 1}
    assert config_hash(cfg) == h0
    cfg["scenario"]["t_event_end"] = 81.0     # 实质内容变化必须改变哈希
    assert config_hash(cfg) != h0


def test_freeze_writes_resolved_thresholds_from_calibration(tmp_path: pathlib.Path):
    """锁 = resolved thresholds（逐资源 band / 窗 / 持久 / 确认）+ 配置与标定数据哈希。"""
    cfg = load_cfg(CONFIG_PATH)
    lock_path = tmp_path / "lock.json"
    lock = freeze(cfg, lock_path)
    rt = lock["resolved_thresholds"]
    assert rt["band_by_rid"]["R2"] < rt["band_by_rid"]["R0"]   # per-resource 规则生效
    assert rt["persistence_n"] == 5 and rt["confirm_n"] == 4   # 规则推导（ceil(min_s/dt)）
    assert lock["calibration_data_hash"]
    assert "p95_step_response_time_s" in lock["calibration"]


def test_formal_uses_lock_resolved_thresholds(tmp_path: pathlib.Path):
    """冻结后只切治理位 → formal 接受，且算法实际使用的阈值来自锁而非配置标量。"""
    cfg = load_cfg(CONFIG_PATH)
    lock_path = tmp_path / "lock.json"
    lock = freeze(cfg, lock_path)
    cfg["experiment"]["phase"] = "formal"
    cfg["experiment"]["thresholds_locked"] = True
    specs = default_site(cfg)
    thr = resolve_thresholds(cfg, specs, lock_path)
    rt = lock["resolved_thresholds"]
    assert thr.band("R2") == pytest.approx(rt["band_by_rid"]["R2"])
    assert thr.band("R2") != pytest.approx(2.0)   # ≠ 配置标量回落 → 证明用的是锁值
    assert thr.window_s == pytest.approx(rt["response_window_s"])
    assert thr.persistence_n == rt["persistence_n"]
    assert thr.confirm_n == rt["confirm_n"]
    assert thr.provenance["source"] == "lock"


def test_formal_refuses_missing_stale_or_tampered_lock(tmp_path: pathlib.Path):
    """formal 四类硬失败：缺锁 / 哈希不匹配 / resolved 缺失 / 未加锁 —— 无标量回落。"""
    cfg = load_cfg(CONFIG_PATH)
    cfg["experiment"]["phase"] = "formal"
    cfg["experiment"]["thresholds_locked"] = True
    specs = default_site(cfg)
    lock_path = tmp_path / "lock.json"

    with pytest.raises(LockError):                 # ① 缺锁
        resolve_thresholds(cfg, specs, lock_path)

    freeze(cfg, lock_path)
    cfg["scenario"]["t_event_end"] = 81.0          # 冻结后改动配置内容
    with pytest.raises(LockError):                 # ② 哈希不匹配
        resolve_thresholds(cfg, specs, lock_path)
    cfg["scenario"]["t_event_end"] = 80.0

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    del lock["resolved_thresholds"]["confirm_n"]
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(LockError):                 # ③ resolved thresholds 缺失
        resolve_thresholds(cfg, specs, lock_path)

    cfg2 = load_cfg(CONFIG_PATH)
    cfg2["experiment"]["phase"] = "formal"         # ④ thresholds_locked=false
    with pytest.raises(LockError):
        resolve_thresholds(cfg2, specs, lock_path)


def test_formal_main_entry_refuses_unlocked_run(tmp_path: pathlib.Path):
    """入口级守卫：手工把 thresholds_locked 置 true 但没有（有效）锁 → 拒绝运行。"""
    import yaml

    from patent_preexperiment.a_ev import runner as runner_mod

    cfg = load_cfg(CONFIG_PATH)
    cfg["experiment"]["phase"] = "formal"
    cfg["experiment"]["thresholds_locked"] = True   # 无锁文件 → check_lock 必败
    cfg_path = tmp_path / "formal.yaml"
    cfg_path.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    out = str(tmp_path / "out")
    assert runner_mod.main(["--config", str(cfg_path), "--set", "commissioning",
                            "--out", out]) == 3
    assert runner_mod.main(["--config", str(cfg_path), "--set", "evaluation",
                            "--out", out]) == 3


# ---------------------------------------------------------------- S9：跨事务复用持久能力知识


def test_s9_persistent_state_survives_transaction_end():
    """权 7 事务级状态随缺口消失清空，但权 1【c】/【e】持久能力知识跨事务保持。"""
    _, pol, m = _run("S9_learned_carrier_reuse", AEVPipeline)
    # T1：归因确认收缩 R0；R1 承接缺口
    assert any(e.get("kind") == "shrink" and e.get("rid") == "R0"
               for s in pol.history for e in s.cap_events)
    assert any(d.carrier_rid == "R1"
               for s in pol.history if s.t < 80.0 for d in s.dispatches)
    # 事务中段（T1 已结束、T2 未开始）：修正与事务级排除清空
    mid = [s for s in pol.history if 90.0 <= s.t <= 100.0]
    assert mid and all(s.carriers == () and s.excluded == () for s in mid)
    # T2：R0 持久边界仍为收缩值（无恢复试探 → 不回升）
    t2 = [s for s in pol.history if s.t >= 115.0]
    assert t2 and all(s.bounds["R0"][0] < 100.0 - 1e-6 for s in t2)
    # A 不向 R0 下发超过其已知能力的修正 → 无二次不可执行命令
    assert not any(d.carrier_rid == "R0" for s in t2 for d in s.dispatches)
    assert m.bad_cmd_rate == pytest.approx(0.0)


def test_s9_no_state_reissues_unexecutable_command():
    """消融【c】：无持久能力知识 → T2 仍按额定能力向 R0 派发 → 二次不可执行命令。"""
    _, pol, m = _run("S9_learned_carrier_reuse", ANoState)
    t2 = [s for s in pol.history if s.t >= 115.0]
    assert any(d.carrier_rid == "R0" for s in t2 for d in s.dispatches)
    assert m.bad_cmd_rate > 0.0
