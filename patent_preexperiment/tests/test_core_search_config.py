"""CORE-PATENT SEARCH 配置加载与冻结值校验（fail-closed，禁止硬编码回退）。

验证 core_search_v1.yaml 的 P0-A / P0-B 门阈值以结构化字段读取，
缺失时抛错而不是静默回退到代码内默认值（AGENTS.md 预注册红线）。
"""

from __future__ import annotations

import pytest

from patent_preexperiment.core_search.config import (
    _parse_p0a_gate,
    _parse_p0b_gate,
    load_core_search_config,
)


def test_load_config_parses_structured_gates():
    cfg = load_core_search_config()
    g = cfg.p0_a.gate
    assert g.usable_events_min == 100
    assert g.unique_sessions_min == 30
    assert g.stations_min == 5
    assert g.months_min == 2
    assert g.no_go_1m_full_response_median == 0.9
    assert g.no_go_1m_full_response_std == 0.1
    assert g.time_dynamic_diff_threshold == 0.05
    assert g.heterogeneity_iqr_threshold == 0.05
    assert g.repeatability_corr_threshold == 0.1

    b = cfg.p0_b.gate
    assert b.bess_comparison_kw_low == 100.0
    assert b.bess_comparison_kw_high == 200.0
    assert b.go_reliable_flex_peak_min_kw == 100.0


def test_p0a_gate_missing_sufficiency_raises():
    gate = {
        "no_go_deterministic_1m": {
            "full_response_median_min": 0.9,
            "full_response_std_max": 0.1,
        },
        "time_dynamic_diff_threshold": 0.05,
        "heterogeneity_iqr_threshold": 0.05,
        "repeatability_corr_threshold": 0.1,
    }
    with pytest.raises(ValueError):
        _parse_p0a_gate(gate)


def test_p0a_gate_missing_threshold_raises():
    gate = {
        "sufficiency": {
            "usable_events_min": 100,
            "unique_sessions_min": 30,
            "stations_min": 5,
            "months_min": 2,
        },
        "no_go_deterministic_1m": {
            "full_response_median_min": 0.9,
            "full_response_std_max": 0.1,
        },
        "heterogeneity_iqr_threshold": 0.05,
        "repeatability_corr_threshold": 0.1,
    }
    with pytest.raises(ValueError):
        _parse_p0a_gate(gate)


def test_p0b_gate_missing_field_raises():
    gate = {
        "bess_comparison_kw_low": 100.0,
        "bess_comparison_kw_high": 200.0,
    }
    with pytest.raises(ValueError):
        _parse_p0b_gate(gate)
