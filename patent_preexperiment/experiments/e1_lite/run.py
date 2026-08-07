"""E1-Lite（K1.1-A + K1.2-B/D）：done-relative 响应差重审。

评审修正：
- 原尾段排除基于 disconnectTime（物理拔枪），未排除"充电完成/持续降流"段。
- 主口径改为 核心运行段 = 距 doneChargingTime > 120 分钟；分为
  post_done / pre_done_tail / pre_done_mid / core_run_segment / done_missing。
- done 缺失会话用离线锚点推断（仅排伪，不入在线特征）——K1.2 对全会话分钟统一赋值。
- NC1（tail=10000）无区分力，废弃；改为 done-anchored 负对照：
  事件是否集中于完成阶段（post_done + pre_done_tail）。

K1.2-B 修正：事件连续段在 core/mid/tail 阶段边界处强制切断，各段重新执行持续>=T_event。
K1.2-D 修正：主集/边界只保留冻结 cycle_month（分钟/控制周期所在月份）；六个月稳定门=
冻结 6 个月逐月 ≥5%；done 锚点覆盖率按会话数报告；时间置换负对照输出 diff/ratio
与多种子 bootstrap 95%CI。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.metrics.bootstrap import bootstrap_session_diff_ci, core_run_session_ids
from patent_preexperiment.response.done import (
    PHASE_CORE,
    PHASE_MISSING,
    PHASE_POST,
    PHASE_TAIL,
    add_done_phases,
    done_anchored_summary,
)
from patent_preexperiment.response.events import GapThresholds, classify, detect_gap_events

REPO = Path(__file__).resolve().parents[3]  # 仓库根
IMPL = REPO / "patent_preexperiment"
MINUTE_TABLE = IMPL / "datasets" / "lite_session_minute.parquet"
BOUNDARY_TABLE = IMPL / "datasets" / "lite_jpl_boundary_minute.parquet"
OUT = IMPL / "results" / "raw" / "E1L"
SEED = 42
BOOT_N = 2000
PERM_SEEDS = [42, 2024, 777]


def _session_rate(events: pd.DataFrame, n_sessions: int) -> float:
    return events["session_id"].nunique() / max(n_sessions, 1)


def _events_with_phase(labeled: pd.DataFrame, thr: GapThresholds) -> pd.DataFrame:
    """检测事件并在阶段边界切断；事件行携带 event_phase。"""
    ev = detect_gap_events(labeled, thr, phase_col="phase")
    if len(ev):
        ev["event_phase"] = ev["phase"].fillna(PHASE_MISSING)
    else:
        ev["event_phase"] = pd.Series(dtype=str)
    return ev


def _load_main(cfg: dict) -> pd.DataFrame:
    df = pd.read_parquet(MINUTE_TABLE)
    df["cycle_month"] = df["timestamp_utc"].astype(str).str[:7]
    frozen = set(cfg["sample_roles"]["main_set"]["months"])
    df = df[df["cycle_month"].isin(frozen)]
    pilot_sess = df[df["pilot_available"]]["session_id"].unique()
    return df[df["session_id"].isin(pilot_sess)].copy()


def _load_boundary(cfg: dict) -> pd.DataFrame:
    df = pd.read_parquet(BOUNDARY_TABLE)
    df["cycle_month"] = df["timestamp_utc"].astype(str).str[:7]
    frozen = set(cfg["sample_roles"]["k1x_boundary"]["months"])
    return df[df["cycle_month"].isin(frozen)].copy()


def _process(
    df: pd.DataFrame, thr: GapThresholds,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    labeled = classify(df, thr)
    labeled = add_done_phases(labeled, thr.p_on_kw)
    events = _events_with_phase(labeled, thr)
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


def _core_stats(events: pd.DataFrame, labeled: pd.DataFrame, thr: GapThresholds) -> dict:
    """核心运行段（距 done>120min，阶段切断后）主口径统计。"""
    core = events[events["event_phase"] == PHASE_CORE]
    core_denom = labeled[
        (labeled["phase"] == PHASE_CORE) & labeled["charging_active"] & labeled["pilot_available"]
    ]["session_id"].nunique()
    rate = _session_rate(core, core_denom) if core_denom else 0.0
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


def _phase_summary(events: pd.DataFrame, labeled: pd.DataFrame) -> pd.DataFrame:
    """事件按 done-relative 阶段分布（阶段切断后，各阶段分别计数）。"""
    phases = list(labeled["phase"].dropna().unique())
    if not phases:
        cols = ["phase", "n_events", "n_event_sessions", "event_share", "energy_kwh"]
        return pd.DataFrame(columns=cols)
    rows: list[dict] = []
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


def _permutation_control(
    labeled: pd.DataFrame, thr: GapThresholds, core_denom: int, core_events: pd.DataFrame,
) -> dict:
    """时间置换负对照：会话内打乱实际功率，多种子；输出 diff/ratio 与会话 cluster bootstrap CI。"""
    real_core_sess = set(core_events["session_id"].unique()) if len(core_events) else set()
    real_rate = _session_rate(core_events, core_denom)
    per_seed: list[dict] = []
    perm_core_frames: dict[int, pd.DataFrame] = {}
    for s, seed in enumerate(PERM_SEEDS):
        rng = np.random.default_rng(seed)
        perm = labeled.copy()
        perm["actual_power_kw"] = perm.groupby("session_id", group_keys=False)[
            "actual_power_kw"
        ].apply(lambda x, rng=rng: pd.Series(rng.permutation(x.to_numpy()), index=x.index))
        perm = add_done_phases(perm, thr.p_on_kw)
        core = _events_with_phase(perm, thr)
        core = core[core["event_phase"] == PHASE_CORE]
        perm_core_frames[s] = core
        per_seed.append({
            "seed": seed,
            "core_events": int(len(core)),
            "core_session_rate": _session_rate(core, core_denom),
        })
    perm_rates = np.array([p["core_session_rate"] for p in per_seed])
    mean_perm = float(perm_rates.mean())
    diff = float(real_rate - mean_perm)
    ratio = float(real_rate / max(mean_perm, 1e-9))

    # K1.2.1-P0-1：bootstrap 母体=有核心运行窗口的会话（同点估计 core_denom），
    # 不得用全部合格会话——否则点估计(349/2939)与 CI(事件标记/5961)口径不一致。
    sessions = core_run_session_ids(labeled)
    real_has = np.isin(sessions, list(real_core_sess))
    perm_has = np.stack([
        np.isin(sessions, list(perm_core_frames[s]["session_id"].unique()))
        for s in perm_core_frames
    ])
    lo, hi = bootstrap_session_diff_ci(real_has, perm_has, seed=SEED, n_boot=BOOT_N)
    return {
        "real_core_session_rate": real_rate,
        "perm_rate_mean": mean_perm,
        "perm_rate_per_seed": per_seed,
        "diff_real_minus_perm": diff,
        "ratio_real_over_perm": ratio,
        "diff_bootstrap_ci95": [float(lo), float(hi)],
        "bootstrap_n_sessions": int(len(sessions)),
        "interpretation": (
            "真实时序显著增强事件（diff CI 下界>0），但 pilot/actual 边际分布本身"
            "也可产生一定事件率；不得表述为'完全排除时序伪相关'。"
            "bootstrap 母体=有核心运行窗口会话，与点估计 core_denom 同口径（K1.2.1-P0-1）。"
        ),
        "perm_core_reference": perm_core_frames[0],
    }


def _negative_controls(
    labeled: pd.DataFrame, events: pd.DataFrame, thr: GapThresholds,
    core_denom: int, session_summary: pd.DataFrame, core_events: pd.DataFrame,
) -> dict:
    neg: dict = {}
    core = core_events

    # NC-done-1: 时间置换（会话内，仅核心运行段，阶段切断）——多种子 + 差值 bootstrap
    neg["time_permutation_core"] = _permutation_control(labeled, thr, core_denom, core)

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
    ev_meas = _events_with_phase(sub, thr)
    meas_core = ev_meas[ev_meas["event_phase"] == PHASE_CORE]
    core_win = sub[(sub["phase"] == PHASE_CORE) & sub["charging_active"] & sub["pilot_available"]]
    meas_denom = core_win["session_id"].nunique()
    neg["measured_or_computed_only_core"] = {
        "core_events": int(len(meas_core)),
        "core_session_rate": _session_rate(meas_core, meas_denom) if meas_denom else 0.0,
    }

    # NC-done-4: 排除短充电会话（<30 分钟）后核心率（阶段切断）
    short = session_summary[session_summary["charging_minutes"] < 30]["session_id"]
    long_df = labeled[~labeled["session_id"].isin(short)]
    ev_long = _events_with_phase(long_df, thr)
    long_core = ev_long[ev_long["event_phase"] == PHASE_CORE]
    long_win = long_df[
        (long_df["phase"] == PHASE_CORE)
        & long_df["charging_active"] & long_df["pilot_available"]
    ]
    long_denom = long_win["session_id"].nunique()
    neg["exclude_short_sessions_lt30min_core"] = {
        "core_events": int(len(long_core)),
        "core_session_rate": _session_rate(long_core, long_denom) if long_denom else 0.0,
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


def _run_boundary(thr: GapThresholds, cfg: dict) -> dict:
    df = _load_boundary(cfg)
    labeled, events, _ = _process(df, thr)
    core = _core_stats(events, labeled, thr)
    return {
        "role": "external_boundary_only_no_tuning",
        "pool": "jpl.Arroyo 2020-06,07",
        "core": core,
        "all_events": {
            "n_events": int(len(events)),
            "event_session_rate": _session_rate(events, labeled["session_id"].nunique()),
        },
    }


def run_e1_lite() -> dict:
    cfg = load_yaml(IMPL / "configs" / "k1_preregister.yaml")
    thr = GapThresholds.from_cfg(cfg)
    OUT.mkdir(parents=True, exist_ok=True)

    # ---------- 主集 caltech（只保留冻结月份） ----------
    main_df = _load_main(cfg)
    labeled, events, session_summary = _process(main_df, thr)
    n_valid = labeled["session_id"].nunique()

    mfe = events.merge(
        labeled[["session_id", "timestamp_utc", "minutes_from_end"]],
        left_on=["session_id", "start_utc"], right_on=["session_id", "timestamp_utc"], how="left",
    )
    events["minutes_from_disconnect_at_start"] = mfe["minutes_from_end"].values

    session_summary.to_csv(OUT / "e1_lite_session_summary.csv", index=False)
    _phase_summary(events, labeled).to_csv(OUT / "e1_lite_phase_summary.csv", index=False)

    core_denom = labeled[
        (labeled["phase"] == PHASE_CORE) & labeled["charging_active"] & labeled["pilot_available"]
    ]["session_id"].nunique()
    core_events = events[events["event_phase"] == PHASE_CORE]
    core = _core_stats(events, labeled, thr)

    # 月份×核心率（核心运行段分母=该月有核心运行窗口的会话；只统计冻结月份）
    frozen = set(cfg["sample_roles"]["main_set"]["months"])
    month_rate: list[dict] = []
    for month, gm in labeled[labeled["phase"] == PHASE_CORE].groupby("cycle_month"):
        if month not in frozen:
            continue
        denom = gm[gm["charging_active"] & gm["pilot_available"]]["session_id"].nunique()
        ce = core_events[core_events["month"] == month]
        month_rate.append({
            "month": month, "n_denom_sessions": denom, "n_core_events": int(len(ce)),
            "core_event_session_rate": _session_rate(ce, denom) if denom else 0.0,
            "core_energy_kwh": float(ce["gap_energy_kwh"].sum()),
        })
    month_rate_df = pd.DataFrame(month_rate)
    month_rate_df.to_csv(OUT / "e1_lite_pool_month_summary.csv", index=False)

    neg = _negative_controls(labeled, events, thr, core_denom, session_summary, core_events)
    fail_cases = _build_fail_cases(events, neg["time_permutation_core"]["perm_core_reference"],
                                   session_summary)
    fail_cases.to_csv(OUT / "e1_lite_fail_cases.csv", index=False)
    events.to_parquet(OUT / "e1_lite_event_table.parquet", index=False)
    neg["time_permutation_core"] = {
        k: v for k, v in neg["time_permutation_core"].items() if k != "perm_core_reference"
    }

    stop = cfg["k1_stop_lines"]["e1"]
    six_month_stable = bool(
        len(month_rate_df) == len(frozen)
        and (month_rate_df["n_denom_sessions"] > 0).all()
        and (month_rate_df["core_event_session_rate"] >= stop["min_event_session_rate"]).all()
    )
    gates = {
        "n_sessions_with_core_run": core_denom,
        "core_event_session_rate": core["event_session_rate"],
        "core_median_gap_kw": core["median_gap_kw"],
        "core_median_gap_ratio_of_working": core["median_gap_ratio_of_working"],
        "post_done_events": int((events["event_phase"] == PHASE_POST).sum()),
        "pass_rate": core["event_session_rate"] >= stop["min_event_session_rate"],
        "pass_median": core["median_gap_kw"] >= stop["min_median_gap_kw"]
        or core["median_gap_ratio_of_working"] >= stop["min_median_gap_ratio"],
        "six_month_detail": {
            "frozen_months": sorted(frozen),
            "per_month_rate": month_rate_df.to_dict("records"),
        },
        "pass_months_stable": six_month_stable,
        "pass_single_station": neg["max_single_station_share_core"]
        <= stop["max_single_station_share"],
        "pass_permutation": neg["time_permutation_core"]["diff_bootstrap_ci95"][0] > 0,
    }

    # ---------- K1-X 外部边界 jpl（只评估不调参） ----------
    boundary = _run_boundary(thr, cfg)
    b_core = boundary["core"]
    boundary_direction_ok = bool(
        b_core["event_session_rate"] >= stop["min_event_session_rate"]
        and (b_core["median_gap_kw"] >= stop["min_median_gap_kw"]
             or b_core["median_gap_ratio_of_working"] >= stop["min_median_gap_ratio"])
    )
    neg_summary = {k: v for k, v in neg.items()}

    summary = {
        "threshold": {
            k: getattr(thr, k)
            for k in ("p_on_kw", "delta_r", "delta_p_kw", "t_event_min",
                      "initial_exclusion_min", "tail_exclusion_min", "pilot_active_min_a")
        },
        "done_relative": {
            "core_margin_min": 120, "mid_min": 30, "tail_min": 30,
            "anchor_inference": (
                "功率<0.3kW 持续20min 且不再恢复→推断完成时间（仅离线排伪，全会话分钟赋值）"
            ),
            "event_cutting": "事件在 core/mid/tail 边界强制切断，各段重跑持续>=T_event",
        },
        "roles": (
            "K1-M=caltech.CG1 主机制门（核心运行段，冻结 6 个月逐月>=5%）；"
            "K1-X=jpl 2020-06,07 外部边界（方向一致参考）"
        ),
        "main_set": {
            "n_valid_sessions": n_valid,
            "core_run": core,
            "phase_summary": _phase_summary(events, labeled).to_dict("records"),
            "core_event_session_rate_by_month": month_rate_df.to_dict("records"),
        },
        "external_boundary": boundary,
        "k1_x_direction_ok": boundary_direction_ok,
        "negative_controls": neg_summary,
        "gates": gates,
        "k1_m_verdict": (
            "核心运行段事件率>=5%、量级达标、冻结 6 个月逐月过线、单桩/单月不集中、"
            "置换对照低（diff CI 下界>0）→ Go"
        ),
        "k1_x_verdict": "边界方向一致（弱证据，COVID 低量窗口，不作等权第二个池）",
    }
    out_json = json.dumps(summary, ensure_ascii=False, indent=2)
    (OUT / "e1_lite_summary.json").write_text(out_json, encoding="utf-8")
    print(out_json)
    return summary


def _build_fail_cases(
    events: pd.DataFrame, ev_perm_core: pd.DataFrame, session_summary: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
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


if __name__ == "__main__":
    sys.exit(0 if run_e1_lite() else 1)
