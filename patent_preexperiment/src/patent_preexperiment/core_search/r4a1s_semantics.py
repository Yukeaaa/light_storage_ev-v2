"""R4-A1S timestamp/execution semantics adjudication for RWTH M5BAT Test 2."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from patent_preexperiment.config.yamlutil import expand_vars, load_yaml
from patent_preexperiment.io.paths import get_paths

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r4a1s.yaml"


def run_r4_a1s() -> dict[str, Any]:
    cfg = load_yaml(_CONFIG)
    paths = get_paths()
    dataset = expand_vars(cfg["dataset"] | paths)
    dataset_dir = Path(str(dataset["dataset_dir"]))
    test_id = int(cfg["dataset"]["test_id"])
    metrics: list[dict[str, Any]] = []
    intervals: list[pd.DataFrame] = []
    for name, hypothesis in cfg["hypotheses"].items():
        frame = _intervals_for_hypothesis(dataset_dir, test_id, str(name), hypothesis, cfg)
        intervals.append(frame)
        metrics.append(_hypothesis_metrics(frame, str(name), hypothesis, cfg))
    decision = _adjudicate(metrics, cfg)
    result = {
        "experiment_id": cfg["experiment_id"],
        "rule_version": cfg["rule_version"],
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": cfg["dataset"]["name"],
        "doi": cfg["dataset"]["doi"],
        "metrics": metrics,
        "decision": decision,
    }
    _write_outputs(cfg, result, pd.concat(intervals, ignore_index=True))
    return result


def _intervals_for_hypothesis(
    dataset_dir: Path,
    test_id: int,
    hypothesis_name: str,
    hypothesis: dict[str, Any],
    cfg: dict[str, Any],
) -> pd.DataFrame:
    measurement = pd.read_csv(
        dataset_dir / f"test_{test_id}_measurement_data.csv", parse_dates=["timestamp"]
    )
    schedule = pd.read_csv(
        dataset_dir / f"test_{test_id}_schedule_data.csv", parse_dates=["timestamp"]
    )
    measurement["aligned_time"] = measurement["timestamp"] - pd.Timedelta(
        hours=int(hypothesis["measurement_offset_hours"])
    )
    schedule["aligned_time"] = schedule["timestamp"] - pd.Timedelta(
        hours=int(hypothesis["schedule_offset_hours"])
    )
    actual = measurement.set_index("aligned_time").sort_index()["bess_power_ac"]
    rows: list[dict[str, Any]] = []
    unfulfilled_floor = float(cfg["tolerances"]["unfulfilled_schedule_abs_kw_floor"])
    schedule = schedule.sort_values("aligned_time").reset_index(drop=True)
    origin = schedule["aligned_time"].min()
    for sched in schedule.itertuples(index=False):
        start = sched.aligned_time
        end = start + pd.Timedelta(minutes=15)
        samples = actual[(actual.index >= start) & (actual.index < end)]
        if int(samples.count()) < 855:
            continue
        p_actual = float(samples.mean())
        p_sched = float(sched.bess_power_ac)
        error_kw = p_actual - p_sched
        sign = 1.0 if p_sched >= 0 else -1.0
        requested_abs = abs(p_sched)
        unfulfilled = (
            max(0.0, requested_abs - sign * p_actual) * 0.25
            if requested_abs >= unfulfilled_floor
            else 0.0
        )
        rows.append({
            "hypothesis": hypothesis_name,
            "interval_start": start,
            "hour_from_start": float((start - origin).total_seconds() / 3600),
            "p_sched_kw": p_sched,
            "p_actual_mean_kw": p_actual,
            "error_kw": error_kw,
            "abs_error_kw": abs(error_kw),
            "signed_energy_deviation_kwh": error_kw * 0.25,
            "abs_energy_deviation_kwh": abs(error_kw) * 0.25,
            "unfulfilled_energy_kwh": unfulfilled,
            "actual_sample_count": int(samples.count()),
        })
    return pd.DataFrame(rows)


def _hypothesis_metrics(
    intervals: pd.DataFrame,
    hypothesis_name: str,
    hypothesis: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    anchors = cfg["published_anchors"]
    if intervals.empty:
        return {"hypothesis": hypothesis_name, "anchor_score": float("inf")}
    rmse = float((intervals["error_kw"] ** 2).mean() ** 0.5)
    mad = float(intervals["abs_error_kw"].mean())
    unfulfilled = float(intervals["unfulfilled_energy_kwh"].sum())
    major = intervals.sort_values("abs_energy_deviation_kwh", ascending=False).iloc[0]
    first_curtailment = _first_curtailment(intervals, float(anchors["single_window_deviation_kwh"]))
    errors = {
        "rmse_rel_error": _relative_error(rmse, float(anchors["rmse_kw"])),
        "mad_rel_error": _relative_error(mad, float(anchors["mean_absolute_deviation_kw"])),
        "unfulfilled_rel_error": _relative_error(
            unfulfilled, float(anchors["cumulative_unfulfilled_energy_kwh"])
        ),
        "first_curtailment_interval_error": abs(
            first_curtailment - float(anchors["first_major_curtailment_hour"])
        )
        / 0.25,
        "single_window_rel_error": _relative_error(
            float(major["abs_energy_deviation_kwh"]),
            float(anchors["single_window_deviation_kwh"]),
        ),
    }
    continuous_tol = float(cfg["tolerances"]["continuous_relative"])
    interval_tol = float(cfg["tolerances"]["first_major_curtailment_interval_tolerance"])
    return {
        "hypothesis": hypothesis_name,
        "description": hypothesis["description"],
        "interval_count": int(len(intervals)),
        "rmse_kw": rmse,
        "mean_absolute_deviation_kw": mad,
        "cumulative_unfulfilled_energy_kwh": unfulfilled,
        "first_major_curtailment_hour": first_curtailment,
        "largest_single_window_abs_deviation_kwh": float(major["abs_energy_deviation_kwh"]),
        "largest_single_window_hour": float(major["hour_from_start"]),
        "within_tolerance_count": _within_tolerance_count(errors, continuous_tol, interval_tol),
        "anchor_score": _anchor_score(errors, interval_tol),
        **errors,
    }


def _first_curtailment(intervals: pd.DataFrame, threshold_kwh: float) -> float:
    hits = intervals[intervals["abs_energy_deviation_kwh"] >= threshold_kwh * 0.75]
    if hits.empty:
        return float("nan")
    return float(hits.sort_values("hour_from_start").iloc[0]["hour_from_start"])


def _relative_error(value: float, target: float) -> float:
    return abs(value - target) / target if target else float("inf")


def _within_tolerance_count(
    errors: dict[str, float], continuous_tol: float, interval_tol: float
) -> int:
    count = 0
    for key, value in errors.items():
        if key == "first_curtailment_interval_error":
            count += int(value <= interval_tol)
        else:
            count += int(value <= continuous_tol)
    return count


def _anchor_score(errors: dict[str, float], interval_tol: float) -> float:
    score = 0.0
    for key, value in errors.items():
        if key == "first_curtailment_interval_error":
            score += value / max(interval_tol, 1.0)
        else:
            score += value
    return score


def _adjudicate(metrics: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    ranked = sorted(metrics, key=lambda row: float(row["anchor_score"]))
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else {"anchor_score": float("inf")}
    dominance = float(second["anchor_score"]) / max(float(best["anchor_score"]), 1e-9)
    required = float(cfg["tolerances"]["dominance_ratio_required"])
    if best["hypothesis"] == "S0_raw_label" and dominance >= required:
        return {
        "verdict": "S0_RAW_LABEL_PREFERRED_REPRO_REQUIRED",
        "a1a_status": "SUSPENDED_PENDING_A1S2_PAPER_METRIC_REPRODUCTION",
            "a1b_status": "BLOCKED",
            "system_layer_status": "BLOCKED",
            "reason": "S0 dominates S1 but absolute paper-metric reproduction is incomplete",
            "dominance_ratio": dominance,
        }
    if best["hypothesis"] == "S1_supplementary_timezone" and dominance >= required:
        return {
            "verdict": "S1_TIMEZONE_NORMALIZED_RETAINED",
            "a1a_status": "INVESTIGATE_METRIC_DISCREPANCY",
            "a1b_status": "BLOCKED",
            "system_layer_status": "BLOCKED",
            "reason": "S1 dominates S0 against published Test 2 anchors",
            "dominance_ratio": dominance,
        }
    return {
        "verdict": "DATA_SEMANTICS_UNRESOLVED",
        "a1a_status": "INVALID_FOR_DECISION",
        "a1b_status": "BLOCKED",
        "system_layer_status": "BLOCKED",
        "reason": "neither hypothesis cleanly adjudicates published anchors",
        "dominance_ratio": dominance,
    }


def _write_outputs(cfg: dict[str, Any], result: dict[str, Any], intervals: pd.DataFrame) -> None:
    metrics_path = _PATENT_ROOT / str(cfg["outputs"]["metrics_csv"])
    intervals_path = _PATENT_ROOT / str(cfg["outputs"]["intervals_csv"])
    report_path = _PATENT_ROOT / str(cfg["outputs"]["report"])
    for path in [metrics_path, intervals_path, report_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(result["metrics"]).to_csv(metrics_path, index=False)
    intervals.to_csv(intervals_path, index=False)
    _write_report(report_path, cfg, result)


def _write_report(path: Path, cfg: dict[str, Any], result: dict[str, Any]) -> None:
    decision = result["decision"]
    lines = [
        "# CORE_SEARCH_R4_A1S_SEMANTICS_AUDIT：timestamp/execution semantics adjudication\n",
        f"> 生成时间（UTC）：{result['generated_at_utc']}",
        "> 纪律：纠错审计；不改 threshold，不执行 A1b，不进入系统层。\n",
        "## 1. 背景\n",
        "09419f3 的实现忠实执行 supplementary UTC+1/UTC+2 表，但该结果与论文公开",
        "Test 2 执行 anchor 严重冲突。因此 A1a STRONG_A1B 先挂起，用论文 anchor 裁决",
        "timestamp/execution pairing 语义。\n",
        "## 2. 冻结 hypotheses\n",
        "| hypothesis | alignment |",
        "|---|---|",
        "| S0_raw_label | raw timestamp label direct pairing |",
        "| S1_supplementary_timezone | schedule UTC+1 -> UTC; measurement UTC+2 -> UTC |\n",
        "## 3. Published anchors\n",
        "| anchor | value |",
        "|---|---:|",
    ]
    for key, value in cfg["published_anchors"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend([
        "\n## 4. Reproduction metrics\n",
        "| hypothesis | RMSE kW | MAD kW | unfulfilled kWh | first major hour | "
        "single-window kWh | tolerance hits | anchor score |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in result["metrics"]:
        lines.append(
            f"| {row['hypothesis']} | {row['rmse_kw']:.6g} | "
            f"{row['mean_absolute_deviation_kw']:.6g} | "
            f"{row['cumulative_unfulfilled_energy_kwh']:.6g} | "
            f"{row['first_major_curtailment_hour']:.6g} | "
            f"{row['largest_single_window_abs_deviation_kwh']:.6g} | "
            f"{row['within_tolerance_count']} | {row['anchor_score']:.6g} |"
        )
    lines.extend([
        "\n## 5. Adjudication\n",
        f"verdict：**{decision['verdict']}**",
        f"reason：{decision['reason']}",
        f"dominance_ratio：{decision['dominance_ratio']:.6g}",
        f"A1a status：**{decision['a1a_status']}**",
        f"A1b status：**{decision['a1b_status']}**",
        f"system layer status：**{decision['system_layer_status']}**\n",
        "S0 未完全复现论文连续指标的具体统计口径，但它在 RMSE/MAD/unfulfilled energy、",
        "hour-61 重大偏差位置与单窗口偏差量级上压倒性接近 S1。S1 产生的是另一套物理世界，",
        "因此 09419f3 的 STRONG_A1B 不可作为后续 A1b 依据；S0 只能暂称 preferred pairing，",
        "需经 A1S-2 exact paper metric reproduction 后才能升级为 authoritative。\n",
        "## 6. Consequence\n",
        "- A1a STRONG_A1B = SUSPENDED。",
        "- S1 supplementary timezone normalization = REJECTED for execution pairing。",
        "- S0 raw-label pairing = PREFERRED / PAPER-METRIC REPRODUCTION REQUIRED。",
        "- A1b、控制器、系统层全部 BLOCKED，直到 A1S-2 完成。\n",
        "## 7. 产物\n",
        f"- `{cfg['outputs']['metrics_csv']}`",
        f"- `{cfg['outputs']['intervals_csv']}`",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
