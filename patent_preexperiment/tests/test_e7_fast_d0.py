"""E7-FAST D0 单元测试：信息类别判定 / pilot step 事件检测 / 充分性门。

用合成 1-min 会话验证逻辑正确性（不依赖外部数据）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patent_preexperiment.e7_fast.config import load_e7_fast_config
from patent_preexperiment.e7_fast.data_sufficiency import (
    compute_info_coverage,
    evaluate_sufficiency_gate,
)
from patent_preexperiment.e7_fast.info_class import attach_info_class, info_mode_of
from patent_preexperiment.e7_fast.pilot_steps import extract_pilot_step_events
from patent_preexperiment.phase3_p2.schema import M2, M3, M4

_CFG = load_e7_fast_config()


def _make_session(
    sid: str,
    pilot_a_seq: list[float],
    actual_seq: list[float],
    *,
    site: str = "caltech",
    split: str = "train",
    station: str = "CA-01",
    severe_gap: list[bool] | None = None,
    done_offset_min: float | None = None,
) -> pd.DataFrame:
    n = len(pilot_a_seq)
    t0 = pd.Timestamp("2020-06-01 00:00:00", tz="UTC")
    ts = [t0 + pd.Timedelta(minutes=i) for i in range(n)]
    rated_v = 240.0
    df = pd.DataFrame({
        "session_id": sid,
        "station_id": station,
        "site": site,
        "garage": "California_Garage_01",
        "split": split,
        "field_mode": "measured_pilot",
        "timestamp_utc": ts,
        "connected_elapsed_min": [i - 0.5 for i in range(n)],
        "done_charging_time": (
            t0 + pd.Timedelta(minutes=done_offset_min) if done_offset_min is not None else pd.NaT
        ),
        "actual_power_kw": actual_seq,
        "pilot_a": pilot_a_seq,
        "pilot_power_kw": [p * rated_v / 1000.0 for p in pilot_a_seq],
        "pilot_available": [not (pd.isna(p)) for p in pilot_a_seq],
        "severe_gap_before": severe_gap if severe_gap is not None else [False] * n,
        "gap_before_min": [np.nan] + [1.0] * (n - 1),
    })
    return df


def _stable_pilot_actual(n_pre: int, pilot: float, actual: float) -> tuple[list, list]:
    return [pilot] * n_pre, [actual] * n_pre


def test_info_mode_lookup():
    # capability 恒 False（ACN 无真实 capability）
    assert info_mode_of(False, True, True, True, _CFG) == M2
    assert info_mode_of(False, False, True, True, _CFG) == M3
    assert info_mode_of(False, True, True, False, _CFG) == M4
    assert info_mode_of(False, False, True, False, _CFG) == M4
    assert info_mode_of(False, False, False, False, _CFG) == M4


def test_attach_info_class_history_sufficient():
    # 10 分钟连续 actual+pilot；前 5 分钟 history 不足 → M4，第 6 分钟起 → M2
    pilot, actual = _stable_pilot_actual(10, 16.0, 4.0)
    df = _make_session("s1", pilot, actual)
    out = attach_info_class(df, _CFG)
    assert "info_mode" in out.columns
    assert "q95_history_kw" in out.columns
    # cycle 0..4: history_count < 5 → M4；cycle 5..: M2
    early = out.iloc[:5]["info_mode"]
    late = out.iloc[5:]["info_mode"]
    assert (early == M4).all(), early.tolist()
    assert (late == M2).all(), late.tolist()


def test_pilot_step_positive_event():
    # minute 10: pilot 16→32（Δ=16A, ratio=100%）；actual 响应 4→6
    pilot_pre, actual_pre = _stable_pilot_actual(10, 16.0, 4.0)
    pilot = pilot_pre + [32.0] * 10
    actual = actual_pre + [4.0, 5.0, 4.8, 5.5, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0]
    df = _make_session("pos1", pilot, actual)
    df_info = attach_info_class(df, _CFG)
    events = extract_pilot_step_events(df_info, _CFG)
    assert len(events) == 1
    ev = events.iloc[0]
    assert ev["direction"] == "up"
    assert ev["pilot_before_a"] == 16.0
    assert ev["pilot_after_a"] == 32.0
    assert ev["delta_pilot_a"] == 16.0
    assert ev["actual_before_kw"] == 4.0
    # actual_5min = minute 15 actual = 6.0
    assert ev["actual_5min_kw"] == 6.0
    assert ev["delta_actual_5min_kw"] == pytest.approx(2.0)
    assert ev["info_mode_before"] == M2


def test_pilot_step_negative_event():
    # minute 10: pilot 32→16（Δ=-16A）；actual 6→4
    pilot_pre, actual_pre = _stable_pilot_actual(10, 32.0, 6.0)
    pilot = pilot_pre + [16.0] * 10
    actual = actual_pre + [6.0, 5.0, 5.2, 4.5, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0]
    df = _make_session("neg1", pilot, actual)
    df_info = attach_info_class(df, _CFG)
    events = extract_pilot_step_events(df_info, _CFG)
    assert len(events) == 1
    assert events.iloc[0]["direction"] == "down"
    assert events.iloc[0]["delta_pilot_a"] == -16.0


def test_pilot_step_excluded_first_5min():
    # step at minute 3（connected_elapsed_min=2.5 < 5）→ 排除
    pilot_pre, actual_pre = _stable_pilot_actual(3, 16.0, 4.0)
    pilot = pilot_pre + [32.0] * 10
    actual = actual_pre + [4.0, 5.0, 4.8, 5.5, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0]
    df = _make_session("early1", pilot, actual)
    df_info = attach_info_class(df, _CFG)
    events = extract_pilot_step_events(df_info, _CFG)
    assert len(events) == 0


def test_pilot_step_excluded_severe_gap():
    # severe_gap_before=True at minute 12 → 后置窗断裂 → 排除
    pilot_pre, actual_pre = _stable_pilot_actual(10, 16.0, 4.0)
    pilot = pilot_pre + [32.0] * 10
    actual = actual_pre + [4.0, 5.0, 4.8, 5.5, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0]
    severe = [False] * 12 + [True] + [False] * 7
    df = _make_session("gap1", pilot, actual, severe_gap=severe)
    df_info = attach_info_class(df, _CFG)
    events = extract_pilot_step_events(df_info, _CFG)
    assert len(events) == 0


def test_pilot_step_excluded_near_done_charging():
    # done_charging_time 距事件 < 10min → 排除（离线标签）
    pilot_pre, actual_pre = _stable_pilot_actual(10, 16.0, 4.0)
    pilot = pilot_pre + [32.0] * 10
    actual = actual_pre + [4.0, 5.0, 4.8, 5.5, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0]
    # 事件在 minute 10，距 done 5min < 10min 阈值 → 排除
    df = _make_session("done1", pilot, actual, done_offset_min=15.0)
    df_info = attach_info_class(df, _CFG)
    events = extract_pilot_step_events(df_info, _CFG)
    assert len(events) == 0


def test_pilot_step_excluded_pre_instability():
    # 前置窗内 pilot 有第二次变化（minute 8: 16→17，Δ=1A<2A 非事件但 |Δ|=1.0 不 <1.0）
    # → minute 10 的 step 前置不稳定 → 排除；minute 8/9 Δ<2A 也不构成事件
    pilot = [16.0] * 8 + [17.0] + [16.0] + [32.0] * 10
    actual = [4.0] * 10 + [4.0, 5.0, 4.8, 5.5, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0]
    df = _make_session("inst1", pilot, actual)
    df_info = attach_info_class(df, _CFG)
    events = extract_pilot_step_events(df_info, _CFG)
    assert len(events) == 0


def test_pilot_step_small_change_not_event():
    # Δpilot=1A < 2A 阈值 → 不构成事件
    pilot_pre, actual_pre = _stable_pilot_actual(10, 16.0, 4.0)
    pilot = pilot_pre + [17.0] * 10  # Δ=1A
    actual = actual_pre + [4.0] * 10
    df = _make_session("small1", pilot, actual)
    df_info = attach_info_class(df, _CFG)
    events = extract_pilot_step_events(df_info, _CFG)
    assert len(events) == 0


def test_sufficiency_gate_levels():
    base_cols = ["event_id", "session_id", "station_id", "site", "timestamp", "direction",
                 "split", "month"]

    def _ev(n: int, stations: int, months: int, direction: str = "up") -> pd.DataFrame:
        rows = []
        for i in range(n):
            stn = f"st{i % max(stations, 1)}"
            mon = f"2020-{(i % max(months, 1)) + 1:02d}"
            rows.append({
                "event_id": f"e{i}", "session_id": f"s{i}", "station_id": stn,
                "site": "caltech", "timestamp": pd.Timestamp("2020-06-01", tz="UTC"),
                "direction": direction, "split": "train", "month": mon,
            })
        return pd.DataFrame(rows, columns=base_cols + ["pilot_before_kw", "pilot_after_kw"])

    # A 级：150 events, 150 sessions, 6 stations, 6 months
    evs_a = _ev(150, 6, 6)
    v = evaluate_sufficiency_gate(evs_a, _CFG)
    assert v.level == "A_level", v.reason
    assert v.positive_events == 150

    # C 级：20 events
    evs_c = _ev(20, 2, 1)
    v = evaluate_sufficiency_gate(evs_c, _CFG)
    assert v.level == "C_level"
    assert v.verdict == "NO_INDEPENDENT_CLAIM_active_increase"

    # B 级：60 events，但 stations=2 (<5) → 集中 → B
    evs_b = _ev(60, 2, 2)
    v = evaluate_sufficiency_gate(evs_b, _CFG)
    assert v.level == "B_level"


def test_compute_info_coverage():
    pilot, actual = _stable_pilot_actual(10, 16.0, 4.0)
    df = _make_session("cov1", pilot, actual)
    df_info = attach_info_class(df, _CFG)
    detail, summary = compute_info_coverage(df_info)
    assert "info_mode" in detail.columns
    assert "cycle_count" in detail.columns
    assert len(summary) > 0
    assert "share_of_active_min" in summary.columns
