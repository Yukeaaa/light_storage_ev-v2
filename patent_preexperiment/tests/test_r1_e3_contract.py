"""R1-E3 配置契约测试（审查结论29）：r1_e3.yaml 独立预注册结构与冻结值校验。

确保 R1-E3 新增 config 不修改已被 D0 冻结的 e0_full.yaml，且引用关系/双轨人口/
代理集/M4 语义/runner 治理/evaluable-day 口径与代码实现一致。
"""

from __future__ import annotations

from pathlib import Path

import yaml

PP = Path(__file__).resolve().parents[1]
CONFIGS = PP / "configs"


def _load_r1_e3() -> dict:
    with open(CONFIGS / "r1_e3.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_e0() -> dict:
    with open(CONFIGS / "e0_full.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_r1_e3_required_sections() -> None:
    cfg = _load_r1_e3()
    for key in (
        "experiment_id", "protocol_version", "review_conclusions",
        "references", "populations", "proxies", "gates",
        "evaluable_day_rule", "runner_governance", "outputs",
        "fail_cases", "terminology",
    ):
        assert key in cfg, f"r1_e3.yaml 缺少必需字段 {key}"


def test_r1_e3_references_e0_stop_lines_not_redefining() -> None:
    """审查结论29：停止线引用 e0_full.yaml，不重复定义数值（单一事实来源）。"""
    r1 = _load_r1_e3()
    assert "stop_lines" in r1["references"]
    assert "e0_full.yaml" in r1["references"]["stop_lines"]
    # r1_e3.yaml 顶层不应有独立 stop_lines 数值定义（只在 gates 下引用 ref）
    assert "k1_replication_stop_lines" not in r1
    # gates 下各阈值必须有 threshold_ref 指向 e0_full.yaml（非自创）
    cal = r1["gates"]["E3_M_caltech_main"]
    for mk in ("M1_a2_daily_ci_lower_rate", "M2_caltech_energy_share",
               "M3_baseline_not_eliminated"):
        assert "threshold_ref" in cal[mk]
        assert "e0_full.yaml" in cal[mk]["threshold_ref"]


def test_r1_e3_stop_line_values_match_e0() -> None:
    """gates 下的 value 必须与 e0_full.yaml 冻结值一致（防漂移）。"""
    r1 = _load_r1_e3()
    e0 = _load_e0()
    e0_e3 = e0["k1_replication_stop_lines"]["e3"]
    cal = r1["gates"]["E3_M_caltech_main"]
    assert cal["M1_a2_daily_ci_lower_rate"]["value"] == e0_e3["caltech_a2_daily_ci_lower_rate"]
    assert cal["M2_caltech_energy_share"]["value"] == e0_e3["daily_energy_share_each_pool"]
    assert cal["M3_baseline_not_eliminated"]["value"] == e0_e3["max_baseline_elimination"]


def test_r1_e3_population_counts_match_code() -> None:
    """人口期望计数与 loader 实测 registry 一致（审查结论28 冻结值）。"""
    r1 = _load_r1_e3()
    cal = r1["populations"]["E3_M_caltech_main"]["expected_counts"]
    jpl = r1["populations"]["E3_X_jpl_current_only"]["expected_counts"]
    assert cal == {"total": 13477, "train": 9426, "validation": 3896, "test": 155}
    assert jpl == {"total": 20925, "train": 13908, "validation": 5026, "test": 1991}


def test_r1_e3_proxies_match_code() -> None:
    """代理集与 stats.CALTECH_PROXIES / JPL_PROXIES 一致。"""
    r1 = _load_r1_e3()
    assert r1["proxies"]["caltech"] == ["A0_avg", "A2_prev_actual", "A3_rolling_quantile"]
    assert r1["proxies"]["jpl_current_only"] == ["A2_prev_actual", "A3_rolling_quantile"]
    assert r1["proxies"]["main_baseline"] == "A2_prev_actual"


def test_r1_e3_m4_hard_is_n_months_no_outlier_cutoff() -> None:
    """审查结论29 NB-2：M4 hard = n_months>=2；top_month/top_day 仅 diagnostic。"""
    r1 = _load_r1_e3()
    m4 = r1["gates"]["E3_M_caltech_main"]["M4_not_single_month"]
    assert m4["hard"] == "n_months_with_opp >= 2"
    assert "diagnostic_only" in m4
    assert "top_month_share_of_opp_energy" in m4["diagnostic_only"]
    assert "top_day_share_of_opp_energy" in m4["diagnostic_only"]


def test_r1_e3_evaluable_day_rule_frozen() -> None:
    """审查结论29 P0-4：evaluable-day 口径冻结。"""
    r1 = _load_r1_e3()
    ed = r1["evaluable_day_rule"]
    assert "candidate=True" in ed["definition"]
    assert "non-evaluable ≠ real zero" in ed["non_evaluable_handling"]
    assert "n_operating_days" in ed["report"]


def test_r1_e3_runner_governance_modes() -> None:
    """审查结论29 P0-1/P0-2/P0-3：runner 三模式 + once-only 状态机 + clean/SHA hard gate。"""
    r1 = _load_r1_e3()
    rg = r1["runner_governance"]
    assert set(rg["modes"]) == {"pretest", "formal_test", "read_frozen"}
    assert rg["once_only_state_machine"]["forbidden_on_rerun"] == ["started", "completed"]
    assert "code_sha == expected_code_sha" in rg["clean_sha_hard_gate"]["assertions"]


def test_r1_e3_review_required_split() -> None:
    """审查结论29 NB-1：review_required 拆 main/cross_pool。"""
    r1 = _load_r1_e3()
    rr = r1["gates"]["review_required"]
    assert "main_review" in rr and "cross_pool_review" in rr
    assert "JPL train 已 FAIL 不误标" in rr["note"]


def test_r1_e3_terminology_forbidden() -> None:
    """术语纪律：可回收能力/命令失败/拒绝/可吸收余量 禁用。"""
    r1 = _load_r1_e3()
    forbidden = r1["terminology"]["forbidden"]
    for term in ("可回收能力", "命令失败", "拒绝", "可吸收余量"):
        assert term in forbidden
