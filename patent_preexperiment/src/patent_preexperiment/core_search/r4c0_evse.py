"""R4-C0 EVSE infrastructure abnormal-state capacity-loss audit.

No classifier, no controller, no system bench. The gate only asks whether real EVSE
availability/capacity-loss events exist with enough scale and spread to justify R4-C1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from patent_preexperiment.config.yamlutil import load_yaml

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r4c0.yaml"


@dataclass(frozen=True)
class EventizationConfig:
    max_gap_min: int
    nominal_capacity_kw: float
    stable_lookback_min: int
    min_stable_samples: int
    active_threshold_kw: float


def _fault_family(state: object, abnormal_states: dict[str, list[str]]) -> str | None:
    state_str = "" if pd.isna(state) else str(state)
    for family, states in abnormal_states.items():
        if state_str in states:
            return family
    return None


def _load_minutes(root: Path, columns: list[str]) -> pd.DataFrame:
    frames = [
        pq.read_table(path, columns=columns).to_pandas()
        for path in sorted(root.rglob("*.parquet"))
    ]
    if not frames:
        raise FileNotFoundError(f"No parquet files under {root}")
    df = pd.concat(frames, ignore_index=True)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df.sort_values(["station_id", "timestamp_utc"], kind="stable").reset_index(drop=True)


def _add_fault_columns(df: pd.DataFrame, abnormal_states: dict[str, list[str]]) -> pd.DataFrame:
    out = df.copy()
    out["fault_family"] = out["state_norm"].map(lambda s: _fault_family(s, abnormal_states))
    out["hard_disabled"] = out["fault_family"] == "hard_disabled"
    out["pilot_violation"] = out["fault_family"] == "pilot_violation"
    out["any_infrastructure_abnormal"] = out["fault_family"].notna()
    return out


def _eventize_fault_rows(fault_rows: pd.DataFrame, max_gap_min: int) -> pd.DataFrame:
    if fault_rows.empty:
        return fault_rows.assign(event_id=pd.Series(dtype="int64"))
    rows = fault_rows.sort_values(
        ["station_id", "fault_family", "timestamp_utc"], kind="stable"
    ).copy()
    prev_station = rows["station_id"].shift(1)
    prev_family = rows["fault_family"].shift(1)
    prev_ts = rows["timestamp_utc"].shift(1)
    gap_min = (rows["timestamp_utc"] - prev_ts).dt.total_seconds() / 60.0
    new_event = (
        (rows["station_id"] != prev_station)
        | (rows["fault_family"] != prev_family)
        | gap_min.isna()
        | (gap_min > max_gap_min)
    )
    rows["event_id"] = new_event.cumsum().astype("int64")
    return rows


def _operational_capacity(df: pd.DataFrame, active_threshold_kw: float) -> pd.Series:
    pilot = pd.to_numeric(df["pilot_power_kw"], errors="coerce")
    actual = pd.to_numeric(df["actual_power_kw"], errors="coerce")
    cap = pd.concat([pilot, actual], axis=1).max(axis=1, skipna=True).fillna(0.0)
    return cap.where(cap >= active_threshold_kw, 0.0)


def _stable_capacity_before(
    station_minutes: pd.DataFrame, onset: pd.Timestamp, cfg: EventizationConfig
) -> float:
    start = onset - pd.Timedelta(minutes=cfg.stable_lookback_min)
    before = station_minutes[
        (station_minutes["timestamp_utc"] < onset)
        & (station_minutes["timestamp_utc"] >= start)
        & ~station_minutes["any_infrastructure_abnormal"]
    ]
    before = before[before["operational_capacity_kw"] >= cfg.active_threshold_kw]
    if before.shape[0] < cfg.min_stable_samples:
        return 0.0
    return float(before["operational_capacity_kw"].median())


def _event_summaries(
    df: pd.DataFrame, events: pd.DataFrame, cfg: EventizationConfig
) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()

    non_fault_capacity = (
        df[~df["any_infrastructure_abnormal"]]
        .groupby("timestamp_utc")["operational_capacity_kw"]
        .sum()
    )
    by_station = {station: g for station, g in df.groupby("station_id", sort=False)}
    records: list[dict[str, Any]] = []

    for event_id, ev in events.groupby("event_id", sort=True):
        station = str(ev["station_id"].iloc[0])
        onset = pd.Timestamp(ev["timestamp_utc"].min())
        end = pd.Timestamp(ev["timestamp_utc"].max())
        station_minutes = by_station[station]
        stable_kw = _stable_capacity_before(station_minutes, onset, cfg)
        actual_event = pd.to_numeric(ev["actual_power_kw"], errors="coerce").fillna(0.0)
        l1_loss = (stable_kw - actual_event).clip(lower=0.0)
        l0_loss = pd.Series(cfg.nominal_capacity_kw, index=ev.index)
        denom = non_fault_capacity.reindex(ev["timestamp_utc"]).fillna(0.0).to_numpy() + l1_loss
        loss_fraction = np.divide(
            l1_loss,
            denom,
            out=np.zeros(len(l1_loss), dtype="float64"),
            where=denom > 0,
        )
        before = _window(station_minutes, onset, -15, 0)
        after = _window(station_minutes, onset, 0, 5)
        records.append({
            "event_id": int(event_id),
            "site": ev["site"].iloc[0],
            "garage": ev["garage"].iloc[0],
            "station_id": station,
            "fault_family": ev["fault_family"].iloc[0],
            "raw_states": ";".join(sorted(ev["state_norm"].dropna().astype(str).unique())),
            "start_utc": onset,
            "end_utc": end,
            "duration_min": int(ev.shape[0]),
            "session_count": int(ev["session_id"].nunique()),
            "split_set": ";".join(sorted(ev["split"].dropna().astype(str).unique())),
            "stable_capacity_kw_l1": stable_kw,
            "lost_capacity_l0_kw_mean": float(l0_loss.mean()),
            "lost_capacity_l1_kw_mean": float(l1_loss.mean()),
            "lost_capacity_l1_kw_max": float(l1_loss.max()),
            "loss_fraction_l1_mean": float(np.mean(loss_fraction)),
            "loss_fraction_l1_max": float(np.max(loss_fraction)),
            "active_at_onset_l1": stable_kw >= cfg.active_threshold_kw,
            "actual_before_kw": _median_or_nan(before["actual_power_kw"]),
            "actual_after_kw": _median_or_nan(after["actual_power_kw"]),
            "pilot_before_kw": _median_or_nan(before["pilot_power_kw"]),
            "pilot_after_kw": _median_or_nan(after["pilot_power_kw"]),
            "state_loss_sync": bool(stable_kw > 0 and float(l1_loss.iloc[0]) >= stable_kw * 0.5),
            "precursor_5m": _has_precursor(station_minutes, onset, 5, cfg.active_threshold_kw),
            "precursor_15m": _has_precursor(station_minutes, onset, 15, cfg.active_threshold_kw),
            "precursor_30m": _has_precursor(station_minutes, onset, 30, cfg.active_threshold_kw),
        })
    return pd.DataFrame(records)


def _window(df: pd.DataFrame, center: pd.Timestamp, start_min: int, end_min: int) -> pd.DataFrame:
    start = center + pd.Timedelta(minutes=start_min)
    end = center + pd.Timedelta(minutes=end_min)
    return df[(df["timestamp_utc"] >= start) & (df["timestamp_utc"] < end)]


def _median_or_nan(s: pd.Series) -> float:
    vals = pd.to_numeric(s, errors="coerce").dropna()
    return float(vals.median()) if not vals.empty else np.nan


def _has_precursor(
    station_minutes: pd.DataFrame, onset: pd.Timestamp, window_min: int, active_threshold_kw: float
) -> bool:
    before = _window(station_minutes, onset, -window_min, 0)
    if before.empty:
        return False
    has_state = bool(before["any_infrastructure_abnormal"].any())
    cap = before["operational_capacity_kw"]
    cap_drop = bool(cap.max() >= active_threshold_kw and cap.iloc[-1] < cap.max() * 0.5)
    return has_state or cap_drop


def _concurrency(df: pd.DataFrame) -> pd.DataFrame:
    abnormal = df[df["any_infrastructure_abnormal"]]
    if abnormal.empty:
        return pd.DataFrame(columns=["timestamp_utc", "disabled_station_count"])
    return (
        abnormal.groupby("timestamp_utc")["station_id"]
        .nunique()
        .rename("disabled_station_count")
        .reset_index()
    )


def _gate(
    summary: pd.DataFrame, concurrency: pd.DataFrame, gate_cfg: dict[str, Any]
) -> dict[str, Any]:
    if summary.empty:
        return {"verdict": "STOP", "reason": "no infrastructure abnormal events"}
    station_counts = summary["station_id"].value_counts()
    top1 = float(station_counts.iloc[:1].sum() / len(summary))
    top2 = float(station_counts.iloc[:2].sum() / len(summary))
    top3 = float(station_counts.iloc[:3].sum() / len(summary))
    loss_p50 = float(summary["loss_fraction_l1_max"].median())
    active_share = float(summary["active_at_onset_l1"].mean())
    ge15_share = float((summary["loss_fraction_l1_max"] >= 0.15).mean())
    multi_minutes = (
        int((concurrency["disabled_station_count"] >= 2).sum())
        if not concurrency.empty
        else 0
    )
    station_count = int(summary["station_id"].nunique())

    stop_cfg = gate_cfg["stop"]
    go_cfg = gate_cfg["go"]
    stop_reasons = []
    if top2 >= float(stop_cfg["max_top2_event_share"]):
        stop_reasons.append("events concentrated in top 1-2 stations")
    if loss_p50 < float(stop_cfg["min_l1_loss_fraction_p50"]):
        stop_reasons.append("median operational lost-capacity fraction <5%")
    if active_share < float(stop_cfg["min_active_fault_event_share"]):
        stop_reasons.append("fault states mostly occur without active operational capacity")

    go = (
        station_count >= int(go_cfg["min_station_count"])
        and ge15_share >= float(go_cfg["min_l1_loss_fraction_event_share_ge_15pct"])
        and multi_minutes >= int(go_cfg["min_concurrent_multi_station_minutes"])
        and not stop_reasons
    )
    verdict = "GO" if go else ("STOP" if stop_reasons else "CONDITIONAL")
    return {
        "verdict": verdict,
        "stop_reasons": stop_reasons,
        "station_count": station_count,
        "top1_event_share": top1,
        "top2_event_share": top2,
        "top3_event_share": top3,
        "loss_fraction_l1_p50": loss_p50,
        "loss_fraction_l1_event_share_ge_15pct": ge15_share,
        "active_fault_event_share": active_share,
        "multi_station_disabled_minutes": multi_minutes,
    }


def run_r4_c0() -> dict[str, Any]:
    cfg = load_yaml(_CONFIG)
    data_cfg = cfg["data"]
    ev_cfg = EventizationConfig(
        max_gap_min=int(cfg["eventization"]["max_gap_min"]),
        nominal_capacity_kw=float(data_cfg["nominal_capacity_kw"]),
        stable_lookback_min=int(cfg["capacity_loss"]["stable_lookback_min"]),
        min_stable_samples=int(cfg["capacity_loss"]["min_stable_samples"]),
        active_threshold_kw=float(cfg["capacity_loss"]["active_threshold_kw"]),
    )
    root = _PATENT_ROOT / str(data_cfg["session_response_root"])
    df = _load_minutes(root, list(data_cfg["source_columns"]))
    df = _add_fault_columns(df, data_cfg["abnormal_states"])
    df["operational_capacity_kw"] = _operational_capacity(df, ev_cfg.active_threshold_kw)
    fault_rows = df[df["any_infrastructure_abnormal"]].copy()
    events = _eventize_fault_rows(fault_rows, ev_cfg.max_gap_min)
    summary = _event_summaries(df, events, ev_cfg)
    conc = _concurrency(df)
    gate = _gate(summary, conc, cfg["gate"])
    stats = _stats(summary, conc, gate)

    out_root = _PATENT_ROOT / str(cfg["outputs"]["results_root"])
    out_root.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out_root / "r4_c0_events.csv", index=False)
    conc.to_csv(out_root / "r4_c0_concurrency.csv", index=False)
    pd.Series(stats).to_csv(out_root / "r4_c0_gate_stats.csv", header=["value"])
    _write_report(cfg, stats, summary, conc, gate)
    return {"stats": stats, "gate": gate}


def _stats(summary: pd.DataFrame, conc: pd.DataFrame, gate: dict[str, Any]) -> dict[str, Any]:
    stats: dict[str, Any] = dict(gate)
    stats.update({
        "event_count": int(len(summary)),
        "session_count": int(summary["session_count"].sum()) if not summary.empty else 0,
        "station_count": int(summary["station_id"].nunique()) if not summary.empty else 0,
        "duration_median_min": _q(summary, "duration_min", 0.50),
        "duration_p75_min": _q(summary, "duration_min", 0.75),
        "duration_p90_min": _q(summary, "duration_min", 0.90),
        "duration_max_min": _q(summary, "duration_min", 1.00),
        "concurrency_p50": _q(conc, "disabled_station_count", 0.50),
        "concurrency_p90": _q(conc, "disabled_station_count", 0.90),
        "concurrency_max": _q(conc, "disabled_station_count", 1.00),
        "state_loss_sync_share": _mean_bool(summary, "state_loss_sync"),
        "precursor_5m_share": _mean_bool(summary, "precursor_5m"),
        "precursor_15m_share": _mean_bool(summary, "precursor_15m"),
        "precursor_30m_share": _mean_bool(summary, "precursor_30m"),
    })
    return stats


def _q(df: pd.DataFrame, col: str, q: float) -> float:
    if df.empty or col not in df:
        return np.nan
    return float(pd.to_numeric(df[col], errors="coerce").quantile(q))


def _mean_bool(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df:
        return np.nan
    return float(df[col].astype(bool).mean())


def _write_report(
    cfg: dict[str, Any],
    stats: dict[str, Any],
    summary: pd.DataFrame,
    conc: pd.DataFrame,
    gate: dict[str, Any],
) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []
    lines.append("# CORE_SEARCH_R4_C0_GATE：EVSE 基础设施事件存在性与量纲审计\n")
    lines.append(f"> 生成时间（UTC）：{ts}")
    lines.append("> 配置：configs/core_search_r4c0.yaml（rule_version=core_search_r4c0_v1，冻结）")
    lines.append(
        "> 纪律：不预测故障、不做控制器、不做系统收益结论；"
        "L1 operational 为主口径，L0 nominal 只作上界。\n"
    )
    lines.append("## 1. 事件定义\n")
    lines.append("- 同 station、同 fault family、相邻记录 gap <= 2min 合并为同一 event。")
    lines.append(
        "- fault family：hard_disabled = DISABLED CHARGER；"
        "pilot_violation = DISABLED PILOT VIOLATION / PILOT VIOLATION。"
    )
    lines.append("- 同时保留 raw state，并输出 any_infrastructure_abnormal。\n")
    lines.append("## 2. 核心量\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---:|")
    for key in [
        "event_count", "session_count", "station_count", "duration_median_min",
        "duration_p75_min", "duration_p90_min", "duration_max_min",
        "top1_event_share", "top2_event_share", "top3_event_share",
        "concurrency_p50", "concurrency_p90", "concurrency_max",
        "loss_fraction_l1_p50", "loss_fraction_l1_event_share_ge_15pct",
        "active_fault_event_share", "state_loss_sync_share", "precursor_5m_share",
        "precursor_15m_share", "precursor_30m_share",
    ]:
        lines.append(f"| {key} | {_fmt(stats.get(key))} |")
    lines.append("")
    lines.append("## 3. 按 fault family\n")
    lines.append(
        "| fault_family | events | stations | median duration | p90 duration | ge15% event share |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|")
    if not summary.empty:
        for family, grp in summary.groupby("fault_family", sort=True):
            ge15 = float((grp["loss_fraction_l1_max"] >= 0.15).mean())
            lines.append(
                f"| {family} | {len(grp)} | {grp['station_id'].nunique()} | "
                f"{grp['duration_min'].median():.1f} | "
                f"{grp['duration_min'].quantile(0.9):.1f} | {ge15:.3f} |"
            )
    lines.append("")
    lines.append("## 4. 判门\n")
    lines.append(f"### 判定：**{gate['verdict']}**\n")
    stop_reasons = gate.get("stop_reasons") or []
    if stop_reasons:
        lines.append("STOP reasons：" + "; ".join(str(r) for r in stop_reasons))
    elif gate["verdict"] == "GO":
        lines.append(
            "多站、重复、L1 operational 量纲与并发均满足 GO 条件，"
            "可进入 R4-C1 system propagation gate。"
        )
    else:
        lines.append("存在重复基础设施事件，但系统相关量纲或并发未达到 GO；暂不进入系统层。")
    lines.append("\n## 5. 产物\n")
    lines.append(f"- `{cfg['outputs']['results_root']}/r4_c0_events.csv`")
    lines.append(f"- `{cfg['outputs']['results_root']}/r4_c0_concurrency.csv`")
    lines.append(f"- `{cfg['outputs']['results_root']}/r4_c0_gate_stats.csv`")

    report = _PATENT_ROOT / str(cfg["outputs"]["report"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return "nan" if np.isnan(value) else f"{value:.4f}"
    return str(value)
