"""P1 特征冻结实现（Phase 3 v1.0.2 §1.5 step 2/4）。

recent_var 必须与 A5 完全相同（run_a5.py::_cycle_observables，Batch_2.1 X3 冻结实现），
协议明确"不重新发明、不重拟合"；本模块是 P1 冻结复用，不改动 E0-Full/A5 已冻结逻辑。

观测单位 = office001×cycle（5-min）；recent_var = 该 cycle 内各会话
recent_actual_var 的中位数（与 A5 obs 层 median_recent_actual_var 同口径）。
E1 event-start cycle snapshot：core_run_segment 事件 start_utc floor 到 5-min。
"""

from __future__ import annotations

import pandas as pd

MIN_CYCLE_MIN = 5
RECENT_WINDOW = 12
MIN_RECENT_SAMPLES = 2

_OBSERVABLE_COLUMNS = [
    "session_id",
    "site",
    "timestamp_utc",
    "actual_power_kw",
    "pilot_power_kw",
    "connected_elapsed_min",
    "severe_gap_before",
]


def cycle_observables(tm: pd.DataFrame) -> pd.DataFrame:
    """office001 分钟表 → site×cycle 级在线可观测量（A5 同源冻结实现）。

    复制自 run_a5.py::_cycle_observables（Batch_2.1 X3 冻结），recent_actual_var 的
    滚动窗口（12）、min_periods（2）、shift(1)、run 断裂 / cycle-gap>5min /
    severe_gap_at_start 重置规则一字不改；仅裁剪输出到 P1 需要的列。
    """
    tm = tm.copy()
    tm["cycle"] = tm["timestamp_utc"].dt.floor("5min")
    tm["active"] = (tm["actual_power_kw"] >= 0.5).astype(float)
    tm["has_pilot"] = tm["pilot_power_kw"].notna().astype(float)
    tm = tm.sort_values(["site", "session_id", "timestamp_utc"], kind="stable")
    sess_cycle = tm.groupby(
        ["site", "session_id", "cycle"], sort=False
    ).agg(
        actual_mean=("actual_power_kw", "mean"),
        pilot_mean=("pilot_power_kw", "mean"),
        pilot_available_first=("has_pilot", "first"),
        elapsed_min=("connected_elapsed_min", "min"),
        severe_gap_at_start=("severe_gap_before", "first"),
        severe_gap_any=("severe_gap_before", "max"),
        n_active_min=("active", "sum"),
    ).reset_index()
    sess_cycle = sess_cycle.sort_values(["session_id", "cycle"])
    sess_cycle["_gap"] = sess_cycle["actual_mean"].isna()
    sess_cycle["_prev_cycle"] = sess_cycle.groupby(
        "session_id", sort=False
    )["cycle"].shift(1)
    sess_cycle["_cycle_gap"] = (
        sess_cycle["cycle"] - sess_cycle["_prev_cycle"]
    ).dt.total_seconds() / 60.0
    sess_cycle["_break"] = (
        sess_cycle["_gap"].fillna(True)
        | (sess_cycle["_cycle_gap"] > 5.0).fillna(True)
        | sess_cycle["severe_gap_at_start"].fillna(True)
    )
    sess_cycle["_run"] = sess_cycle.groupby(
        "session_id", sort=False
    )["_break"].cumsum()
    run_key = ["session_id", "_run"]
    sess_cycle["recent_actual_var"] = sess_cycle.groupby(
        run_key, sort=False
    )["actual_mean"].transform(
        lambda s: s.shift(1).rolling(RECENT_WINDOW, min_periods=MIN_RECENT_SAMPLES).var()
    )
    obs = sess_cycle.groupby(["site", "cycle"], sort=False).agg(
        median_recent_actual_var=("recent_actual_var", "median"),
        history_coverage=("recent_actual_var", lambda s: float(s.notna().mean())),
        n_sessions=("session_id", "nunique"),
    ).reset_index()
    return obs


def e1_event_start_cycles(
    core_events: pd.DataFrame,
) -> set[tuple[str, pd.Timestamp]]:
    """E1 core event start_utc → 5-min cycle（与 A5 s1_cycles 同口径，去重）。"""
    if len(core_events) == 0:
        return set()
    floor = core_events["start_utc"].dt.floor("5min")
    return set(zip(core_events["site"], floor, strict=False))
