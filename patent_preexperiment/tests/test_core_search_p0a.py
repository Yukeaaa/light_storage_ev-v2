"""CORE-PATENT SEARCH P0-A 单元测试：binding 分类 / response_fraction / 分层 / repeatability / 门。

用合成事件验证逻辑正确性（不依赖外部数据）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.config import (
    BindingRules,
    P0AConfig,
    P0AGate,
    ResponseLagRules,
)
from patent_preexperiment.core_search.p0a_response import (
    add_strata,
    classify_binding,
    compute_response_fraction,
    compute_session_repeatability,
    evaluate_p0a_gate,
    summarize_response,
)

_TOL = 0.5
_BIND = BindingRules(tolerance_kw=_TOL)
_RESP = ResponseLagRules(lag_min=(1, 3, 5), fraction_clip_low=0.0, fraction_clip_high=2.0)


def _make_events(
    n: int,
    direction: str = "down",
    *,
    pilot_after: list[float] | None = None,
    actual_before: list[float] | None = None,
    actual_1m: list[float] | None = None,
    actual_3m: list[float] | None = None,
    actual_5m: list[float] | None = None,
    session_ids: list[str] | None = None,
    stations: list[str] | None = None,
    sites: list[str] | None = None,
    months: list[str] | None = None,
    splits: list[str] | None = None,
    pilot_before_kw: list[float] | None = None,
    delta_pilot_kw: list[float] | None = None,
    connected_elapsed: list[float] | None = None,
) -> pd.DataFrame:
    pa = pilot_after or [3.0] * n
    ab = actual_before or [6.0] * n
    a1 = actual_1m or [5.0] * n
    a3 = actual_3m or [4.0] * n
    a5 = actual_5m or [3.5] * n
    pb = pilot_before_kw or [6.0] * n
    dp = delta_pilot_kw or [-3.0] * n
    ce = connected_elapsed or [30.0] * n
    sids = session_ids or [f"S{i}" for i in range(n)]
    sts = stations or [f"ST{i % 3}" for i in range(n)]
    sis = sites or ["caltech"] * n
    ms = months or ["2020-06"] * n
    sp = splits or ["train"] * n
    return pd.DataFrame({
        "event_id": [f"e{i}" for i in range(n)],
        "session_id": sids,
        "station_id": sts,
        "site": sis,
        "timestamp": pd.date_range("2020-06-01", periods=n, freq="1min", tz="UTC"),
        "direction": direction,
        "pilot_before_kw": pb,
        "pilot_after_kw": pa,
        "delta_pilot_kw": dp,
        "actual_before_kw": ab,
        "actual_1min_kw": a1,
        "actual_3min_kw": a3,
        "actual_5min_kw": a5,
        "connected_elapsed_min": ce,
        "month": ms,
        "split": sp,
    })


# --- binding 分类 ---

def test_binding_decrease_classified():
    ev = _make_events(3, "down", pilot_after=[3.0, 5.8, 7.0], actual_before=[6.0, 6.0, 6.0])
    out = classify_binding(ev, _BIND)
    # 3.0 < 6.0 - 0.5 = 5.5 → binding
    # 5.8 >= 5.5 → non_binding
    # 7.0 >= 5.5 → non_binding
    assert list(out["binding"]) == ["binding", "non_binding", "non_binding"]


def test_binding_increase_classified():
    ev = _make_events(
        3, "up",
        pilot_after=[9.0, 6.2, 5.0],
        actual_before=[6.0, 6.0, 6.0],
    )
    out = classify_binding(ev, _BIND)
    # 9.0 > 6.0 + 0.5 = 6.5 → binding
    # 6.2 <= 6.5 → non_binding
    # 5.0 <= 6.5 → non_binding
    assert list(out["binding"]) == ["binding", "non_binding", "non_binding"]


# --- response_fraction ---

def test_response_fraction_down():
    ev = _make_events(
        1, "down",
        pilot_after=[3.0], actual_before=[6.0],
        actual_1m=[5.0], actual_3m=[4.0], actual_5m=[3.5],
    )
    out = classify_binding(ev, _BIND)
    out = compute_response_fraction(out, _RESP)
    # down: r = (6 - lag) / (6 - 3) = (6-lag)/3
    assert np.isclose(out["response_fraction_1m"].iloc[0], 1 / 3)
    assert np.isclose(out["response_fraction_3m"].iloc[0], 2 / 3)
    assert np.isclose(out["response_fraction_5m"].iloc[0], 2.5 / 3)


def test_response_fraction_up():
    ev = _make_events(
        1, "up",
        pilot_after=[9.0], actual_before=[6.0],
        actual_1m=[7.0], actual_3m=[8.0], actual_5m=[8.5],
        pilot_before_kw=[6.0], delta_pilot_kw=[3.0],
    )
    out = classify_binding(ev, _BIND)
    out = compute_response_fraction(out, _RESP)
    # up: r = (lag - 6) / (9 - 6) = (lag-6)/3
    assert np.isclose(out["response_fraction_1m"].iloc[0], 1 / 3)
    assert np.isclose(out["response_fraction_3m"].iloc[0], 2 / 3)
    assert np.isclose(out["response_fraction_5m"].iloc[0], 2.5 / 3)


def test_response_fraction_non_binding_is_nan():
    ev = _make_events(
        1, "down",
        pilot_after=[5.8], actual_before=[6.0],
        actual_1m=[5.5], actual_3m=[5.0], actual_5m=[4.8],
    )
    out = classify_binding(ev, _BIND)
    out = compute_response_fraction(out, _RESP)
    assert pd.isna(out["response_fraction_1m"].iloc[0])
    assert pd.isna(out["response_fraction_3m"].iloc[0])


def test_response_fraction_clip():
    ev = _make_events(
        1, "down",
        pilot_after=[0.1], actual_before=[6.0],
        actual_1m=[0.0], actual_3m=[0.0], actual_5m=[0.0],
    )
    out = classify_binding(ev, _BIND)
    out = compute_response_fraction(out, _RESP)
    # r = (6-0)/(6-0.1) = 6/5.9 ≈ 1.017 → 不超 clip
    # 5min: (6-0)/5.9 = 1.017
    assert out["response_fraction_5m"].iloc[0] <= 2.0


# --- 分层 ---

def test_add_strata_phase():
    ev = _make_events(3, "down", connected_elapsed=[5.0, 50.0, 150.0])
    out = add_strata(ev)
    assert list(out["session_phase"]) == ["early", "mid", "late"]


def test_add_strata_power_bins():
    ev = _make_events(3, "down", actual_before=[1.0, 3.0, 7.0])
    out = add_strata(ev)
    assert list(out["actual_before_bin"]) == ["low", "mid", "high"]


# --- 汇总 ---

def test_summarize_response_returns_rows():
    ev = _make_events(
        2, "down",
        pilot_after=[3.0, 3.0], actual_before=[6.0, 6.0],
        actual_1m=[5.0, 4.0], actual_3m=[4.0, 3.0], actual_5m=[3.5, 2.5],
    )
    out = classify_binding(ev, _BIND)
    out = compute_response_fraction(out, _RESP)
    summ = summarize_response(out, (1, 3, 5))
    assert len(summ) == 3  # 3 lags for 1 direction
    assert set(summ["lag_min"]) == {1, 3, 5}


# --- repeatability ---

def test_session_repeatability_correlation():
    # 5 sessions, each with 2 binding events; first rf varies across sessions
    # to create a real correlation (not all-identical which gives std=0 → NaN).
    sids: list[str] = []
    a3_firsts = [4.0, 4.5, 3.5, 5.0, 3.0]  # varies → rf varies
    a3_laters = [4.2, 4.3, 3.8, 4.8, 3.2]
    actual_3m: list[float] = []
    for i in range(5):
        sids += [f"S{i}", f"S{i}"]
        actual_3m += [a3_firsts[i], a3_laters[i]]
    ev = _make_events(
        10, "down",
        pilot_after=[3.0] * 10, actual_before=[6.0] * 10,
        actual_1m=[5.0] * 10, actual_3m=actual_3m, actual_5m=[3.5] * 10,
        session_ids=sids,
        stations=[f"ST{i // 2}" for i in range(10)],
        splits=["train"] * 10,
    )
    out = classify_binding(ev, _BIND)
    out = compute_response_fraction(out, _RESP)
    rep, corr = compute_session_repeatability(out, lag=3)
    assert len(rep) == 5
    assert not np.isnan(corr)


# --- gate ---

def _gate_cfg() -> P0AConfig:
    return P0AConfig(
        binding=_BIND,
        response=_RESP,
        gate=P0AGate(
            usable_events_min=2,
            unique_sessions_min=2,
            stations_min=2,
            months_min=1,
            no_go_1m_full_response_median=0.9,
            no_go_1m_full_response_std=0.1,
            time_dynamic_diff_threshold=0.05,
            heterogeneity_iqr_threshold=0.05,
            repeatability_corr_threshold=0.1,
        ),
        results_root="results/raw/core_search/p0_a",
        report_path="reports/core_search/CORE_P0_A_EV_RESPONSE.md",
        counting_scope="train+validation",
    )


def test_gate_go_binding_sufficient_with_time_dynamic():
    # binding down 事件，1/3/5min 明显不同
    ev = _make_events(
        4, "down",
        pilot_after=[3.0] * 4, actual_before=[6.0] * 4,
        actual_1m=[5.0] * 4, actual_3m=[4.0] * 4, actual_5m=[3.0] * 4,
        session_ids=["A", "B", "C", "D"],
        stations=["ST0", "ST1", "ST0", "ST1"],
        months=["2020-06"] * 4,
        splits=["train"] * 4,
    )
    out = classify_binding(ev, _BIND)
    out = compute_response_fraction(out, _RESP)
    v = evaluate_p0a_gate(out, 0.0, _gate_cfg())
    assert v.verdict == "GO"
    assert v.binding_sufficient


def test_gate_no_go_insufficient():
    ev = _make_events(
        1, "down",
        pilot_after=[3.0], actual_before=[6.0],
        actual_1m=[5.0], actual_3m=[4.0], actual_5m=[3.0],
        session_ids=["A"], stations=["ST0"], months=["2020-06"], splits=["train"],
    )
    out = classify_binding(ev, _BIND)
    out = compute_response_fraction(out, _RESP)
    v = evaluate_p0a_gate(out, 0.0, _gate_cfg())
    assert v.verdict == "NO_GO"
    assert not v.binding_sufficient


def test_gate_no_go_deterministic_1m():
    # binding 充分但 1min 内几乎完全响应（rf_1m ≈ 1.0，std 很小）
    ev = _make_events(
        4, "up",
        pilot_after=[9.0] * 4, actual_before=[6.0] * 4,
        actual_1m=[8.99, 8.98, 8.99, 8.97],
        actual_3m=[9.0] * 4, actual_5m=[9.0] * 4,
        pilot_before_kw=[6.0] * 4, delta_pilot_kw=[3.0] * 4,
        session_ids=["A", "B", "C", "D"],
        stations=["ST0", "ST1", "ST0", "ST1"],
        months=["2020-06"] * 4,
        splits=["train"] * 4,
    )
    out = classify_binding(ev, _BIND)
    out = compute_response_fraction(out, _RESP)
    v = evaluate_p0a_gate(out, 0.0, _gate_cfg())
    # up: r_1m = (8.9x - 6) / 3 ≈ 0.99，几乎完全响应；std 很小
    # 3m/5m: (9-6)/3 = 1.0 → 与 1m 差异小 → time_dynamic False
    # 但 no_go_deterministic 需要 1m median > 0.9 且 std < 0.1
    assert v.no_go_deterministic_1m
    assert v.verdict == "NO_GO"
