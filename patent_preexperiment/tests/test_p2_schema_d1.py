"""P2 schema 加载 + D1 precedence 穷尽查表单测（v1.0.2 §P0-1/P0-3）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from patent_preexperiment.phase3_p2.d1 import (
    assert_exhaustive,
    build_info_mode_table,
    eval_condition,
    lookup_mode,
)
from patent_preexperiment.phase3_p2.schema import M1, M2, M3, M4, load_schema

PP = Path(__file__).resolve().parents[1]
SCFG = load_schema(PP / "configs" / "phase3_p2_action_schema.yaml")


def test_frozen_identity() -> None:
    assert SCFG.experiment_id == "P2_v1_0_2"
    assert SCFG.protocol_version == "phase3_p2_preregistration_v1.0.2"
    assert SCFG.gate2_verdict == "NARROW_CONDITIONAL_GO"
    assert SCFG.scope == "mechanism_realizability_only"


def test_frozen_numeric_thresholds() -> None:
    assert SCFG.min_history_samples == 5
    assert SCFG.history_window_min == 15
    assert SCFG.history_quantile == 0.95
    assert SCFG.history_min_samples == 5
    assert SCFG.injection_value_kw == 7.2
    assert SCFG.budget_base_kw == 3.0
    assert SCFG.budget_step_kw == 1.5
    assert SCFG.budget_modulus == 4
    assert SCFG.probe_grid == (-3.0, -1.5, 0.0, 1.5, 3.0)
    assert SCFG.probe_modulus == 5
    assert SCFG.recovery_ratio == 0.95
    assert SCFG.recovery_sustained_cycles == 3
    assert SCFG.m1_target == 1.0 and SCFG.m2_target == 1.0 and SCFG.m4_target == 0.0
    assert SCFG.m3_min_traces == 20 and SCFG.m3_min_sessions == 5


def test_layer2_boundary_modes_fixed_mapping() -> None:
    assert SCFG.layer2_boundary_modes == {
        M1: "capability_supported_boundary",
        M2: "response_history_boundary",
        M3: "history_protective_boundary",
        M4: "conservative_fallback",
    }


def test_default_application_state() -> None:
    assert SCFG.default_application_state == {
        M1: "NORMAL",
        M2: "NORMAL",
        M3: "PROTECTIVE",
        M4: "LOCKED",
    }


def test_precedence_exhaustive_table() -> None:
    table, mode_arr, reason_arr = build_info_mode_table(SCFG)
    assert len(table) == 16
    assert all(res.mode in (M1, M2, M3, M4) for res in table.values())

    # 期望映射（与冻结 precedence 一一对应）：
    # rule1: capability → M1（不受 history/pilot/actual 影响）
    for pilot in (False, True):
        for actual in (False, True):
            for hist in (False, True):
                assert table[(True, pilot, actual, hist)].mode == M1
    # rule2: pilot+actual+history → M2
    assert table[(False, True, True, True)].mode == M2
    # rule3: pilot+actual 无 history → M4
    assert table[(False, True, True, False)].mode == M4
    # rule4: actual+history（无 pilot）→ M3
    assert table[(False, False, True, True)].mode == M3
    # rule5/else: 其余组合 → M4
    for comb in [(False, True, False, True), (False, True, False, False),
                 (False, False, True, False), (False, False, False, True),
                 (False, False, False, False)]:
        assert table[comb].mode == M4
        assert table[comb].reason_code in ("rule5", "fail_closed")

    # mode_arr 按 code=cap*8+pilot*4+actual*2+history 索引与 table 一致
    for (cap, pilot, actual, hist), res in table.items():
        code = int(cap) * 8 + int(pilot) * 4 + int(actual) * 2 + int(hist)
        assert mode_arr[code] == res.mode
        assert reason_arr[code] == res.reason_code


def test_assert_exhaustive_passes() -> None:
    assert_exhaustive(SCFG)


def test_eval_condition_rejects_unknown_var() -> None:
    with pytest.raises(ValueError, match="不允许的变量"):
        eval_condition("capability_available and evil_var", {"capability_available": True})


def test_lookup_mode_requires_else_last() -> None:
    with pytest.raises(ValueError, match="没有 else fail_closed"):
        lookup_mode((("actual_available", M3),), {"actual_available": False})
