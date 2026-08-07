"""K0-01 基线冻结与 K0-02 最小数据校验（V2.1 §17.1 Sprint 0）。"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from patent_preexperiment.io.paths import acn_project_dir

MANIFESTS = {
    "static_file_index.csv": 85877,
    "api_metadata_index.csv": 51234,
    "static_api_mapping.csv": 96467,
}

MATCH_STATUS_EXPECT = {"matched": 40644, "static_only": 45233, "api_only": 10590}

GOLD_EXPECT = 115


def _git_commit() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _line_count(path: Path) -> int:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh) - 1  # 减表头


def build_design_baseline(out: str | Path) -> dict[str, Any]:
    """K0-01：冻结协议版本、commit、数据版本（manifest 哈希）、路径、输出目录。"""
    acn = acn_project_dir()
    manifest_hashes: dict[str, Any] = {}
    for name in MANIFESTS:
        p = acn / "manifests" / name
        manifest_hashes[name] = {"sha256": _sha256(p), "exists": p.exists()}
    baseline = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_version": "V2.0",
        "landing_version": "V2.1",
        "engineering_version": "V1.1",
        "commit": _git_commit(),
        "data_version": _sha256(acn / "manifests" / "static_api_mapping.csv")[:16],
        "data_roots": {
            "acn_project": str(acn),
            "static_root": str(Path(acn).parent / "ACN-Data-Static" / "time series data"),
        },
        "output_root": "patent_preexperiment/results",
        "manifest_hashes": manifest_hashes,
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    return baseline


def check_core_data(out: str | Path | None = None) -> dict[str, Any]:
    """K0-02：核对核心文件存在、行数、match_status 计数、gold 站数、质量报告关键项。"""
    acn = acn_project_dir()
    result: dict[str, Any] = {
        "acn_project_exists": acn.exists(),
        "manifests": {},
        "gold": {},
        "quality": {},
        "passed": False,
    }

    for name, expected_rows in MANIFESTS.items():
        p = acn / "manifests" / name
        if not p.exists():
            result["manifests"][name] = {"ok": False, "reason": "missing"}
            continue
        rows = _line_count(p)
        result["manifests"][name] = {
            "ok": rows == expected_rows,
            "rows": rows,
            "expected": expected_rows,
        }

    mapping = acn / "manifests" / "static_api_mapping.csv"
    if mapping.exists():
        df = pd.read_csv(mapping, usecols=["match_status"], dtype=str)
        counts = df["match_status"].value_counts().to_dict()
        result["match_status"] = {
            "actual": counts,
            "expected": MATCH_STATUS_EXPECT,
            "ok": counts == MATCH_STATUS_EXPECT,
        }

    gold_5 = acn / "gold" / "benchmark_5min"
    gold_15 = acn / "gold" / "benchmark_15min"
    n5 = len(list(gold_5.glob("*.csv"))) if gold_5.exists() else -1
    n15 = len(list(gold_15.glob("*.csv"))) if gold_15.exists() else -1
    result["gold"] = {
        "n_5min": n5,
        "n_15min": n15,
        "expected": GOLD_EXPECT,
        "ok": n5 == GOLD_EXPECT == n15,
    }

    ecr = acn / "quality" / "energy_consistency_report.csv"
    if ecr.exists():
        e = pd.read_csv(ecr)
        rows = len(e)
        result["quality"]["energy_consistency_rows"] = rows
        result["quality"]["energy_consistency_rows_ok"] = rows == 40609
    for name in ("static_scan_summary.json", "coverage_report.csv", "benchmark_summary.json"):
        result["quality"][name] = (acn / "quality" / name).exists()

    manifests_ok = (
        all(v.get("ok", False) for v in result["manifests"].values())
        if result["manifests"]
        else False
    )
    match_ok = bool(result.get("match_status", {}).get("ok"))
    gold_ok = bool(result["gold"]["ok"])
    result["passed"] = manifests_ok and match_ok and gold_ok

    if out is not None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
