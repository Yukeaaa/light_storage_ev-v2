"""E1 主口径统计（从 e1_lite/run.py 冻结逻辑抽取，供 Lite 复现与 R1 硬切分复现共用）。

R1（E0F-06 / #17）要求"严格 K1 冻结值，不改"。本模块把 E1-Lite run.py 中的
事件检测/阶段切断/核心运行段统计/负对照/失败案例抽取为纯函数；e1_full 与
e1_lite 必须调用同一份逻辑。种子、bootstrap 次数、阈值一律由调用方显式传入，
不做模块级魔法常数（Lite 历史值见 e1_lite/run.py；R1 冻结值见 e0_full.yaml）。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from patent_preexperiment.metrics.permutation import permutation_negative_control
from patent_preexperiment.response.done import (
    PHASE_CORE,
    PHASE_MISSING,
    PHASE_POST,
    PHASE_TAIL,
    add_done_phases,
    done_anchored_summary,
)
from patent_preexperiment.response.events import GapThresholds, detect_gap_events


def session_rate(events: pd.DataFrame, n_sessions: int) -> float:
    return events["session_id"].nunique() / max(n_sessions, 1)


def events_with_phase(labeled: pd.DataFrame, thr: GapThresholds) -> pd.DataFrame:
    """检测事件并在阶段边界切断；事件行携带 event_phase。"""
    ev = detect_gap_events(labeled, thr, phase_col="phase")
    if len(ev):
        ev["event_phase"] = ev["phase"].fillna(PHASE_MISSING)
    else:
        ev["event_phase"] = pd.Series(dtype=str)
    return ev


def process(
    df: pd.DataFrame, thr: GapThresholds,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """分类 → done 阶段 → 事件（阶段切断）；输出 labeled/events/session_summary。"""
    labeled = classify_add_done(df, thr)
    events = events_with_phase(labeled, thr)
    if len(events):
        anchor = labeled[["session_id", "timestamp_utc", "minutes_to_done"]].rename(
            columns={"timestamp_utc": "start_utc"}
        )
        events = events.merge(anchor, on=["session_id", "start_utc"], how="left")
        events["start_minutes_to_done"] = events["minutes_to_done"]
        events = events.drop(columns=["minutes_to_done"])
    else:
        events["start_minutes_to_done"] = pd.Series(dtype="float64")

    sess_energy = (
        labeled[labeled["charging_active"]]
        .groupby("session_id")
        .agg(charging_minutes=("timestamp_utc", "size"), work_energy_kwh=("actual_power_kw", "sum"))
        .reset_index()
    )
    ev_sess = (
        events.groupby("session_id")
        .agg(n_events=("start_utc", "size"), gap_energy_kwh=("gap_energy_kwh", "sum"),
             max_duration_min=("duration_min", "max"))
        .reset_index()
    )
    session_summary = sess_energy.merge(ev_sess, on="session_id", how="left").fillna(
        {"n_events": 0, "gap_energy_kwh": 0.0, "max_duration_min": 0}
    )
    session_summary["has_event"] = session_summary["n_events"] > 0
    return labeled, events, session_summary


def classify_add_done(df: pd.DataFrame, thr: GapThresholds) -> pd.DataFrame:
    from patent_preexperiment.response.events import classify

    return add_done_phases(classify(df, thr), thr.p_on_kw)


def core_stats(events: pd.DataFrame, labeled: pd.DataFrame, thr: GapThresholds) -> dict[str, Any]:
    """核心运行段（距 done>120min，阶段切断后）主口径统计。"""
    core = events[events["event_phase"] == PHASE_CORE]
    core_denom = labeled[
        (labeled["phase"] == PHASE_CORE) & labeled["charging_active"] & labeled["pilot_available"]
    ]["session_id"].nunique()
    rate = session_rate(core, core_denom) if core_denom else 0.0
    median_gap = float(core["median_gap_kw"].median()) if len(core) else 0.0
    median_work = float(core["working_power_median_kw"].median()) if len(core) else 0.0
    return {
        "denominator_sessions_with_core_run": core_denom,
        "n_events": int(len(core)),
        "n_event_sessions": int(core["session_id"].nunique()) if len(core) else 0,
        "event_session_rate": rate,
        "median_gap_kw": median_gap,
        "median_gap_ratio_of_working": median_gap / max(median_work, 1e-6),
        "total_gap_energy_kwh": float(core["gap_energy_kwh"].sum()) if len(core) else 0.0,
        "duration_p50_p95": {
            "p50": float(core["duration_min"].quantile(0.5)) if len(core) else None,
            "p95": float(core["duration_min"].quantile(0.95)) if len(core) else None,
        },
    }


def phase_summary(events: pd.DataFrame, labeled: pd.DataFrame) -> pd.DataFrame:
    """事件按 done-relative 阶段分布（阶段切断后，各阶段分别计数）。"""
    phases = list(labeled["phase"].dropna().unique())
    if not phases:
        cols = ["phase", "n_events", "n_event_sessions", "event_share", "energy_kwh"]
        return pd.DataFrame(columns=cols)
    rows: list[dict[str, Any]] = []
    for ph in phases:
        e = events[events["event_phase"] == ph]
        rows.append({
            "phase": ph,
            "n_events": int(len(e)),
            "n_event_sessions": int(e["session_id"].nunique()),
            "event_share": float(len(e)) / max(len(events), 1),
            "energy_kwh": float(e["gap_energy_kwh"].sum()),
        })
    order = {PHASE_POST: 0, PHASE_TAIL: 1, "pre_done_mid": 2, PHASE_CORE: 3, PHASE_MISSING: 4}
    return pd.DataFrame(rows).sort_values("phase", key=lambda s: s.map(order).fillna(9))


def negative_controls(
    labeled: pd.DataFrame,
    events: pd.DataFrame,
    thr: GapThresholds,
    session_summary: pd.DataFrame,
    core_events: pd.DataFrame,
    perm_seeds: list[int],
    bootstrap_seed: int,
    n_boot: int,
) -> dict[str, Any]:
    neg: dict[str, Any] = {}
    core = core_events

    # NC-done-1: 时间置换（会话内，仅核心运行段，阶段切断）——多种子 + 差值 bootstrap
    neg["time_permutation_core"] = permutation_negative_control(
        labeled, thr, core, perm_seeds=perm_seeds, bootstrap_seed=bootstrap_seed, n_boot=n_boot,
    )

    # NC-done-2: 事件是否集中于完成阶段（done-anchored 特征化，非门判定）
    anch = done_anchored_summary(events)
    anch["interpretation"] = (
        "特征化：响应差事件在 done 前 120 分钟内占多数（车辆满充/降流机制），post_done=0 "
        "排除'停车占位'伪影（事件要求 charging_active）。核心运行段事件独立满足停止线，"
        "问题在正常充电段仍成立；近完成段浓度在 E2 可执行区间生成中须单独建模。"
    )
    neg["done_anchored_events"] = anch

    # NC-done-3: 仅实测/计算功率子集（核心，阶段切断）
    sub = labeled[labeled["power_source"].isin(["measured", "computed"])].copy()
    sub = add_done_phases(sub, thr.p_on_kw)
    ev_meas = events_with_phase(sub, thr)
    meas_core = ev_meas[ev_meas["event_phase"] == PHASE_CORE]
    core_win = sub[(sub["phase"] == PHASE_CORE) & sub["charging_active"] & sub["pilot_available"]]
    meas_denom = core_win["session_id"].nunique()
    neg["measured_or_computed_only_core"] = {
        "core_events": int(len(meas_core)),
        "core_session_rate": session_rate(meas_core, meas_denom) if meas_denom else 0.0,
    }

    # NC-done-4: 排除短充电会话（<30 分钟）后核心率（阶段切断）
    short = session_summary[session_summary["charging_minutes"] < 30]["session_id"]
    long_df = labeled[~labeled["session_id"].isin(short)]
    ev_long = events_with_phase(long_df, thr)
    long_core = ev_long[ev_long["event_phase"] == PHASE_CORE]
    long_win = long_df[
        (long_df["phase"] == PHASE_CORE)
        & long_df["charging_active"] & long_df["pilot_available"]
    ]
    long_denom = long_win["session_id"].nunique()
    neg["exclude_short_sessions_lt30min_core"] = {
        "core_events": int(len(long_core)),
        "core_session_rate": session_rate(long_core, long_denom) if long_denom else 0.0,
    }

    # NC-done-5: 单桩/单月集中度（核心）
    if len(core):
        neg["max_single_station_share_core"] = float(
            core.groupby("station_id")["start_utc"].count().max() / max(len(core), 1)
        )
        neg["max_single_month_share_core"] = float(
            core.groupby("month")["start_utc"].count().max() / max(len(core), 1)
        )
        neg["n_stations_with_core_events"] = int(core["station_id"].nunique())
    else:
        neg["max_single_station_share_core"] = 0.0
        neg["max_single_month_share_core"] = 0.0
        neg["n_stations_with_core_events"] = 0

    # NC-done-6: 距断开时间分布（原解释口径，供对照）
    if "minutes_from_disconnect_at_start" in events:
        mfe = events["minutes_from_disconnect_at_start"].dropna()
    else:
        mfe = pd.Series(dtype="float64")
    neg["minutes_from_disconnect_at_start"] = {
        "p25": float(mfe.quantile(0.25)) if len(mfe) else None,
        "p50": float(mfe.quantile(0.5)) if len(mfe) else None,
        "p75": float(mfe.quantile(0.75)) if len(mfe) else None,
    }

    # done 锚点覆盖率（按会话数）
    anch = labeled.groupby("session_id")["done_anchor_source"].first().value_counts()
    n_sess = len(labeled["session_id"].unique())
    neg["done_anchor_coverage_by_session"] = {
        "api": int(anch.get("api", 0)),
        "inferred": int(anch.get("inferred", 0)),
        "missing": int(anch.get("missing", 0)),
        "n_sessions": n_sess,
        "api_share": float(anch.get("api", 0)) / max(n_sess, 1),
        "inferred_share": float(anch.get("inferred", 0)) / max(n_sess, 1),
    }
    return neg


def build_fail_cases(
    events: pd.DataFrame, ev_perm_core: pd.DataFrame, session_summary: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    core = events[events["event_phase"] == PHASE_CORE]
    if len(core):
        top = core.nlargest(20, "duration_min")
        for _, e in top.iterrows():
            perm_hit = ev_perm_core["session_id"] == e["session_id"]
            survived = bool(len(ev_perm_core) and perm_hit.any())
            rows.append({**e.to_dict(), "fail_type": "largest_core_event",
                         "permutation_survived": survived})
    no_ev = session_summary[session_summary["has_event"] == False]  # noqa: E712
    no_ev = no_ev.sort_values("charging_minutes", ascending=False).head(20)
    for _, s in no_ev.iterrows():
        rows.append({"session_id": s["session_id"], "fail_type": "no_event_long_charging",
                     "charging_minutes": int(s["charging_minutes"]), "n_events": 0})
    return pd.DataFrame(rows)
