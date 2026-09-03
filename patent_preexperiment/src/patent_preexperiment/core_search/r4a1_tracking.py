"""R4-A1 RWTH M5BAT tracking-capability gate.

A1-0 freezes timestamp semantics before any tracking calculation. A1a then measures
15-minute energy/mean-power schedule tracking magnitude. This module deliberately does
not implement A1b candidate modeling or any system-layer propagation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from patent_preexperiment.config.yamlutil import expand_vars, load_yaml
from patent_preexperiment.io.paths import get_paths

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r4a1.yaml"


def run_r4_a1() -> dict[str, Any]:
    cfg = load_yaml(_CONFIG)
    paths = get_paths()
    dataset_cfg = expand_vars(cfg["dataset"] | paths)
    dataset_dir = Path(str(dataset_cfg["dataset_dir"]))
    alignment_rows: list[dict[str, Any]] = []
    interval_frames: list[pd.DataFrame] = []
    for test_id in [int(value) for value in cfg["dataset"]["tests"]]:
        alignment, intervals = _audit_test(dataset_dir, test_id, cfg)
        alignment_rows.append(alignment)
        if not intervals.empty:
            interval_frames.append(intervals)
    intervals_all = (
        pd.concat(interval_frames, ignore_index=True) if interval_frames else pd.DataFrame()
    )
    alignment_gate = _alignment_gate(alignment_rows, cfg["a1_0_alignment_gate"])
    magnitude = _magnitude_gate(intervals_all, cfg["a1a_magnitude_gate"], alignment_gate)
    raw_label_diagnostic = _raw_label_diagnostic(dataset_dir, cfg)
    result = {
        "experiment_id": cfg["experiment_id"],
        "rule_version": cfg["rule_version"],
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": cfg["dataset"]["name"],
        "doi": cfg["dataset"]["doi"],
        "alignment_gate": alignment_gate,
        "magnitude_gate": magnitude,
        "raw_label_diagnostic": raw_label_diagnostic,
    }
    _write_outputs(cfg, result, alignment_rows, intervals_all)
    return result


def _audit_test(
    dataset_dir: Path, test_id: int, cfg: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame]:
    measurement_path = dataset_dir / f"test_{test_id}_measurement_data.csv"
    schedule_path = dataset_dir / f"test_{test_id}_schedule_data.csv"
    if not measurement_path.exists() or not schedule_path.exists():
        return _missing_alignment(test_id, measurement_path, schedule_path), pd.DataFrame()
    measurement = pd.read_csv(measurement_path, parse_dates=["timestamp"])
    schedule = pd.read_csv(schedule_path, parse_dates=["timestamp"])
    measurement["timestamp_utc"] = _to_utc(
        measurement["timestamp"], int(cfg["dataset"]["measurement_timezone_utc_offset_hours"])
    )
    schedule["timestamp_utc"] = _to_utc(
        schedule["timestamp"], int(cfg["dataset"]["schedule_timezone_utc_offset_hours"])
    )
    raw_hits = int(measurement["timestamp"].isin(set(schedule["timestamp"])).sum())
    intervals = _interval_metrics(
        measurement,
        schedule,
        test_id,
        cfg["a1_0_alignment_gate"],
        cfg["a1a_magnitude_gate"],
    )
    usable = intervals[intervals["interval_usable"]]
    alignment = {
        "test_id": test_id,
        "raw_label_schedule_timestamp_hits": raw_hits,
        "measurement_utc_start": str(measurement["timestamp_utc"].min()),
        "measurement_utc_end": str(measurement["timestamp_utc"].max()),
        "schedule_utc_start": str(schedule["timestamp_utc"].min()),
        "schedule_utc_end": str(schedule["timestamp_utc"].max()),
        "schedule_interval_count": int(len(schedule)),
        "usable_interval_count": int(len(usable)),
        "coverage_share": float(len(usable) / len(schedule)) if len(schedule) else 0.0,
        "min_sample_count_usable": int(usable["actual_sample_count"].min())
        if not usable.empty
        else 0,
        "p50_sample_count_all": float(intervals["actual_sample_count"].median())
        if not intervals.empty
        else 0.0,
    }
    return alignment, intervals


def _to_utc(series: pd.Series, offset_hours: int) -> pd.Series:
    localized = series.dt.tz_localize(f"Etc/GMT-{offset_hours}")
    return localized.dt.tz_convert("UTC")


def _interval_metrics(
    measurement: pd.DataFrame,
    schedule: pd.DataFrame,
    test_id: int,
    gate_cfg: dict[str, Any],
    magnitude_cfg: dict[str, Any],
) -> pd.DataFrame:
    expected = int(gate_cfg["expected_samples_per_interval"])
    min_samples = int(expected * float(gate_cfg["min_sample_completeness_share"]))
    actual = measurement.set_index("timestamp_utc").sort_index()["bess_power_ac"]
    transition_exclusion = int(magnitude_cfg["transition_exclusion_seconds"])
    rows: list[dict[str, Any]] = []
    for sched in schedule.sort_values("timestamp_utc").itertuples(index=False):
        start = sched.timestamp_utc
        end = start + pd.Timedelta(minutes=15)
        samples = actual[(actual.index >= start) & (actual.index < end)]
        steady_start = start + pd.Timedelta(seconds=transition_exclusion)
        steady_samples = actual[(actual.index >= steady_start) & (actual.index < end)]
        sample_count = int(samples.count())
        steady_sample_count = int(steady_samples.count())
        actual_mean = float(samples.mean()) if sample_count else float("nan")
        actual_median = float(samples.median()) if sample_count else float("nan")
        steady_mean = float(steady_samples.mean()) if steady_sample_count else float("nan")
        p_sched = float(sched.bess_power_ac)
        error = actual_mean - p_sched if sample_count else float("nan")
        steady_error = steady_mean - p_sched if steady_sample_count else float("nan")
        sign = 1.0 if p_sched >= 0 else -1.0
        requested_abs = abs(p_sched)
        sign_aware_actual = sign * actual_mean if sample_count else float("nan")
        steady_sign_aware_actual = sign * steady_mean if steady_sample_count else float("nan")
        shortfall_kw = max(0.0, requested_abs - sign_aware_actual) if sample_count else float("nan")
        steady_shortfall_kw = (
            max(0.0, requested_abs - steady_sign_aware_actual)
            if steady_sample_count
            else float("nan")
        )
        rows.append({
            "test_id": test_id,
            "interval_start_utc": start,
            "interval_end_utc": end,
            "p_sched_kw": p_sched,
            "p_actual_mean_kw": actual_mean,
            "p_actual_median_kw": actual_median,
            "tracking_error_kw": error,
            "steady_tracking_error_kw": steady_error,
            "abs_tracking_error_kw": abs(error) if sample_count else float("nan"),
            "steady_abs_tracking_error_kw": abs(steady_error)
            if steady_sample_count
            else float("nan"),
            "relative_tracking_error": abs(error) / max(requested_abs, 1.0)
            if sample_count
            else float("nan"),
            "sign_aware_actual_kw": sign_aware_actual,
            "shortfall_kw": shortfall_kw,
            "steady_shortfall_kw": steady_shortfall_kw,
            "shortfall_kwh": shortfall_kw * 0.25 if sample_count else float("nan"),
            "steady_shortfall_kwh": steady_shortfall_kw * (900 - transition_exclusion) / 3600
            if steady_sample_count
            else float("nan"),
            "requested_kwh_abs": requested_abs * 0.25,
            "delivered_ratio": sign_aware_actual / requested_abs
            if requested_abs > 0
            else float("nan"),
            "direction": _direction(p_sched),
            "actual_sample_count": sample_count,
            "steady_sample_count": steady_sample_count,
            "interval_usable": sample_count >= min_samples,
        })
    return pd.DataFrame(rows)


def _alignment_gate(rows: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    min_coverage = float(cfg["min_schedule_interval_coverage_share"])
    usable = [row for row in rows if float(row.get("coverage_share", 0.0)) >= min_coverage]
    verdict = "PASS" if len(usable) >= int(cfg["min_usable_test_count"]) else "STOP"
    return {
        "verdict": verdict,
        "usable_test_count": len(usable),
        "min_required_usable_test_count": int(cfg["min_usable_test_count"]),
        "min_required_coverage_share": min_coverage,
        "reason": "timezone-normalized alignment usable"
        if verdict == "PASS"
        else "alignment unusable",
    }


def _magnitude_gate(
    intervals: pd.DataFrame,
    cfg: dict[str, Any],
    alignment_gate: dict[str, Any],
) -> dict[str, Any]:
    if alignment_gate["verdict"] != "PASS" or intervals.empty:
        return {"verdict": "STOP", "reason": "A1-0 alignment gate failed"}
    active = intervals[
        (intervals["interval_usable"])
        & (intervals["p_sched_kw"].abs() >= float(cfg["active_schedule_abs_kw_floor"]))
    ].copy()
    if active.empty:
        return {"verdict": "STOP", "reason": "no active usable schedule intervals"}
    summary = _active_summary(active, cfg)
    ratio = float(summary["equivalent_shortfall_ratio"])
    thresholds = cfg["verdict_thresholds"]
    if ratio < float(thresholds["stop_lt"]):
        verdict = "STOP"
    elif ratio < float(thresholds["weak_lt"]):
        verdict = "WEAK"
    elif ratio < float(thresholds["worth_lt"]):
        verdict = "WORTH_A1B"
    else:
        verdict = "STRONG_A1B"
    return {"verdict": verdict, "reason": _verdict_reason(verdict), **summary}


def _active_summary(active: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    requested_kwh = float(active["requested_kwh_abs"].sum())
    shortfall_kwh = float(active["shortfall_kwh"].sum())
    steady_shortfall_kwh = float(active["steady_shortfall_kwh"].sum())
    abs_error_kwh = float((active["abs_tracking_error_kw"] * 0.25).sum())
    large = active[
        (active["shortfall_kw"] >= float(cfg["large_shortfall_abs_kw"]))
        & (
            active["shortfall_kw"] / active["p_sched_kw"].abs()
            >= float(cfg["large_shortfall_relative"])
        )
    ]
    return {
        "active_interval_count": int(len(active)),
        "charge_interval_count": int((active["direction"] == "charge").sum()),
        "discharge_interval_count": int((active["direction"] == "discharge").sum()),
        "requested_energy_kwh_abs": requested_kwh,
        "shortfall_energy_kwh": shortfall_kwh,
        "steady_shortfall_energy_kwh": steady_shortfall_kwh,
        "abs_tracking_error_energy_kwh": abs_error_kwh,
        "equivalent_shortfall_ratio": shortfall_kwh / requested_kwh if requested_kwh else 0.0,
        "steady_equivalent_shortfall_ratio": steady_shortfall_kwh / requested_kwh
        if requested_kwh
        else 0.0,
        "equivalent_abs_error_ratio": abs_error_kwh / requested_kwh if requested_kwh else 0.0,
        "mae_kw": float(active["abs_tracking_error_kw"].mean()),
        "steady_mae_kw": float(active["steady_abs_tracking_error_kw"].mean()),
        "p50_abs_error_kw": float(active["abs_tracking_error_kw"].quantile(0.50)),
        "p90_abs_error_kw": float(active["abs_tracking_error_kw"].quantile(0.90)),
        "p95_abs_error_kw": float(active["abs_tracking_error_kw"].quantile(0.95)),
        "p50_shortfall_kw": float(active["shortfall_kw"].quantile(0.50)),
        "p90_shortfall_kw": float(active["shortfall_kw"].quantile(0.90)),
        "p95_shortfall_kw": float(active["shortfall_kw"].quantile(0.95)),
        "charge_equivalent_shortfall_ratio": _direction_shortfall_ratio(active, "charge"),
        "discharge_equivalent_shortfall_ratio": _direction_shortfall_ratio(active, "discharge"),
        "large_shortfall_interval_share": float(len(large) / len(active)),
        "max_consecutive_large_shortfall_intervals": _max_run(
            active["shortfall_kw"] >= float(cfg["large_shortfall_abs_kw"])
        ),
        "top5_abs_error_share": _top_n_share(active["abs_tracking_error_kw"] * 0.25, 5),
    }


def _direction_shortfall_ratio(active: pd.DataFrame, direction: str) -> float:
    subset = active[active["direction"] == direction]
    requested = float(subset["requested_kwh_abs"].sum())
    if requested <= 0:
        return 0.0
    return float(subset["shortfall_kwh"].sum() / requested)


def _raw_label_diagnostic(dataset_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    frames: list[pd.DataFrame] = []
    original = dict(cfg["dataset"])
    diagnostic_cfg = dict(cfg)
    diagnostic_cfg["dataset"] = {
        **original,
        "schedule_timezone_utc_offset_hours": 0,
        "measurement_timezone_utc_offset_hours": 0,
    }
    for test_id in [int(value) for value in cfg["dataset"]["tests"]]:
        _, intervals = _audit_test(dataset_dir, test_id, diagnostic_cfg)
        if not intervals.empty:
            frames.append(intervals)
    intervals = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    gate = {"verdict": "PASS"}
    result = _magnitude_gate(intervals, cfg["a1a_magnitude_gate"], gate)
    return {
        "alignment": "raw-label sensitivity only; not primary evidence",
        "verdict": result.get("verdict"),
        "equivalent_shortfall_ratio": result.get("equivalent_shortfall_ratio"),
        "active_interval_count": result.get("active_interval_count"),
    }


def _direction(value: float) -> str:
    if value > 0:
        return "discharge"
    if value < 0:
        return "charge"
    return "idle"


def _max_run(flags: pd.Series) -> int:
    best = 0
    current = 0
    for flag in flags.fillna(False):
        if bool(flag):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _top_n_share(values: pd.Series, n: int) -> float:
    total = float(values.sum())
    if total <= 0:
        return 0.0
    return float(values.sort_values(ascending=False).head(n).sum() / total)


def _verdict_reason(verdict: str) -> str:
    return {
        "STOP": "active 15min equivalent tracking shortfall <10%",
        "WEAK": "active 15min equivalent tracking shortfall is 10-15%",
        "WORTH_A1B": "active 15min equivalent tracking shortfall is 15-20%",
        "STRONG_A1B": "active 15min equivalent tracking shortfall >=20%",
    }[verdict]


def _missing_alignment(test_id: int, measurement_path: Path, schedule_path: Path) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "missing_measurement": not measurement_path.exists(),
        "missing_schedule": not schedule_path.exists(),
        "schedule_interval_count": 0,
        "usable_interval_count": 0,
        "coverage_share": 0.0,
    }


def _write_outputs(
    cfg: dict[str, Any],
    result: dict[str, Any],
    alignment_rows: list[dict[str, Any]],
    intervals: pd.DataFrame,
) -> None:
    alignment_path = _PATENT_ROOT / str(cfg["outputs"]["alignment_csv"])
    intervals_path = _PATENT_ROOT / str(cfg["outputs"]["intervals_csv"])
    summary_path = _PATENT_ROOT / str(cfg["outputs"]["summary_csv"])
    for path in [alignment_path, intervals_path, summary_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(alignment_rows).to_csv(alignment_path, index=False)
    intervals.to_csv(intervals_path, index=False)
    pd.DataFrame([result["alignment_gate"], result["magnitude_gate"]]).to_csv(summary_path)
    _write_prereg(cfg)
    _write_report(cfg, result, alignment_rows)


def _write_prereg(cfg: dict[str, Any]) -> None:
    path = _PATENT_ROOT / str(cfg["outputs"]["prereg"])
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# CORE_SEARCH_R4_A1_PREREG：RWTH M5BAT tracking-capability gate\n",
        f"> rule_version={cfg['rule_version']}；冻结日期={cfg['frozen_date']}。\n",
        "## A1-0 时间语义冻结\n",
        (
            "- primary alignment：schedule timestamp UTC+1 -> UTC；measurement timestamp "
            "UTC+2 -> UTC。"
        ),
        "- raw-label alignment 只作 sensitivity/diagnostic，不作为主 tracking 结论。",
        "- 若 timezone-normalized interval coverage <95%，R4-A1 直接 STOP。\n",
        "## A1a tracking magnitude gate\n",
        "- primary：15min interval mean-power / energy tracking，不做逐秒 residual 主结论。",
        "- active interval：|P_sched| >= 100 kW；idle 不进入主样本。",
        "- primary metric：sign-aware equivalent shortfall energy / requested absolute energy。",
        "- <10% STOP；10-15% weak；15-20% worth A1b；>=20% strong A1b。\n",
        "## A1b 暂不执行\n",
        "只有 A1a 过门后，才比较 SOC+direction+schedule-magnitude baseline 与 recent residual。",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_report(
    cfg: dict[str, Any], result: dict[str, Any], alignment_rows: list[dict[str, Any]]
) -> None:
    path = _PATENT_ROOT / str(cfg["outputs"]["report"])
    path.parent.mkdir(parents=True, exist_ok=True)
    mag = result["magnitude_gate"]
    lines = [
        "# CORE_SEARCH_R4_A1_TRACKING_GATE：RWTH M5BAT tracking magnitude\n",
        f"> 生成时间（UTC）：{result['generated_at_utc']}",
        "> 纪律：A1-0 + A1a only；不执行 A1b，不进入系统层，不称 BESS 物理降额。\n",
        "## 1. A1-0 timezone-normalized alignment\n",
        (
            "| test | schedule intervals | usable intervals | coverage | raw label hits | "
            "UTC range note |"
        ),
        "|---:|---:|---:|---:|---:|---|",
    ]
    for row in alignment_rows:
        lines.append(
            f"| {row['test_id']} | {row.get('schedule_interval_count', 0)} | "
            f"{row.get('usable_interval_count', 0)} | {row.get('coverage_share', 0):.4f} | "
            f"{row.get('raw_label_schedule_timestamp_hits', 0)} | "
            f"{row.get('measurement_utc_start')} -> {row.get('measurement_utc_end')} |"
        )
    align = result["alignment_gate"]
    lines.extend([
        "",
        f"A1-0 verdict：**{align['verdict']}**，{align['reason']}。\n",
        "## 2. A1a tracking magnitude\n",
        "| 指标 | 值 |",
        "|---|---:|",
    ])
    for key, value in mag.items():
        if isinstance(value, int | float):
            lines.append(f"| {key} | {value:.6g} |")
        else:
            lines.append(f"| {key} | {value} |")
    lines.extend([
        "\n## 3. 判定\n",
        f"A1a verdict：**{mag['verdict']}**。",
        "若 A1a 未达到 WORTH_A1B，不启动 A1b、控制器或系统传播。\n",
        "## 4. raw-label diagnostic\n",
    ])
    raw = result["raw_label_diagnostic"]
    lines.extend([
        "| 指标 | 值 |",
        "|---|---:|",
        f"| active_interval_count | {raw.get('active_interval_count')} |",
        f"| equivalent_shortfall_ratio | {raw.get('equivalent_shortfall_ratio'):.6g} |",
        f"| verdict | {raw.get('verdict')} |",
        "",
        "raw-label alignment 只作 sensitivity/diagnostic。它与官方时区归一主口径出现量级分歧：",
        "raw-label tracking shortfall 很低，而 timezone-normalized shortfall 很高。",
        "因此 A1a 的主结果只能说明按 supplementary 时区语义存在 material tracking gap；",
        "进入 A1b 前必须人工复核 timestamp 语义，不能直接把该 gap 解释为 BESS 物理能力原因。\n",
        "## 5. 产物\n",
        f"- `{cfg['outputs']['prereg']}`",
        f"- `{cfg['outputs']['alignment_csv']}`",
        f"- `{cfg['outputs']['intervals_csv']}`",
        f"- `{cfg['outputs']['summary_csv']}`",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
