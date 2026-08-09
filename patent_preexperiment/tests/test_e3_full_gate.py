"""E3-Full gate 测试（R1 / 审查结论28）：分层门判定与正式裁决优先级。

覆盖：
- caltech_split_gate：M1(CI 下界)/M2(能量占比)/M3(消除率)/M4(非单月) 与 all_pass；
- jpl_split_gate：X1(能量占比)/X2(非单月)/X3(唯一性)；
- cross_pool_gate：两池能量占比各自达标；
- formal_verdict 四分支：E3_PASS / STOP_COMPLEX_MODEL / FORMAL_FAIL_MAIN / FORMAL_FAIL_CROSS_POOL；
- review_required：train/validation PASS 而 test FAIL；
- formal_exit_code：fail-closed（STOP_COMPLEX_MODEL 也返回 1）。
"""

from __future__ import annotations

import pytest

from patent_preexperiment.e3_full.gate import (
    caltech_split_gate,
    cross_pool_gate,
    formal_exit_code,
    formal_verdict,
    jpl_split_gate,
)

STOP = {
    "caltech_a2_daily_ci_lower_rate": 0.01,
    "daily_energy_share_each_pool": 0.005,
    "max_baseline_elimination": 0.80,
    "not_single_month_or_outlier": True,
}


def _audit(
    ci_lower: float | None = 0.02,
    energy_share: float | None = 0.01,
    elim_a2: float | None = 0.3,
    elim_a3: float | None = 0.4,
    n_months: int = 3,
    n_dup: int = 0,
) -> dict:
    return {
        "day_cluster_ci95": {
            "A2_prev_actual": {"ci95": [ci_lower, 0.05] if ci_lower is not None else None}
        },
        "daily_energy_share_median": energy_share,
        "elimination_vs_A0": {
            "A2_prev_actual": {"point": elim_a2},
            "A3_rolling_quantile": {"point": elim_a3},
        },
        "concentration": {
            "n_months_with_opp": n_months,
            "top_month_share_of_opp_energy": 0.4,
            "top_day_share_of_opp_energy": 0.15,
        },
        "n_dup_cycles": n_dup,
    }


def _caltech_gate(**kw) -> dict:
    return caltech_split_gate(_audit(**kw), STOP)


def _jpl_gate(**kw) -> dict:
    return jpl_split_gate(_audit(**kw), STOP)


def test_caltech_gate_all_pass() -> None:
    g = _caltech_gate()
    assert g["m1_a2_daily_ci_lower_rate"] is True
    assert g["m2_caltech_energy_share"] is True
    assert g["m3_baseline_not_eliminated"] is True
    assert g["m4_not_single_month"] is True
    assert g["all_pass"] is True


def test_caltech_gate_m1_fail_ci_below_threshold() -> None:
    g = _caltech_gate(ci_lower=0.005)  # < 0.01
    assert g["m1_a2_daily_ci_lower_rate"] is False
    assert g["all_pass"] is False


def test_caltech_gate_m2_fail_energy_share() -> None:
    g = _caltech_gate(energy_share=0.003)  # < 0.005
    assert g["m2_caltech_energy_share"] is False
    assert g["all_pass"] is False


def test_caltech_gate_m3_fail_elimination_too_high() -> None:
    g = _caltech_gate(elim_a2=0.9)  # > 0.80
    assert g["m3_baseline_not_eliminated"] is False
    assert g["m3_elim_max"] == pytest.approx(0.9)
    assert g["all_pass"] is False


def test_caltech_gate_m4_fail_single_month() -> None:
    g = _caltech_gate(n_months=1)
    assert g["m4_not_single_month"] is False
    assert g["all_pass"] is False


def test_caltech_gate_m1_fail_ci_none() -> None:
    g = _caltech_gate(ci_lower=None)
    assert g["m1_a2_daily_ci_lower_rate"] is False
    assert g["all_pass"] is False


def test_jpl_gate_all_pass() -> None:
    g = _jpl_gate()
    assert g["x1_energy_share"] is True
    assert g["x2_not_single_month"] is True
    assert g["x3_uniqueness"] is True
    assert g["all_pass"] is True


def test_jpl_gate_x3_fail_dup_cycles() -> None:
    g = _jpl_gate(n_dup=1)
    assert g["x3_uniqueness"] is False
    assert g["all_pass"] is False


def test_cross_pool_gate_both_pass() -> None:
    cal = _caltech_gate()
    jpl = _jpl_gate()
    assert cross_pool_gate(cal, jpl)["energy_share_each_pool_pass"] is True


def test_cross_pool_gate_caltech_fails() -> None:
    cal = _caltech_gate(energy_share=0.003)
    jpl = _jpl_gate()
    assert cross_pool_gate(cal, jpl)["energy_share_each_pool_pass"] is False


def test_verdict_pass() -> None:
    v = formal_verdict(
        caltech_test=_caltech_gate(), jpl_test=_jpl_gate(),
        caltech_train=_caltech_gate(), caltech_validation=_caltech_gate(),
        jpl_train=_jpl_gate(), jpl_validation=_jpl_gate(), stop=STOP,
    )
    assert v["primary"] == "E3_PASS"
    assert v["review_required"] is False
    assert v["main_review_required"] is False
    assert v["cross_pool_review_required"] is False
    assert formal_exit_code(v) == 0


def test_verdict_stop_complex_model() -> None:
    """优先级②：A2/A3 消除 >80% → 停止复杂区间模型（即便主门其他项通过）。"""
    v = formal_verdict(
        caltech_test=_caltech_gate(elim_a2=0.85), jpl_test=_jpl_gate(),
        caltech_train=_caltech_gate(), caltech_validation=_caltech_gate(),
        jpl_train=_jpl_gate(), jpl_validation=_jpl_gate(), stop=STOP,
    )
    assert v["primary"] == "STOP_COMPLEX_MODEL"
    assert formal_exit_code(v) == 1  # fail-closed


def test_verdict_fail_main() -> None:
    """优先级③：Caltech test 主门 FAIL → JPL 不得 rescue。"""
    v = formal_verdict(
        caltech_test=_caltech_gate(ci_lower=0.005), jpl_test=_jpl_gate(),
        caltech_train=_caltech_gate(), caltech_validation=_caltech_gate(),
        jpl_train=_jpl_gate(), jpl_validation=_jpl_gate(), stop=STOP,
    )
    assert v["primary"] == "FORMAL_FAIL_MAIN"
    assert formal_exit_code(v) == 1


def test_verdict_fail_cross_pool() -> None:
    """优先级④：Caltech PASS 但 JPL 跨池佐证不足。"""
    v = formal_verdict(
        caltech_test=_caltech_gate(), jpl_test=_jpl_gate(energy_share=0.003),
        caltech_train=_caltech_gate(), caltech_validation=_caltech_gate(),
        jpl_train=_jpl_gate(), jpl_validation=_jpl_gate(), stop=STOP,
    )
    assert v["primary"] == "FORMAL_FAIL_CROSS_POOL"
    assert formal_exit_code(v) == 1


def test_verdict_main_review_required_train_val_pass_test_fail() -> None:
    """NB-1 main_review：Caltech train/val PASS 而 test 主门 FAIL → main_review=True。"""
    v = formal_verdict(
        caltech_test=_caltech_gate(ci_lower=0.005), jpl_test=_jpl_gate(),
        caltech_train=_caltech_gate(), caltech_validation=_caltech_gate(),
        jpl_train=_jpl_gate(), jpl_validation=_jpl_gate(), stop=STOP,
    )
    assert v["primary"] == "FORMAL_FAIL_MAIN"
    assert v["main_review_required"] is True
    assert v["review_required"] is True


def test_verdict_cross_pool_review_required() -> None:
    """NB-1 cross_pool_review：双轨 train/val + cross-pool 全 PASS 而 test FAIL。"""
    v = formal_verdict(
        caltech_test=_caltech_gate(), jpl_test=_jpl_gate(energy_share=0.003),
        caltech_train=_caltech_gate(), caltech_validation=_caltech_gate(),
        jpl_train=_jpl_gate(), jpl_validation=_jpl_gate(), stop=STOP,
    )
    assert v["primary"] == "FORMAL_FAIL_CROSS_POOL"
    assert v["cross_pool_review_required"] is True
    assert v["review_required"] is True


def test_verdict_no_cross_pool_review_when_jpl_train_fails() -> None:
    """NB-1 关键：JPL train 已 FAIL → cross_pool_review 不触发（不误标标准情况二）。
    Caltech train/val PASS → main_review 仍可触发（test 主门 FAIL 时）。"""
    v = formal_verdict(
        caltech_test=_caltech_gate(ci_lower=0.005), jpl_test=_jpl_gate(),
        caltech_train=_caltech_gate(), caltech_validation=_caltech_gate(),
        jpl_train=_jpl_gate(energy_share=0.003), jpl_validation=_jpl_gate(), stop=STOP,
    )
    assert v["primary"] == "FORMAL_FAIL_MAIN"
    assert v["cross_pool_review_required"] is False
    assert v["main_review_required"] is True  # Caltech train/val 仍 PASS


def test_verdict_no_review_when_train_also_fails() -> None:
    v = formal_verdict(
        caltech_test=_caltech_gate(ci_lower=0.005), jpl_test=_jpl_gate(),
        caltech_train=_caltech_gate(ci_lower=0.005), caltech_validation=_caltech_gate(),
        jpl_train=_jpl_gate(), jpl_validation=_jpl_gate(), stop=STOP,
    )
    assert v["review_required"] is False


def test_caltech_gate_m4_concentration_diagnostic_only() -> None:
    """NB-2：M4 hard = n_months>=2；top_month/top_day 只作 diagnostic 输出。"""
    g = _caltech_gate(n_months=1)
    assert g["m4_not_single_month"] is False
    assert "m4_concentration_diagnostic" in g
    diag = g["m4_concentration_diagnostic"]
    assert "top_month_share" in diag and "top_day_share" in diag
