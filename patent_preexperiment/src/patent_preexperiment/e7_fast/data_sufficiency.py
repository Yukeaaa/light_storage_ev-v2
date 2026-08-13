"""D0 数据充分性门（review §4-7）。

D0-1：信息类别覆盖审计（review §4）——按 site/station/month/field_mode/info_mode/split 统计
       cycle 数、session 数，并汇总 station 数、月份数、占有效充电时间比例。
D0-2：自然 pilot step 事件库的充分性判定（review §7）——三级门（A/B/C），不用 formal bootstrap。
       gate 主判集 = train+validation（拟合集）；test 报告 single-exposure 可用量；
       office001 external 单列不计入 gate；stress 不计入 gate。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from patent_preexperiment.e7_fast.config import E7FastConfig

_GATE_SPLITS = ("train", "validation")  # gate 主判集（拟合集）


@dataclass(frozen=True)
class GateVerdict:
    level: str                   # A_level / B_level / C_level
    verdict: str                 # GO_active_increase / CONDITIONAL_... / NO_INDEPENDENT_CLAIM_...
    positive_events: int
    positive_sessions: int
    positive_stations: int
    positive_months: int
    negative_events: int
    negative_sessions: int
    negative_stations: int
    negative_sufficient: bool
    test_positive_events: int    # single-exposure 可用量（报告，不入 gate）
    external_positive_events: int
    reason: str


@dataclass
class D0Result:
    info_coverage_detail: pd.DataFrame
    info_coverage_summary: pd.DataFrame
    events: pd.DataFrame
    verdict: GateVerdict
    extras: dict[str, Any] = field(default_factory=dict)


def compute_info_coverage(df_info: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """D0-1 信息类别覆盖审计。

    返回 (detail, summary)：
    - detail：[site, station_id, month, field_mode, info_mode, split] × {cycle_count, session_count}
    - summary：[site, info_mode, split] × {cycle_count, session_count, station_count, month_count,
              share_of_active_min}
    """
    if df_info.empty:
        empty_detail = pd.DataFrame(
            columns=["site", "station_id", "month", "field_mode", "info_mode", "split",
                     "cycle_count", "session_count"]
        )
        empty_summary = pd.DataFrame(
            columns=["site", "info_mode", "split", "cycle_count", "session_count",
                     "station_count", "month_count", "share_of_active_min"]
        )
        return empty_detail, empty_summary

    df = df_info.copy()
    df["month"] = df["timestamp_utc"].dt.strftime("%Y-%m")

    detail = (
        df.groupby(
            ["site", "station_id", "month", "field_mode", "info_mode", "split"],
            observed=True,
        )
        .agg(cycle_count=("timestamp_utc", "size"), session_count=("session_id", "nunique"))
        .reset_index()
        .sort_values(["site", "field_mode", "info_mode", "month", "station_id", "split"])
    )

    summary = (
        df.groupby(["site", "info_mode", "split"], observed=True)
        .agg(
            cycle_count=("timestamp_utc", "size"),
            session_count=("session_id", "nunique"),
            station_count=("station_id", "nunique"),
            month_count=("month", "nunique"),
        )
        .reset_index()
    )
    site_total = summary.groupby("site")["cycle_count"].transform("sum")
    summary["share_of_active_min"] = (summary["cycle_count"] / site_total).round(4)
    summary = summary.sort_values(["site", "info_mode", "split"])
    return detail, summary


def _count_events(events: pd.DataFrame, direction: str) -> tuple[int, int, int, int]:
    sub = events[events["direction"] == direction]
    if sub.empty:
        return 0, 0, 0, 0
    return (
        int(len(sub)),
        int(sub["session_id"].nunique()),
        int(sub["station_id"].nunique()),
        int(sub["month"].nunique()),
    )


def evaluate_sufficiency_gate(
    events: pd.DataFrame, cfg: E7FastConfig
) -> GateVerdict:
    """D0-2 充分性门判定（review §7 三级门）。"""
    pg = cfg.d0.positive_gate
    ng = cfg.d0.negative_gate
    external_only = set(cfg.split.external_only)

    gate_mask = events["split"].isin(_GATE_SPLITS) & ~events["site"].isin(external_only)
    gate_events = events[gate_mask]
    test_events = events[events["split"] == "test"]
    ext_events = events[events["site"].isin(external_only)]

    p_ev, p_sess, p_stn, p_mon = _count_events(gate_events, "up")
    n_ev, n_sess, n_stn, _mon = _count_events(gate_events, "down")
    test_p_ev = int(len(test_events[test_events["direction"] == "up"]))
    ext_p_ev = int(len(ext_events[ext_events["direction"] == "up"]))

    neg_sufficient = (
        n_ev >= ng.events_min
        and n_sess >= ng.sessions_min
        and n_stn >= ng.stations_min
    )

    if p_ev < pg.c_max + 1:  # < 30 → C
        level, verdict, reason = "C_level", "NO_INDEPENDENT_CLAIM_active_increase", (
            f"正 pilot 上调事件 {p_ev} < {pg.c_max + 1}；独立权利要求不主张"
            "基于历史主动增加 EV 功率，"
            "只保留明确 capability 时增加 / 信息不足时限制增加 / 降低或保持。"
        )
    elif (
        p_ev >= pg.a_events
        and p_sess >= pg.a_sessions
        and p_stn >= pg.a_stations
        and p_mon >= pg.a_months
    ):
        level, verdict, reason = "A_level", "GO_active_increase", (
            f"正 pilot 上调事件 {p_ev}>={pg.a_events}、"
            f"sessions {p_sess}>={pg.a_sessions}、"
            f"stations {p_stn}>={pg.a_stations}、"
            f"months {p_mon}>={pg.a_months}；足以支持主动增加功率实验。"
        )
    else:
        level, verdict, reason = "B_level", "CONDITIONAL_active_increase_only_as_dependent", (
            f"正 pilot 上调事件 {p_ev}（B 级 {pg.b_low}-{pg.b_high}）或集中在少数桩/月"
            f"（stations={p_stn}, months={p_mon}）；“允许提高 EV 功率”只能写成条件实施方式。"
        )

    return GateVerdict(
        level=level,
        verdict=verdict,
        positive_events=p_ev,
        positive_sessions=p_sess,
        positive_stations=p_stn,
        positive_months=p_mon,
        negative_events=n_ev,
        negative_sessions=n_sess,
        negative_stations=n_stn,
        negative_sufficient=neg_sufficient,
        test_positive_events=test_p_ev,
        external_positive_events=ext_p_ev,
        reason=reason,
    )
