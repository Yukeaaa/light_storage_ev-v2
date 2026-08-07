"""E0F-01 baseline 组装（e0_full_baseline.schema.json，审查结论7 §4.4）。

冻结：code_sha、e0_full.yaml 哈希、三个 manifest 哈希、runtime 版本、
data_roots_resolved、split_rule_version、output_manifest、parent_baseline。
"""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas
import pyarrow

from patent_preexperiment.io.paths import acn_project_dir, load_paths


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


def build_e0_full_baseline(
    out: str | Path,
    manifest_hash_hex: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """按 schema 组装并写出 e0_full_baseline.json。

    manifest_hash_hex：source manifest 的确定性哈希（manifest_hash(df) 输出）。
    """
    acn = acn_project_dir()
    paths = load_paths()

    manifest_hashes: dict[str, dict[str, Any]] = {}
    for name in ("static_file_index.csv", "api_metadata_index.csv", "static_api_mapping.csv"):
        p = acn / "manifests" / name
        manifest_hashes[name] = {
            "sha256": _sha256(p) if p.exists() else None,
            "rows": sum(1 for _ in p.open("r", encoding="utf-8", errors="replace")) - 1
            if p.exists()
            else 0,
            "exists": p.exists(),
        }

    e0_yaml = Path(__file__).resolve().parents[3] / "configs" / "e0_full.yaml"
    baseline: dict[str, Any] = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_version": config["protocol_version"],
        "landing_version": config["landing_version"],
        "experiment_id": config["experiment_id"],
        "rule_version": config["rule_version"],
        "parent_baseline": {
            "path": "patent_preexperiment/data_registry/design_baseline.json",
            "commit": _git_commit(),
        },
        "code_sha": _git_commit(),
        "e0_full_yaml_sha256": _sha256(e0_yaml),
        "manifest_hashes": manifest_hashes,
        "runtime_versions": {
            "python": platform.python_version(),
            "pandas": pandas.__version__,
            "pyarrow": pyarrow.__version__,
        },
        "input_logical_id": "acn_project_v1",
        "data_roots_resolved": {
            "data_root": paths["data_root"],
            "acn_project": str(acn),
            "static_root": str(Path(paths["static_root"])),
            "acn_full": paths["acn_full"],
        },
        "split_rule_version": config["split"]["rule_version"],
        "output_manifest": [
            "data_registry/e0_full_source_manifest.parquet",
            "data_registry/e0_full_quality_summary.json",
            "data_registry/e0_full_connection_time_audit.parquet",
            "reports/E0_Full_input_audit.md",
            "data_registry/e0_full_baseline.json",
        ],
        "source_manifest_sha256": manifest_hash_hex,
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    return baseline
