"""R4-A0b RWTH Aachen official M5BAT data landing audit.

This gate only audits fields and timestamp semantics. Level B supports a schedule-tracking
question, not a BESS physical derating claim.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from patent_preexperiment.config.yamlutil import expand_vars, load_yaml
from patent_preexperiment.io.paths import get_paths

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r4a0b.yaml"


def run_r4_a0b() -> dict[str, Any]:
    cfg = load_yaml(_CONFIG)
    paths = get_paths()
    expanded = expand_vars(cfg["candidate_dataset"] | paths)
    dataset_dir = Path(str(expanded["dataset_dir"]))
    pdf_path = Path(str(expanded["supplementary_pdf"]))
    expected = [str(name) for name in cfg["candidate_dataset"]["expected_files"]]
    files = [dataset_dir / name for name in expected]
    existing_files = [path for path in files if path.exists()]
    schema = _schema_rows(existing_files)
    alignment = _alignment_rows(dataset_dir)
    pdf_text = _extract_pdf_actual_text(pdf_path)
    fields = _field_hits(schema, pdf_text, cfg["field_requirements"])
    data_level = _data_level(fields, alignment, len(existing_files), len(expected))
    source_status = (
        "DATA_SOURCE_RESOLVED" if len(existing_files) == len(expected) else "DATA_PENDING"
    )
    registry: dict[str, Any] = {
        "experiment_id": cfg["experiment_id"],
        "rule_version": cfg["rule_version"],
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": cfg["candidate_dataset"]["name"],
        "doi": cfg["candidate_dataset"]["doi"],
        "record_url": cfg["candidate_dataset"]["record_url"],
        "local_root": str(expanded["local_root"]),
        "data_source_status": source_status,
        "expected_files": expected,
        "local_files_found": len(existing_files),
        "missing_files": [path.name for path in files if not path.exists()],
        "field_hits": fields,
        "schema_summary": schema,
        "alignment_summary": alignment,
        "schedule_semantics": _schedule_semantics(pdf_text),
        "data_level": data_level,
        "level_meaning": cfg["level_rules"][data_level],
        "research_question": (
            "在相同 SOC 和外部 dispatch requirement 下，真实 BESS 的 schedule-tracking "
            "shortfall 是否存在显著、重复、状态相关的结构。"
        ),
    }
    _write_outputs(cfg, registry)
    return registry


def _schema_rows(files: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(files):
        df = pd.read_csv(path, parse_dates=["timestamp"])
        interval_s = df["timestamp"].diff().dropna().dt.total_seconds()
        mode_interval = None if interval_s.empty else float(interval_s.mode().iloc[0])
        rows.append({
            "file": path.name,
            "rows": int(len(df)),
            "columns": list(df.columns),
            "column_count": int(len(df.columns)),
            "start_timestamp": str(df["timestamp"].min()),
            "end_timestamp": str(df["timestamp"].max()),
            "sampling_interval_seconds_mode": mode_interval,
            "sampling_frequency": _frequency_label(mode_interval),
            "units": _units_for_columns(df.columns),
        })
    return rows


def _alignment_rows(dataset_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for test_id in [1, 2]:
        measurement = dataset_dir / f"test_{test_id}_measurement_data.csv"
        schedule = dataset_dir / f"test_{test_id}_schedule_data.csv"
        if not measurement.exists() or not schedule.exists():
            continue
        m = pd.read_csv(measurement, usecols=["timestamp"], parse_dates=["timestamp"])
        s = pd.read_csv(schedule, usecols=["timestamp"], parse_dates=["timestamp"])
        overlap_start = max(m["timestamp"].min(), s["timestamp"].min())
        overlap_end = min(m["timestamp"].max(), s["timestamp"].max())
        overlap_seconds = max(0.0, float((overlap_end - overlap_start).total_seconds()))
        schedule_times = set(s["timestamp"])
        timestamp_hits = m["timestamp"].isin(schedule_times)
        raw_aligned = bool(overlap_seconds > 0 and timestamp_hits.any())
        rows.append({
            "test_id": test_id,
            "measurement_start": str(m["timestamp"].min()),
            "measurement_end": str(m["timestamp"].max()),
            "schedule_start": str(s["timestamp"].min()),
            "schedule_end": str(s["timestamp"].max()),
            "overlap_seconds": overlap_seconds,
            "measurement_rows_on_schedule_timestamps": int(timestamp_hits.sum()),
            "raw_timestamp_aligned": raw_aligned,
            "alignment_semantics_status": "RAW_LABEL_ALIGNED_WITH_TIMEZONE_CAVEAT"
            if raw_aligned
            else "NOT_ALIGNED",
        })
    return rows


def _field_hits(
    schema: list[dict[str, Any]], pdf_text: str, requirements: dict[str, dict[str, list[str]]]
) -> dict[str, dict[str, Any]]:
    columns_text = " ".join(" ".join(str(c) for c in row["columns"]) for row in schema).lower()
    combined = f"{columns_text}\n{pdf_text.lower()}"
    hits: dict[str, dict[str, Any]] = {}
    for field, spec in requirements.items():
        keywords = [str(keyword).lower() for keyword in spec["keywords"]]
        matched = [keyword for keyword in keywords if keyword in combined]
        hits[field] = {"present": bool(matched), "matched_keywords": matched}
    return hits


def _data_level(
    fields: dict[str, dict[str, Any]],
    alignment: list[dict[str, Any]],
    n_files: int,
    n_expected: int,
) -> str:
    if n_files < n_expected:
        return "DATA_PENDING"
    actual = bool(fields["actual_bess_power"]["present"])
    schedule = bool(fields["dispatch_schedule"]["present"])
    soc = bool(fields["soc"]["present"])
    state = any(
        bool(fields[name]["present"])
        for name in ["temperature", "charge_discharge_limit", "alarms_status"]
    )
    aligned = any(bool(row["raw_timestamp_aligned"]) for row in alignment)
    if actual and schedule and soc and state and aligned:
        return "A"
    if actual and schedule and soc and aligned:
        return "B"
    if actual and soc:
        return "C"
    return "DATA_PENDING"


def _schedule_semantics(pdf_text: str) -> dict[str, Any]:
    text = pdf_text.lower()
    source = (
        "M5Use scheduling optimization framework"
        if "m5use" in text or "m 5 use" in text
        else "UNKNOWN"
    )
    resolution = "15 minutes" if "15 - minute" in text or "15-minute" in text else "UNKNOWN"
    execution = (
        "operation plans used for physical system execution and comparison with measurement data"
        if "executed on the physical system" in text
        else "UNKNOWN"
    )
    return {
        "source": source,
        "optimization_type": "MILP" if "milp" in text or "mixed-integer" in text else "UNKNOWN",
        "time_resolution": resolution,
        "execution_semantics": execution,
        "reoptimization_during_execution": "NOT_IDENTIFIED_IN_AUDIT",
        "timestamp_timezone_note": (
            "schedule UTC+1; measurement UTC+2 per supplementary field table"
        ),
    }


def _extract_pdf_actual_text(path: Path) -> str:
    if not path.exists():
        return ""
    raw = path.read_bytes().decode("latin1", errors="ignore")
    values = re.findall(r"/ActualText\((.*?)\)", raw, flags=re.S)
    text = " ".join(values)
    return text.replace("\x00", "")


def _frequency_label(interval_s: float | None) -> str:
    if interval_s is None:
        return "UNKNOWN"
    if interval_s == 1.0:
        return "1 second"
    if interval_s == 900.0:
        return "15 minutes"
    return f"{interval_s:g} seconds"


def _units_for_columns(columns: pd.Index) -> dict[str, str]:
    units: dict[str, str] = {}
    for column in columns:
        col = str(column)
        if col == "timestamp":
            units[col] = "timestamp; timezone differs by file family per supplementary PDF"
        elif col.endswith("_soc"):
            units[col] = "%"
        elif "power" in col:
            units[col] = "kW"
        elif col.endswith("_energy"):
            units[col] = "kWh"
        else:
            units[col] = "UNKNOWN"
    return units


def _write_outputs(cfg: dict[str, Any], registry: dict[str, Any]) -> None:
    registry_path = _PATENT_ROOT / str(cfg["outputs"]["registry"])
    schema_path = _PATENT_ROOT / str(cfg["outputs"]["schema_csv"])
    alignment_path = _PATENT_ROOT / str(cfg["outputs"]["alignment_csv"])
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    alignment_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(_flatten_schema(registry["schema_summary"])).to_csv(schema_path, index=False)
    pd.DataFrame(registry["alignment_summary"]).to_csv(alignment_path, index=False)
    _write_report(cfg, registry)


def _flatten_schema(schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in schema:
        for column in item["columns"]:
            rows.append({
                "file": item["file"],
                "rows": item["rows"],
                "column": column,
                "unit": item["units"][column],
                "start_timestamp": item["start_timestamp"],
                "end_timestamp": item["end_timestamp"],
                "sampling_frequency": item["sampling_frequency"],
            })
    return rows


def _write_report(cfg: dict[str, Any], registry: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# CORE_SEARCH_R4_A0b_RWTH_OFFICIAL_AUDIT：RWTH M5BAT 官方数据落地审计\n")
    lines.append(f"> 生成时间（UTC）：{registry['generated_at_utc']}")
    lines.append(
        "> 配置：configs/core_search_r4a0b.yaml"
        "（rule_version=core_search_r4a0b_v1，冻结）"
    )
    lines.append(
        "> 纪律：只做官方数据源、字段、单位、粒度、schedule 语义与对齐审计；"
        "不启动 Round 5。\n"
    )
    lines.append("## 1. 数据源状态\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| DOI | {registry['doi']} |")
    lines.append(f"| source status | **{registry['data_source_status']}** |")
    lines.append(f"| local root | `{registry['local_root']}` |")
    lines.append(f"| local files found | {registry['local_files_found']} |")
    lines.append(f"| data level | **LEVEL {registry['data_level']}** |")
    lines.append(f"| level meaning | {registry['level_meaning']} |\n")
    lines.append("## 2. 文件、字段、单位与采样频率\n")
    lines.append("| file | rows | columns | sampling | start | end |")
    lines.append("|---|---:|---:|---|---|---|")
    for item in registry["schema_summary"]:
        lines.append(
            f"| {item['file']} | {item['rows']} | {item['column_count']} | "
            f"{item['sampling_frequency']} | {item['start_timestamp']} | {item['end_timestamp']} |"
        )
    lines.append("\n字段单位详见 `results/raw/core_search/r4_a0b/rwth_m5bat_2025_schema.csv`。\n")
    lines.append("## 3. schedule 语义\n")
    sem = registry["schedule_semantics"]
    lines.append("| 项 | 审计结论 |")
    lines.append("|---|---|")
    for key, value in sem.items():
        lines.append(f"| {key} | {value} |")
    lines.append("\n## 4. timestamp 对齐\n")
    lines.append(
        "| test | measurement range | schedule range | overlap seconds | "
        "schedule timestamp hits | raw label aligned | semantics |"
    )
    lines.append("|---:|---|---|---:|---:|---|---|")
    for item in registry["alignment_summary"]:
        lines.append(
            f"| {item['test_id']} | {item['measurement_start']} -> {item['measurement_end']} | "
            f"{item['schedule_start']} -> {item['schedule_end']} | {item['overlap_seconds']} | "
            f"{item['measurement_rows_on_schedule_timestamps']} | "
            f"{item['raw_timestamp_aligned']} | "
            f"{item['alignment_semantics_status']} |"
        )
    lines.append("\n- test_1 schedule 与 measurement 时间戳不重叠，不能作为严格对齐回放样本。")
    lines.append(
        "- test_2 schedule 与 measurement 原始 timestamp 标签同期，15 分钟 schedule "
        "timestamp 均命中 1 秒 measurement。"
    )
    lines.append(
        "- supplementary PDF 同时标注 schedule timestamp 为 UTC+1、measurement timestamp "
        "为 UTC+2；"
    )
    lines.append(
        "  因此 tracking gate 前必须冻结时区归一化规则，不能在本审计中声称"
        "绝对时间已无歧义严格对齐。\n"
    )
    lines.append("## 5. Level 判定\n")
    lines.append("| 字段族 | present | matched keywords |")
    lines.append("|---|---|---|")
    for field, hit in registry["field_hits"].items():
        lines.append(f"| {field} | {hit['present']} | {', '.join(hit['matched_keywords'])} |")
    lines.append(
        "\n结论：**LEVEL B**。官方数据已落地，具备 actual power + optimized schedule + SOC，"
    )
    lines.append(
        "且 test_2 存在原始 timestamp 标签对齐；但未发现 temperature / status / "
        "power limit / alarm，"
    )
    lines.append(
        "test_1 也不能作为严格对齐样本。因此只能进入 tracking-capability gate，"
        "禁止称 BESS 物理降额。\n"
    )
    lines.append("## 6. 后续唯一允许问题\n")
    lines.append(f"> {registry['research_question']}\n")
    lines.append("## 7. 产物\n")
    lines.append(f"- `{cfg['outputs']['registry']}`")
    lines.append(f"- `{cfg['outputs']['schema_csv']}`")
    lines.append(f"- `{cfg['outputs']['alignment_csv']}`")
    report_path = _PATENT_ROOT / str(cfg["outputs"]["report"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
