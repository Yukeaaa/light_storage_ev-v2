"""E1-Lite 运行器（V2.1 §6；K1 冻结样本角色 2026-08-06）。

- 主集：caltech.CG1（独立推断，承载门判断）
- 外部边界：jpl.Arroyo 2020-06/07（只评估不调参，方向一致性参考）
- 负对照 + 失败案例 + 距断开时间分布（解释 NC1）
- current_only_fallback 独立于本脚本（build_boundary.py）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.response.events import GapThresholds, classify, detect_gap_events

REPO = Path(__file__).resolve().parents[3]  # 仓库根
IMPL = REPO / "patent_preexperiment"
MINUTE_TABLE = IMPL / "datasets" / "lite_session_minute.parquet"
BOUNDARY_TABLE = IMPL / "datasets" / "lite_jpl_boundary_minute.parquet"
REGISTRY = IMPL / "data_registry" / "k1_sample_registry.csv"
OUT = IMPL / "results" / "raw" / "E1L"
SEED = 42


def _session_rate(events: pd.DataFrame, n_sessions: int) -> float:
    return events["session_id"].nunique() / max(n_sessions, 1)


def _load_main(cfg: dict) -> pd.DataFrame:
    df = pd.read_parquet(MINUTE_TABLE)
    df["month_data"] = df["timestamp_utc"].astype(str).str[:7]
    reg = pd.read_csv(REGISTRY, dtype=str)
    df = df.merge(reg[["sessionID", "connection_time"]].rename(columns={"sessionID": "session_id"}),
                  on="session_id", how="left")
    df["month_connected"] = df["connection_time"].str[:7]
    pilot_sess = df[df["pilot_available"]]["session_id"].unique()
    return df[df["session_id"].isin(pilot_sess)].copy()


def _load_boundary() -> pd.DataFrame:
    df = pd.read_parquet(BOUNDARY_TABLE)
    df["month_data"] = df["timestamp_utc"].astype(str).str[:7]
    df["month_connected"] = df["month_data"]
    return df


def _process(df: pd.DataFrame, thr: GapThresholds) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    labeled = classify(df, thr)
    events = detect_gap_events(labeled, thr)
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


def run_e1_lite() -> dict:
    cfg = load_yaml(IMPL / "configs" / "k1_preregister.yaml")
    thr = GapThresholds.from_cfg(cfg)
    OUT.mkdir(parents=True, exist_ok=True)

    # ---------- 主集 caltech ----------
    main_df = _load_main(cfg)
    labeled, events, session_summary = _process(main_df, thr)
    n_valid = labeled["session_id"].nunique()
    rate = _session_rate(events, n_valid)

    # 距断开时间分布（解释 NC1：事件是否锚定尾段）
    mfe = events.merge(
        labeled[["session_id", "timestamp_utc", "minutes_from_end"]],
        left_on=["session_id", "start_utc"], right_on=["session_id", "timestamp_utc"], how="left",
    )
    events["minutes_from_disconnect_at_start"] = mfe["minutes_from_end"].values

    session_summary.to_csv(OUT / "e1_lite_session_summary.csv", index=False)
    pool_month = (
        events.groupby(["site", "garage", "month"])
        .agg(n_events=("start_utc", "size"), n_event_sessions=("session_id", "nunique"),
             total_gap_energy_kwh=("gap_energy_kwh", "sum"),
             median_duration_min=("duration_min", "median"))
        .reset_index()
    )
    pool_month.to_csv(OUT / "e1_lite_pool_month_summary.csv", index=False)

    # ---------- 负对照 ----------
    neg = _run_negative_controls(labeled, events, thr, n_valid, session_summary)

    fail_cases = _build_fail_cases(events, neg["perm_events"], session_summary)
    fail_cases.to_csv(OUT / "e1_lite_fail_cases.csv", index=False)
    events.to_parquet(OUT / "e1_lite_event_table.parquet", index=False)

    stop = cfg["k1_stop_lines"]["e1"]
    median_gap = float(events["median_gap_kw"].median()) if len(events) else 0.0
    median_work = float(events["working_power_median_kw"].median()) if len(events) else 0.0
    gap_ratio = median_gap / max(median_work, 1e-6)
    n_months_connected = int(labeled["month_connected"].nunique())
    n_months_data = int(labeled["month_data"].nunique())

    gates = {
        "n_pools": labeled[["site", "garage"]].drop_duplicates().shape[0],
        "n_months_connected": n_months_connected,
        "n_months_data": n_months_data,
        "n_sessions": n_valid,
        "event_session_rate": rate,
        "median_gap_kw": median_gap,
        "median_gap_ratio_of_working": gap_ratio,
        "pass_min_months": n_months_connected >= stop["min_normal_months"],
        "pass_min_sessions": n_valid >= stop["min_sessions"],
        "pass_rate": rate >= stop["min_event_session_rate"],
        "pass_median": median_gap >= stop["min_median_gap_kw"] or gap_ratio >= stop["min_median_gap_ratio"],
        "pass_single_station": neg["max_single_station_share"] <= stop["max_single_station_share"],
        "pass_neg_controls": neg["time_permutation"]["session_rate"] < rate,
    }

    # ---------- 外部边界 jpl（只评估不调参） ----------
    boundary = _evaluate_boundary(thr)
    neg_summary = {k: v for k, v in neg.items() if k != "perm_events"}
    boundary_dir = (
        boundary["event_session_rate"] >= stop["min_event_session_rate"]
        and (boundary["median_gap_kw"] >= stop["min_median_gap_kw"]
             or boundary["median_gap_ratio_of_working"] >= stop["min_median_gap_ratio"])
    )
    gates["pass_two_pool_repetition"] = bool(
        all(gates[k] for k in ("pass_min_months", "pass_min_sessions", "pass_rate", "pass_median",
                               "pass_single_station", "pass_neg_controls"))
        and boundary_dir
    )
    mfe = events["minutes_from_disconnect_at_start"].dropna()
    mfe_stats = {
        "p25": float(mfe.quantile(0.25)) if len(mfe) else None,
        "p50": float(mfe.quantile(0.5)) if len(mfe) else None,
        "p75": float(mfe.quantile(0.75)) if len(mfe) else None,
        "share_within_30min_of_disconnect": float((mfe <= 30).mean()) if len(mfe) else None,
    }

    summary = {
        "threshold": {k: getattr(thr, k) for k in ("p_on_kw", "delta_r", "delta_p_kw", "t_event_min",
                                                   "initial_exclusion_min", "tail_exclusion_min", "pilot_active_min_a")},
        "roles": "main=caltech.CG1 / external_boundary=jpl 2020-06,07 / current_only_fallback=独立(见 build_boundary.py)",
        "main_set": {
            "n_valid_sessions": n_valid,
            "n_charging_sessions": int(labeled[labeled["charging_active"]]["session_id"].nunique()),
            "n_events": int(len(events)),
            "n_event_sessions": int(events["session_id"].nunique()),
            "event_session_rate": rate,
            "n_pools": gates["n_pools"],
            "n_months_connected": n_months_connected,
            "n_months_data": n_months_data,
            "event_duration_p50_p75_p95": {
                "p50": float(events["duration_min"].quantile(0.5)) if len(events) else None,
                "p75": float(events["duration_min"].quantile(0.75)) if len(events) else None,
                "p95": float(events["duration_min"].quantile(0.95)) if len(events) else None,
                "max": int(events["duration_min"].max()) if len(events) else None,
            },
            "gap_kw_p50_p95": {
                "p50": float(events["median_gap_kw"].quantile(0.5)) if len(events) else None,
                "p95": float(events["median_gap_kw"].quantile(0.95)) if len(events) else None,
            },
            "total_gap_energy_kwh": float(events["gap_energy_kwh"].sum()),
            "mfe_at_start_min": mfe_stats,
        },
        "external_boundary": boundary,
        "negative_controls": neg_summary,
        "gates": gates,
        "gates_interpretation": (
            "Go：主集门全过且边界方向一致；条件Go：主集门过但边界方向不一致；No-Go：主集门不过"
        ),
    }
    (OUT / "e1_lite_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def _run_negative_controls(
    labeled: pd.DataFrame, events: pd.DataFrame, thr: GapThresholds,
    n_valid: int, session_summary: pd.DataFrame,
) -> dict:
    neg: dict = {}
    # NC1: 尾段完全排除（tail=10000）——把"有效区"全标尾段后仅剩缺 disconnect 的会话事件
    thr_tail = GapThresholds(thr.p_on_kw, thr.delta_r, thr.delta_p_kw, thr.t_event_min,
                             thr.initial_exclusion_min, 10_000, thr.pilot_active_min_a)
    ev_tail = detect_gap_events(labeled, thr_tail)
    neg["tail_fully_excluded"] = {
        "events": len(ev_tail),
        "session_rate": _session_rate(ev_tail, n_valid),
        "interpretation": "事件几乎全部集中在距断开<10^4分钟区（正常会话距断开<1000分钟）→ 事件依赖尾段锚定；"
                          "主口径已用 tail=10 排除末段，NC1 不提供额外区分力，改由 mfe 分布与 tail 敏感性解释",
    }
    # NC1b: tail 敏感性 tail∈{5,15}（V2.0 §4.3 网格，非调参）
    neg["tail_sensitivity"] = {}
    for tl in (5, 15):
        thr_t = GapThresholds(thr.p_on_kw, thr.delta_r, thr.delta_p_kw, thr.t_event_min,
                              thr.initial_exclusion_min, tl, thr.pilot_active_min_a)
        ev_t = detect_gap_events(labeled, thr_t)
        neg["tail_sensitivity"][f"tail_{tl}"] = {
            "events": len(ev_t), "session_rate": _session_rate(ev_t, n_valid)
        }
    # NC2: 会话内时间置换（固定种子）
    rng = np.random.default_rng(SEED)
    perm = labeled.copy()
    perm["actual_power_kw"] = perm.groupby("session_id", group_keys=False)["actual_power_kw"].apply(
        lambda s: pd.Series(rng.permutation(s.values), index=s.index)
    )
    ev_perm = detect_gap_events(perm, thr)
    neg["time_permutation"] = {"events": len(ev_perm), "session_rate": _session_rate(ev_perm, n_valid)}
    # NC3: 仅实测/计算功率子集
    sub = labeled[labeled["power_source"].isin(["measured", "computed"])].copy()
    ev_meas = detect_gap_events(sub, thr)
    neg["measured_or_computed_only"] = {"events": len(ev_meas), "session_rate": _session_rate(ev_meas, n_valid)}
    # NC4: 排除短会话（充电分钟<30）
    short = session_summary[session_summary["charging_minutes"] < 30]["session_id"]
    ev_long = detect_gap_events(labeled[~labeled["session_id"].isin(short)], thr)
    neg["exclude_short_sessions_lt30min"] = {"events": len(ev_long), "session_rate": _session_rate(ev_long, n_valid)}
    # NC5: station/月集中度
    station_share = events.groupby("station_id")["start_utc"].count().max() / max(len(events), 1)
    month_share = events.groupby("month")["start_utc"].count().max() / max(len(events), 1)
    neg["max_single_station_share"] = float(station_share)
    neg["max_single_month_share"] = float(month_share)
    neg["n_stations_with_events"] = int(events["station_id"].nunique())
    neg["jpl_energy_outlier_filter"] = "deferred_to_E0_Full"
    neg["perm_events"] = ev_perm
    neg_df = pd.DataFrame([{"control": k, "value": json.dumps(v, ensure_ascii=False, default=str)} for k, v in neg.items() if k != "perm_events"])
    neg_df.to_csv(OUT / "e1_lite_negative_controls.csv", index=False)
    return neg


def _evaluate_boundary(thr: GapThresholds) -> dict:
    df = _load_boundary()
    labeled, events, _ = _process(df, thr)
    n = labeled["session_id"].nunique()
    rate = _session_rate(events, n)
    median_gap = float(events["median_gap_kw"].median()) if len(events) else 0.0
    median_work = float(events["working_power_median_kw"].median()) if len(events) else 0.0
    return {
        "role": "external_boundary_only_no_tuning",
        "pool": "jpl.Arroyo 2020-06,07",
        "n_valid_sessions": n,
        "n_events": int(len(events)),
        "event_session_rate": rate,
        "median_gap_kw": median_gap,
        "median_gap_ratio_of_working": median_gap / max(median_work, 1e-6),
        "total_gap_energy_kwh": float(events["gap_energy_kwh"].sum()),
        "total_gap_energy_share_of_ev_kwh": None,  # 边界无站级能量基，E0-Full 补
    }


def _build_fail_cases(events: pd.DataFrame, ev_perm: pd.DataFrame, session_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    if len(events):
        top = events.nlargest(20, "duration_min")
        for _, e in top.iterrows():
            survived = bool(len(ev_perm) and (ev_perm["session_id"] == e["session_id"]).any())
            rows.append({**e.to_dict(), "fail_type": "largest_event", "permutation_survived": survived})
    no_ev = session_summary[session_summary["has_event"] == False].sort_values("charging_minutes", ascending=False).head(20)  # noqa: E712
    for _, s in no_ev.iterrows():
        rows.append({"session_id": s["session_id"], "fail_type": "no_event_long_charging",
                     "charging_minutes": int(s["charging_minutes"]), "n_events": 0})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    sys.exit(0 if run_e1_lite() else 1)
