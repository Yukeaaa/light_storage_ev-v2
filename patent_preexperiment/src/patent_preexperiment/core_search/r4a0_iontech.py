"""R4-A0 Iontech/Aachen BESS local field/schema audit.

This is a data gate only. It does not infer physical derating without command/setpoint
semantics and state/limit evidence.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from patent_preexperiment.config.yamlutil import expand_vars, load_yaml
from patent_preexperiment.io.paths import get_paths

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r4a0.yaml"


def _candidate_files(
    roots: list[str], keywords: list[str], identity_keywords: list[str], exclude_parts: list[str]
) -> list[Path]:
    found: list[Path] = []
    lowered = [k.lower() for k in keywords]
    identity = [k.lower() for k in identity_keywords]
    excluded = {p.lower() for p in exclude_parts}
    for root_s in roots:
        root = Path(root_s)
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_dir():
                continue
            path_text = str(path).lower()
            if any(part.lower() in excluded for part in path.parts):
                continue
            if not any(k in path_text for k in identity):
                continue
            if any(k in path.name.lower() for k in lowered):
                found.append(path)
    return sorted(set(found))


def _columns_for_file(path: Path) -> list[str]:
    suffixes = "".join(path.suffixes).lower()
    try:
        if suffixes.endswith(".csv") or suffixes.endswith(".csv.gz"):
            return list(pd.read_csv(path, nrows=0).columns)
        if suffixes.endswith(".parquet"):
            return list(pq.read_schema(path).names)
    except Exception:
        return []
    return []


def _field_hits(files: list[Path], requirements: dict[str, dict[str, list[str]]]) -> dict[str, Any]:
    file_columns = {str(path): _columns_for_file(path) for path in files[:50]}
    text = "\n".join([str(p) for p in files] + [" ".join(cols) for cols in file_columns.values()])
    text = text.lower()
    hits: dict[str, Any] = {}
    for field, spec in requirements.items():
        keywords = [str(k).lower() for k in spec["keywords"]]
        matched = [k for k in keywords if k in text]
        hits[field] = {"present": bool(matched), "matched_keywords": matched}
    return {"fields": hits, "file_columns": file_columns}


def _level(field_hits: dict[str, Any], n_files: int) -> str:
    if n_files == 0:
        return "DATA_PENDING"
    fields = field_hits["fields"]
    actual = bool(fields["actual_bess_power"]["present"])
    soc = bool(fields["soc"]["present"])
    command = bool(fields["command_setpoint"]["present"] or fields["dispatch_schedule"]["present"])
    state = bool(
        fields["temperature"]["present"]
        or fields["charge_discharge_limit"]["present"]
        or fields["alarms_status"]["present"]
    )
    if actual and soc and command and state:
        return "A"
    if actual and soc and command:
        return "B"
    if actual and soc:
        return "C"
    return "DATA_PENDING"


def run_r4_a0() -> dict[str, Any]:
    cfg = load_yaml(_CONFIG)
    paths = get_paths()
    expanded = expand_vars({"roots": cfg["candidate_dataset"]["local_search_roots"]} | paths)
    roots = [str(r) for r in expanded["roots"]]
    keywords = [str(k) for k in cfg["candidate_dataset"]["filename_keywords"]]
    identity_keywords = [str(k) for k in cfg["candidate_dataset"]["identity_keywords"]]
    exclude_parts = [str(k) for k in cfg["candidate_dataset"]["exclude_path_parts"]]
    files = _candidate_files(roots, keywords, identity_keywords, exclude_parts)
    hits = _field_hits(files, cfg["field_requirements"])
    level = _level(hits, len(files))
    registry: dict[str, Any] = {
        "experiment_id": cfg["experiment_id"],
        "rule_version": cfg["rule_version"],
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": cfg["candidate_dataset"]["name"],
        "local_files_found": len(files),
        "candidate_files_sample": [str(p) for p in files[:50]],
        "field_hits": hits["fields"],
        "data_level": level,
        "level_meaning": cfg["level_rules"][level],
        "time_semantics_status": (
            "NOT_AUDITABLE_WITHOUT_METADATA"
            if level == "DATA_PENDING"
            else "PENDING_MANUAL_REVIEW"
        ),
    }
    registry_path = _PATENT_ROOT / str(cfg["outputs"]["registry"])
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(cfg, registry)
    return registry


def _write_report(cfg: dict[str, Any], registry: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# CORE_SEARCH_R4_A0_DATA_AUDIT：Iontech/Aachen BESS 字段与语义审计\n")
    lines.append(f"> 生成时间（UTC）：{registry['generated_at_utc']}")
    lines.append("> 配置：configs/core_search_r4a0.yaml（rule_version=core_search_r4a0_v1，冻结）")
    lines.append(
        "> 纪律：只审计 README/metadata/raw schema；不建 pipeline，"
        "不把 actual<schedule 直接称 physical derating。\n"
    )
    lines.append("## 1. 本地数据发现\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| local files found | {registry['local_files_found']} |")
    lines.append(f"| data level | **{registry['data_level']}** |")
    lines.append(f"| level meaning | {registry['level_meaning']} |")
    lines.append(f"| time semantics | {registry['time_semantics_status']} |\n")
    lines.append("## 2. 字段存在性\n")
    lines.append("| 字段 | present | matched keywords |")
    lines.append("|---|---|---|")
    for field, hit in registry["field_hits"].items():
        lines.append(f"| {field} | {hit['present']} | {', '.join(hit['matched_keywords'])} |")
    lines.append("\n## 3. 时间语义\n")
    if registry["data_level"] == "DATA_PENDING":
        lines.append(
            "- 本地未发现可审计的 Iontech/Aachen metadata/raw files；timestamp timezone、"
            "sampling interval、command 生效语义、schedule 重调规则均不可审计。"
        )
    else:
        lines.append(
            "- 需人工确认 timezone、采样间隔、clock alignment、command timestamp 生效语义、"
            "schedule 是否中途重调、actual 与 command 最大时间偏差。"
        )
    lines.append("\n## 4. 结论\n")
    if registry["data_level"] == "A":
        lines.append("- **LEVEL A**：可启动 R4-A1 physical capability / derating existence gate。")
    elif registry["data_level"] == "B":
        lines.append("- **LEVEL B**：只能做 tracking-capability；禁止称 physical derating。")
    elif registry["data_level"] == "C":
        lines.append("- **LEVEL C**：actual + SOC only；R4-A core path STOP。")
    else:
        lines.append("- **DATA_PENDING**：未取得最小必要元数据/原始 schema；R4-A 不进入机制门。")
    lines.append("\n## 5. 产物\n")
    lines.append(f"- `{cfg['outputs']['registry']}`")
    report_path = _PATENT_ROOT / str(cfg["outputs"]["report"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
