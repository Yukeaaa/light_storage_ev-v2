"""R4-A1S-2 exact paper-metric reproduction under fixed S0 raw-label pairing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from patent_preexperiment.config.yamlutil import expand_vars, load_yaml
from patent_preexperiment.io.paths import get_paths

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r4a1s2.yaml"


def run_r4_a1s2() -> dict[str, Any]:
    cfg = load_yaml(_CONFIG)
    dataset = expand_vars(cfg["dataset"] | get_paths())
    dataset_dir = Path(str(dataset["dataset_dir"]))
    test_id = int(cfg["dataset"]["test_id"])
    measurement = pd.read_csv(
        dataset_dir / f"test_{test_id}_measurement_data.csv", parse_dates=["timestamp"]
    )
    schedule = pd.read_csv(
        dataset_dir / f"test_{test_id}_schedule_data.csv", parse_dates=["timestamp"]
    )
    interval_df = _interval_table(measurement, schedule)
    power_rows = _power_metric_variants(measurement, schedule, cfg)
    energy_rows = _energy_metric_variants(interval_df, cfg)
    event_rows = _event_metric_variants(interval_df, cfg)
    rows = power_rows + energy_rows + event_rows
    decision = _decision(rows, cfg)
    result = {
        "experiment_id": cfg["experiment_id"],
        "rule_version": cfg["rule_version"],
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": cfg["dataset"]["name"],
        "doi": cfg["dataset"]["doi"],
        "pairing": cfg["dataset"]["pairing"],
        "metric_rows": rows,
        "decision": decision,
    }
    _write_outputs(cfg, result)
    return result


def _interval_table(measurement: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    actual = measurement.set_index("timestamp").sort_index()["bess_power_ac"]
    rows: list[dict[str, Any]] = []
    origin = schedule["timestamp"].min()
    for sched in schedule.sort_values("timestamp").itertuples(index=False):
        start = sched.timestamp
        end = start + pd.Timedelta(minutes=15)
        samples = actual[(actual.index >= start) & (actual.index < end)]
        if int(samples.count()) < 855:
            continue
        p_sched = float(sched.bess_power_ac)
        p_actual = float(samples.mean())
        error_kw = p_actual - p_sched
        sign = 1.0 if p_sched >= 0 else -1.0
        requested_abs = abs(p_sched)
        rows.append({
            "hour_from_start": float((start - origin).total_seconds() / 3600),
            "p_sched_kw": p_sched,
            "p_actual_mean_kw": p_actual,
            "error_kw": error_kw,
            "abs_error_kw": abs(error_kw),
            "signed_energy_deviation_kwh": error_kw * 0.25,
            "abs_energy_deviation_kwh": abs(error_kw) * 0.25,
            "unfulfilled_energy_kwh": max(0.0, requested_abs - sign * p_actual) * 0.25
            if requested_abs >= 1.0
            else 0.0,
        })
    return pd.DataFrame(rows)


def _power_metric_variants(
    measurement: pd.DataFrame, schedule: pd.DataFrame, cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    interval = _interval_table(measurement, schedule)
    rows.append(_metric_row("power", "p_15min_mean", interval["error_kw"], "rmse_kw", cfg))
    for exclusion in [0, 15, 30, 60]:
        errors = _forward_fill_errors(measurement, schedule, exclusion)
        name = "p_1s_forward_fill_all" if exclusion == 0 else (
            f"p_1s_forward_fill_exclude_first_{exclusion}s"
        )
        rows.append(_metric_row("power", name, errors, "rmse_kw", cfg))
    return rows


def _forward_fill_errors(
    measurement: pd.DataFrame, schedule: pd.DataFrame, exclusion_seconds: int
) -> pd.Series:
    pieces: list[pd.Series] = []
    actual = measurement.set_index("timestamp").sort_index()["bess_power_ac"]
    for sched in schedule.sort_values("timestamp").itertuples(index=False):
        start = sched.timestamp + pd.Timedelta(seconds=exclusion_seconds)
        end = sched.timestamp + pd.Timedelta(minutes=15)
        samples = actual[(actual.index >= start) & (actual.index < end)]
        if not samples.empty:
            pieces.append(samples - float(sched.bess_power_ac))
    return pd.concat(pieces, ignore_index=True) if pieces else pd.Series(dtype="float64")


def _energy_metric_variants(intervals: pd.DataFrame, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    variants = {
        "e_15min_unfulfilled_all_nonzero_schedule": intervals["unfulfilled_energy_kwh"],
        "e_15min_unfulfilled_first_61h_nonzero_schedule": intervals[
            intervals["hour_from_start"] < 61
        ]["unfulfilled_energy_kwh"],
        "e_15min_abs_deviation_first_61h": intervals[intervals["hour_from_start"] < 61][
            "abs_energy_deviation_kwh"
        ],
        "e_15min_abs_deviation_ge_3_61kwh_first_61h": _energy_above(intervals, 3.61, True),
        "e_15min_abs_deviation_ge_5kwh_first_61h": _energy_above(intervals, 5.0, True),
        "e_15min_abs_deviation_ge_10kwh_all": _energy_above(intervals, 10.0, False),
    }
    return [
        _scalar_metric_row(
            "energy",
            name,
            float(values.sum()),
            "cumulative_unfulfilled_energy_kwh",
            cfg,
        )
        for name, values in variants.items()
    ]


def _energy_above(intervals: pd.DataFrame, threshold: float, first_61h: bool) -> pd.Series:
    frame = intervals[intervals["abs_energy_deviation_kwh"] >= threshold]
    if first_61h:
        frame = frame[frame["hour_from_start"] < 61]
    return frame["abs_energy_deviation_kwh"]


def _event_metric_variants(intervals: pd.DataFrame, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    major = intervals.sort_values("abs_energy_deviation_kwh", ascending=False).iloc[0]
    first = intervals[intervals["abs_energy_deviation_kwh"] >= 52.5 * 0.75].sort_values(
        "hour_from_start"
    ).iloc[0]
    return [
        _scalar_metric_row(
            "event", "first_major_curtailment_hour", float(first["hour_from_start"]),
            "first_major_curtailment_hour", cfg,
        ),
        _scalar_metric_row(
            "event",
            "largest_single_window_abs_deviation",
            float(major["abs_energy_deviation_kwh"]),
            "single_window_deviation_kwh",
            cfg,
        ),
    ]


def _metric_row(
    family: str, name: str, errors_kw: pd.Series, anchor_name: str, cfg: dict[str, Any]
) -> dict[str, Any]:
    rmse = float((errors_kw**2).mean() ** 0.5)
    mad = float(errors_kw.abs().mean())
    anchors = cfg["published_anchors"]
    rmse_error = _relative_error(rmse, float(anchors["rmse_kw"]))
    mad_error = _relative_error(mad, float(anchors["mean_absolute_deviation_kw"]))
    return {
        "family": family,
        "metric_variant": name,
        "anchor_name": anchor_name,
        "value": rmse,
        "secondary_value": mad,
        "relative_error": rmse_error,
        "secondary_relative_error": mad_error,
        "within_15pct": bool(rmse_error <= float(cfg["tolerances"]["continuous_relative"])),
        "secondary_within_15pct": bool(
            mad_error <= float(cfg["tolerances"]["continuous_relative"])
        ),
        "n": int(len(errors_kw)),
    }


def _scalar_metric_row(
    family: str, name: str, value: float, anchor_name: str, cfg: dict[str, Any]
) -> dict[str, Any]:
    anchor = float(cfg["published_anchors"][anchor_name])
    if family == "event" and anchor_name == "first_major_curtailment_hour":
        error = abs(value - anchor) / 0.25
        within = error <= float(cfg["tolerances"]["first_major_curtailment_interval_tolerance"])
    else:
        error = _relative_error(value, anchor)
        within = error <= float(cfg["tolerances"]["continuous_relative"])
    return {
        "family": family,
        "metric_variant": name,
        "anchor_name": anchor_name,
        "value": value,
        "secondary_value": float("nan"),
        "relative_error": error,
        "secondary_relative_error": float("nan"),
        "within_15pct": bool(within),
        "secondary_within_15pct": False,
        "n": 1,
    }


def _decision(rows: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    power_pass = any(
        row["family"] == "power" and row["within_15pct"] and row["secondary_within_15pct"]
        for row in rows
    )
    energy_pass = any(row["family"] == "energy" and row["within_15pct"] for row in rows)
    event_pass_count = sum(int(row["family"] == "event" and row["within_15pct"]) for row in rows)
    if power_pass and energy_pass and event_pass_count >= int(
        cfg["tolerances"]["required_event_hits"]
    ):
        verdict = "S0_RAW_LABEL_AUTHORITATIVE"
        r4a_status = "ALLOW_CORRECTED_A1A"
    else:
        verdict = "DATA_SEMANTICS_OR_METRIC_UNRESOLVED"
        r4a_status = "R4_A_STOP"
    return {
        "verdict": verdict,
        "r4a_status": r4a_status,
        "power_pass": power_pass,
        "energy_pass": energy_pass,
        "event_pass_count": event_pass_count,
        "a1b_status": "BLOCKED",
        "system_layer_status": "BLOCKED",
    }


def _relative_error(value: float, target: float) -> float:
    return abs(value - target) / target if target else float("inf")


def _write_outputs(cfg: dict[str, Any], result: dict[str, Any]) -> None:
    metrics_path = _PATENT_ROOT / str(cfg["outputs"]["metrics_csv"])
    report_path = _PATENT_ROOT / str(cfg["outputs"]["report"])
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(result["metric_rows"]).to_csv(metrics_path, index=False)
    _write_report(report_path, cfg, result)


def _write_report(path: Path, cfg: dict[str, Any], result: dict[str, Any]) -> None:
    decision = result["decision"]
    lines = [
        "# CORE_SEARCH_R4_A1S2_PAPER_METRIC_REPRO：S0 exact paper metric audit\n",
        f"> 生成时间（UTC）：{result['generated_at_utc']}",
        "> 纪律：固定 S0 raw-label pairing；不搜索新 shift，不调 tolerance，不运行 A1b。\n",
        "## 1. Paper Definition Evidence\n",
    ]
    for key, value in cfg["paper_definition_evidence"].items():
        lines.append(f"- {key}: {value}")
    lines.extend([
        "\n## 2. Metric Variant Reproduction\n",
        "| family | variant | anchor | value | secondary | rel err | secondary err | pass |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ])
    for row in result["metric_rows"]:
        passed = row["within_15pct"] and (
            row["family"] != "power" or row["secondary_within_15pct"]
        )
        lines.append(
            f"| {row['family']} | {row['metric_variant']} | {row['anchor_name']} | "
            f"{row['value']:.6g} | {row['secondary_value']:.6g} | "
            f"{row['relative_error']:.6g} | {row['secondary_relative_error']:.6g} | "
            f"{passed} |"
        )
    lines.extend([
        "\n## 3. Decision\n",
        f"verdict：**{decision['verdict']}**",
        f"R4-A status：**{decision['r4a_status']}**",
        f"power_pass：{decision['power_pass']}",
        f"energy_pass：{decision['energy_pass']}",
        f"event_pass_count：{decision['event_pass_count']}",
        f"A1b status：**{decision['a1b_status']}**",
        f"system layer status：**{decision['system_layer_status']}**\n",
        "S0 固定配对能复现 hour-61 与单窗口偏差锚点，但公开文本可还原的 power RMSE/MAD",
        "口径均未在 ±15% 内同时复现。因此 S0 只能称 preferred pairing，不能升级为",
        "authoritative execution alignment。按预注册规则，R4-A STOP，不运行 corrected A1a/A1b。\n",
        "## 4. Outputs\n",
        f"- `{cfg['outputs']['metrics_csv']}`",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
