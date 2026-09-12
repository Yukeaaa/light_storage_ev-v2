"""A-EV HIL 数据合同与准入门单测：缺层 ⇒ 对应机制标记不可验证，绝不事后猜。"""

from __future__ import annotations

import copy

import pytest

from patent_preexperiment.a_ev.hil_contract import (
    ADMITTED,
    CONDITIONAL,
    CONTRACT_FIELDS,
    REJECTED,
    admit,
    load_contract,
)


def _load() -> dict:
    return load_contract("configs/a_ev_hil_contract.yaml")


def test_contract_covers_review_field_list():
    """评审 2026-09-12 强制记录清单必须全部在合同内。"""
    keys = {f.key for f in CONTRACT_FIELDS}
    assert {
        "command_id", "requested_setpoint", "translated_setpoint", "accepted_setpoint",
        "write_ack", "control_owner", "override_source", "override_reason",
        "applied_timestamp", "p_meas", "pcc",
    } <= keys


def test_committed_contract_is_conditional_with_derived_accepted():
    """现实口径：accepted 走推导 ⇒ CONDITIONAL，依赖机制标 DERIVED 而非失明。"""
    rep = admit(_load())
    assert rep.decision == CONDITIONAL
    assert any("accepted_setpoint" in d for d in rep.derived_fields)
    derived_mechs = [m for m in rep.mechanisms if m.verifiable and m.derived]
    assert any("M1 上报限值区分" == m.mechanism for m in derived_mechs)
    # 全部机制要么可验证，要么显式列名——不允许静默缺口
    assert all(m.verifiable or m.reason for m in rep.mechanisms)


def test_full_contract_admits_all_mechanisms():
    cfg = _load()
    cfg["hil_contract"]["fields"]["accepted_setpoint"] = {"available": True}
    rep = admit(cfg)
    assert rep.decision == ADMITTED
    assert rep.not_verifiable() == []
    assert all(not m.derived for m in rep.mechanisms)


def test_missing_accepted_without_derivation_marks_reported_layer_not_verifiable():
    """accepted 缺层且无推导 ⇒ 上报限值区分 / Reported 包络 / 写回 显式不可验证。"""
    cfg = _load()
    cfg["hil_contract"]["fields"]["accepted_setpoint"] = {"available": False}
    rep = admit(cfg)
    assert rep.decision == CONDITIONAL
    dead = {m.mechanism for m in rep.not_verifiable()}
    assert {"M1 上报限值区分", "Reported 包络", "commissioning 响应窗"} <= dead
    # 缺层必须点名到字段，不允许"事后猜"
    assert "accepted_setpoint" in rep.missing_fields


def test_missing_pcc_marks_station_residual_channel_not_verifiable():
    cfg = _load()
    cfg["hil_contract"]["fields"]["pcc"] = {"available": False}
    rep = admit(cfg)
    assert rep.decision == CONDITIONAL
    assert "模块6 PCC 残差通道" in {m.mechanism for m in rep.not_verifiable()}


def test_core_field_missing_rejects():
    """没有 requested 或 p_meas ⇒ 无执行偏差可言 ⇒ REJECTED。"""
    cfg = _load()
    cfg["hil_contract"]["fields"]["p_meas"] = {"available": False}
    rep = admit(cfg)
    assert rep.decision == REJECTED


def test_clock_over_budget_rejects():
    """秒级时钟偏差即混淆暂态/限值/能力受限 ⇒ 拒绝进入 commissioning。"""
    cfg = _load()
    cfg["hil_contract"]["clock"]["actual_skew_s"] = 3.0
    rep = admit(cfg)
    assert rep.decision == REJECTED
    assert any("时序判据" in m.mechanism for m in rep.not_verifiable())


def test_multi_owner_control_authority_rejects():
    """隐形上游写点（多主控制权）⇒ 错误归因不可控 ⇒ REJECTED。"""
    cfg = _load()
    cfg["hil_contract"]["control_authority"] = {"single_owner": False,
                                                "owners": ["ems_a", "vendor_cloud"]}
    rep = admit(cfg)
    assert rep.decision == REJECTED
    assert any("控制权仲裁" in m.mechanism for m in rep.not_verifiable())


def test_admit_is_pure_over_input():
    """admit 不得修改输入（可重复调用，结果一致）。"""
    cfg = _load()
    snapshot = copy.deepcopy(cfg)
    r1 = admit(cfg)
    r2 = admit(cfg)
    assert cfg == snapshot
    assert r1.decision == r2.decision == CONDITIONAL


@pytest.mark.parametrize("field_key", [f.key for f in CONTRACT_FIELDS])
def test_every_contract_field_is_registered(field_key: str):
    cfg = _load()
    assert field_key in cfg["hil_contract"]["fields"], f"合同配置缺字段 {field_key}"
