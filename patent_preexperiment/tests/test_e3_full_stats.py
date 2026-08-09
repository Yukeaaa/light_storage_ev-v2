"""E3-Full stats 测试（R1 / 审查结论28）：pool_audit 候选率、fan-out 守卫、能量占比、浓度。

合成数据：2 会话 × 4 个 5min 周期，同池（site+garage）。
- cycle1/2：actual=6kW（建立 actual_prev / rolling 历史）
- cycle3/4：actual=2kW（prev=6 → slack=4≥0.5，n_active=2 → 候选窗口）
A3_rolling_quantile 需 min_periods=2 → cycle3 起可计算；caltech [A0,A2,A3] 与
jpl [A2,A3] 的 eligible 交集都落在 cycle3/4，候选率=1.0。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patent_preexperiment.e3_full.stats import (
    CALTECH_PROXIES,
    JPL_PROXIES,
    audit_to_serializable,
    pool_audit,
)

SEED = 42
N_BOOT = 200


def _synth_minutes(site: str, garage: str, pilot_kw: float | None) -> pd.DataFrame:
    """2 会话 × 4 周期（5min 间距）。cycle1/2 actual=6，cycle3/4 actual=2。"""
    base = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    rows = []
    actuals = [6.0, 6.0, 2.0, 2.0]
    for sid in ("s1", "s2"):
        for i, a in enumerate(actuals):
            rows.append({
                "session_id": f"{site}_{sid}", "station_id": f"st_{sid}",
                "site": site, "garage": garage,
                "timestamp_utc": base + pd.Timedelta(minutes=5 * i),
                "actual_power_kw": a,
                "pilot_power_kw": pilot_kw if pilot_kw is not None else np.nan,
            })
    return pd.DataFrame(rows)


def test_pool_audit_caltech_candidate_rate() -> None:
    df = _synth_minutes("caltech", "California_Garage_01", pilot_kw=8.0)
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    audit.pop("_cand", None)
    assert audit["n_valid_cycles"] == 2  # cycle3, cycle4 eligible
    # A2=prev_actual：cycle3 候选（prev=6, slack=4），cycle4 prev 追平=2 → 不候选 → 0.5
    assert audit["cycle_weighted_rate"]["A2_prev_actual"] == pytest.approx(0.5)
    # A3=rolling_quantile：历史 6,6 主导 q90 → 两周期都候选 → 1.0
    assert audit["cycle_weighted_rate"]["A3_rolling_quantile"] == pytest.approx(1.0)
    # A0_avg=pilot 恒定 8 → 两周期都候选 → 1.0
    assert audit["cycle_weighted_rate"]["A0_avg"] == pytest.approx(1.0)


def test_pool_audit_caltech_a0_finite_in_eligible_cycles() -> None:
    df = _synth_minutes("caltech", "California_Garage_01", pilot_kw=8.0)
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    cand = audit.pop("_cand")
    # A0 只在 pilot 覆盖足够的周期可计算；eligible 周期（cycle3/4）A0 应有限
    assert cand["candidate_A0_avg"].any()


def test_pool_audit_no_fan_out() -> None:
    """审查结论28：候选表 [site,garage,cycle] 必须唯一（n_dup_cycles==0）。"""
    df = _synth_minutes("caltech", "California_Garage_01", pilot_kw=8.0)
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    audit.pop("_cand", None)
    assert audit["n_dup_cycles"] == 0


def test_pool_audit_energy_share_passes_threshold() -> None:
    df = _synth_minutes("caltech", "California_Garage_01", pilot_kw=8.0)
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    audit.pop("_cand", None)
    assert audit["daily_energy_share_median"] is not None
    assert audit["daily_energy_share_median"] >= 0.005


def test_pool_audit_jpl_current_only_without_pilot() -> None:
    """jpl current-only 无 pilot：A2/A3 仍可计算候选（current-only 回退路径）。"""
    df = _synth_minutes("jpl", "Arroyo_Garage_01", pilot_kw=None)
    audit = pool_audit(df, "jpl.Arroyo_Garage_01.current_only", JPL_PROXIES, SEED, N_BOOT)
    audit.pop("_cand", None)
    assert audit["n_valid_cycles"] == 2
    # A2=prev_actual：cycle3 候选，cycle4 prev 追平 → 0.5（与 caltech 同口径）
    assert audit["cycle_weighted_rate"]["A2_prev_actual"] == pytest.approx(0.5)
    # A3=rolling_quantile：历史高值主导 → 1.0
    assert audit["cycle_weighted_rate"]["A3_rolling_quantile"] == pytest.approx(1.0)


def test_pool_audit_concentration_single_month() -> None:
    df = _synth_minutes("caltech", "California_Garage_01", pilot_kw=8.0)
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    audit.pop("_cand", None)
    conc = audit["concentration"]
    assert conc["n_months_with_opp"] == 1  # 全部 2018-11
    assert conc["top_month_share_of_opp_energy"] == pytest.approx(1.0)


def test_pool_audit_duration_single_run() -> None:
    """主基线 A2 只 cycle3 候选 → 1 个 run，时长=5min（单周期）。"""
    df = _synth_minutes("caltech", "California_Garage_01", pilot_kw=8.0)
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    audit.pop("_cand", None)
    dur = audit["opportunity_duration_min"]
    assert dur["n_runs"] == 1
    assert dur["duration_median_min"] == pytest.approx(5.0)


def test_pool_audit_concurrency() -> None:
    df = _synth_minutes("caltech", "California_Garage_01", pilot_kw=8.0)
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    audit.pop("_cand", None)
    conc = audit["concurrency"]
    assert conc["candidate_cycles"] == 1  # A2 仅 cycle3 候选
    assert conc["median_n_active"] == pytest.approx(2.0)


def test_pool_audit_elimination_vs_a0() -> None:
    """caltech：A2 候选率 0.5 vs A0 1.0 → 消除 50%；A3 1.0 vs A0 → 消除 0%。"""
    df = _synth_minutes("caltech", "California_Garage_01", pilot_kw=8.0)
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    audit.pop("_cand", None)
    elim = audit["elimination_vs_A0"]
    assert elim["A2_prev_actual"]["point"] == pytest.approx(0.5)
    assert elim["A3_rolling_quantile"]["point"] == pytest.approx(0.0, abs=1e-6)


def test_audit_to_serializable_strips_cand() -> None:
    df = _synth_minutes("caltech", "California_Garage_01", pilot_kw=8.0)
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    serial = audit_to_serializable(audit)
    assert "_cand" not in serial
    assert "n_valid_cycles" in serial


# ---- 审查结论30 P0-2：daily_energy_share evaluable-day K1 exact 口径回归 ----


def _three_day_minutes() -> pd.DataFrame:
    """三日数据，覆盖 P0-2 的两种情况：
    - day1（2018-11-01）：2 会话 × 4 周期，cycle3 产生 candidate=True → share 正值。
    - day2（2018-11-02，case A）：2 会话 × 4 周期，actual 恒高=10（slack=prev10-actual10=0
      <margin）→ 有 valid paired cycles（在 candidate table）但全部 candidate=False →
      evaluable，share=0 是真实零效果，进入 median。
    - day3（2018-11-03，case B）：1 会话 × 4 周期，actual 全 NaN → build_cycles 丢弃
      → 无 candidate table 行 → non-evaluable，不以 0 进入 median。
    """
    base1 = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    base2 = pd.Timestamp("2018-11-02 08:00:00", tz="UTC")
    base3 = pd.Timestamp("2018-11-03 08:00:00", tz="UTC")
    rows: list[dict] = []
    # day1：2 会话，cycle1/2 actual=6，cycle3/4 actual=2，pilot=8 → cycle3 candidate
    for sid in ("d1_s1", "d1_s2"):
        for i, a in enumerate([6.0, 6.0, 2.0, 2.0]):
            rows.append({
                "session_id": f"caltech_{sid}", "station_id": f"st_{sid}",
                "site": "caltech", "garage": "California_Garage_01",
                "timestamp_utc": base1 + pd.Timedelta(minutes=5 * i),
                "actual_power_kw": a, "pilot_power_kw": 8.0,
            })
    # day2 case A：2 会话，actual 恒=10（slack=0，无 candidate=True，但有 valid cycles）
    for sid in ("d2_s1", "d2_s2"):
        for i in range(4):
            rows.append({
                "session_id": f"caltech_{sid}", "station_id": f"st_{sid}",
                "site": "caltech", "garage": "California_Garage_01",
                "timestamp_utc": base2 + pd.Timedelta(minutes=5 * i),
                "actual_power_kw": 10.0, "pilot_power_kw": 8.0,
            })
    # day3 case B：1 会话，actual 全 NaN → build_cycles 丢弃 → 无 candidate table 行
    for i in range(4):
        rows.append({
            "session_id": "caltech_d3_s1", "station_id": "st_d3s1",
            "site": "caltech", "garage": "California_Garage_01",
            "timestamp_utc": base3 + pd.Timedelta(minutes=5 * i),
            "actual_power_kw": np.nan, "pilot_power_kw": 8.0,
        })
    return pd.DataFrame(rows)


def test_daily_energy_share_case_a_evaluable_zero_in_median() -> None:
    """P0-2 case A：day2 有 valid paired cycles 但全 candidate=False → evaluable，
    share=0 是真实零效果，进入 median（不被排除）。"""
    df = _three_day_minutes()
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    audit.pop("_cand", None)
    evd = audit["evaluable_days"]
    assert evd["n_operating_days"] == 2  # day1 + day2 有 EV 能量（day3 actual 全 NaN → 0 能量）
    assert evd["n_evaluable_days"] == 2  # day1 + day2 都有 candidate table 行
    assert evd["n_non_evaluable_days"] == 0
    # median 来自 [day1_share>0, day2_share=0] → median 应含 0（case A 真实零进 median）
    assert audit["daily_energy_share_median"] is not None


def test_daily_energy_share_case_b_non_evaluable_excluded() -> None:
    """P0-2 case B：day3 无 valid paired cycles（actual 全 NaN）→ non-evaluable，
    不以 0 进入 median。day3 不计入 n_operating_days（EV 能量=0）也不计 n_evaluable_days。"""
    df = _three_day_minutes()
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    audit.pop("_cand", None)
    evd = audit["evaluable_days"]
    # day3 actual 全 NaN → EV 能量=0 → 不计 operating day；且无 candidate table 行 → non-evaluable
    assert "2018-11-03" not in str(audit.get("evaluable_days", {}))
    assert evd["n_operating_days"] == 2  # day1 + day2
    assert evd["n_evaluable_days"] == 2  # day1 + day2


def test_daily_energy_share_single_evaluable_day_nonzero() -> None:
    """单 evaluable day：share_median = 该日 share（非 0）。"""
    df = _synth_minutes("caltech", "California_Garage_01", pilot_kw=8.0)
    audit = pool_audit(df, "caltech.California_Garage_01", CALTECH_PROXIES, SEED, N_BOOT)
    audit.pop("_cand", None)
    assert audit["evaluable_days"]["n_operating_days"] == 1
    assert audit["evaluable_days"]["n_evaluable_days"] == 1
    assert audit["evaluable_days"]["n_non_evaluable_days"] == 0
    assert audit["daily_energy_share_median"] > 0.0
