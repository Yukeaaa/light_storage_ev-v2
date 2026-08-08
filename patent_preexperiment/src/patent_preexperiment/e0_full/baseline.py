"""E0F-01 baseline 组装（e0_full_baseline.schema.json，审查结论7 §4.4；审查结论10 P0-1）。

冻结：code_sha、e0_full.yaml 哈希、三个 manifest 哈希、runtime 版本、
data_roots_resolved、split_rule_version、output_manifest、parent_baseline。

审查结论10 P0-1 追溯链修复：
- parent_baseline.commit 从 design_baseline.json 读取其自身记录的历史提交（41dd1dd…），
  而不是运行时 HEAD；
- code_sha 记录真正运行本实验的代码提交（运行时 HEAD）；
- 正式冻结运行时要求无未提交代码（git_dirty_code 为空，证据产物输出路径除外），
  否则拒绝生成 frozen baseline（采用"代码 commit → clean run → evidence commit"两段式）。
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

_REPO_ROOT = Path(__file__).resolve().parents[4]
_IMPL_ROOT = Path(__file__).resolve().parents[3]

# 证据产物输出路径白名单（生成期间允许为已跟踪修改；其余已跟踪文件修改视为未提交代码）
_OUTPUT_PATHS = {
    "patent_preexperiment/data_registry/e0_full_source_manifest.parquet",
    "patent_preexperiment/data_registry/e0_full_quality_summary.json",
    "patent_preexperiment/data_registry/e0_full_connection_time_audit.parquet",
    "patent_preexperiment/data_registry/e0_full_dup_ts_classification.csv",
    "patent_preexperiment/data_registry/e0_full_dup_collapse_impact.json",
    "patent_preexperiment/data_registry/e0_full_dup_current_only_sensitivity.json",
    "patent_preexperiment/data_registry/e0_full_dup_current_only_full_pool_sensitivity.json",
    "patent_preexperiment/data_registry/e0_full_baseline.json",
    "patent_preexperiment/reports/E0_Full_input_audit.md",
    "patent_preexperiment/data_registry/e0_full_split_registry.parquet",
    "patent_preexperiment/data_registry/e0_full_field_mode_registry.parquet",
    "patent_preexperiment/reports/E0_Full_split_audit.md",
    "patent_preexperiment/data_registry/e0_full_session_response_partitions.json",
    "patent_preexperiment/reports/E0_Full_session_response_audit.md",
    "patent_preexperiment/data_registry/pool_registry.csv",
    "patent_preexperiment/data_registry/e0_full_pool_state_registry.json",
    "patent_preexperiment/reports/E0_Full_pool_state_audit.md",
}

# 审查结论11 低优先级增强：代码目录内任何 untracked 文件也视为未提交代码。
# 证据产物（data_registry/reports 等）不在这些目录，两段式下 untracked 证据不受影响。
_CODE_DIR_PREFIXES = (
    "patent_preexperiment/src/",
    "patent_preexperiment/configs/",
    "patent_preexperiment/experiments/",
    "patent_preexperiment/tests/",
)


def _git_commit() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                cwd=_REPO_ROOT,
            )
            .stdout.strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _git_dirty_code() -> list[str]:
    """未提交代码列表：已跟踪文件的修改/删除（排除证据产物输出路径）＋代码目录内 untracked 文件。

    只读检查（审查结论11 低优先级增强）：src/configs/experiments/tests 下任何 untracked 文件
    都使 code_clean=false；data_registry/reports 下的 untracked 证据产物不计。
    """
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            cwd=_REPO_ROOT,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ["git_unavailable"]
    dirty: list[str] = []
    for line in r.stdout.splitlines():
        if not line:
            continue
        if line.startswith("??"):
            path = line[2:].strip()
            path = path.strip('"').replace("\\", "/")
            if path.startswith(_CODE_DIR_PREFIXES):
                dirty.append(path)
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"').replace("\\", "/")
        if path in _OUTPUT_PATHS:
            continue
        dirty.append(path)
    return sorted(dirty)


def _parent_commit() -> str:
    """K0 历史基线自己记录的提交（design_baseline.json["commit"]），不是运行时 HEAD。"""
    p = _IMPL_ROOT / "data_registry" / "design_baseline.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        commit = data.get("commit")
        if commit and isinstance(commit, str):
            return commit
    except (OSError, json.JSONDecodeError):
        pass
    return _git_commit()


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
    require_clean: bool = True,
    split_registry: dict[str, Any] | None = None,
    session_response: dict[str, Any] | None = None,
    pool_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按 schema 组装并写出 e0_full_baseline.json。

    manifest_hash_hex：source manifest 的确定性哈希（manifest_hash(df) 输出）。
    require_clean=True：正式冻结运行时存在未提交代码（git_dirty_code 非空）则拒绝生成。
    split_registry：E0F-02 产物哈希（split/field_mode registry sha256 + 行数），写入
    `split_registry` 节并追加到 output_manifest。
    session_response：E0F-03 产物哈希（分区注册表 sha256 + 行数），写入
    `session_response` 节并追加到 output_manifest。
    pool_state：E0F-04 产物哈希（pool_registry + pool_state_registry sha256 + 行数），
    写入 `pool_state` 节并追加到 output_manifest。
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

    code_sha = _git_commit()
    dirty_code = _git_dirty_code()
    if require_clean and dirty_code:
        raise RuntimeError(
            "frozen baseline 拒绝生成：存在未提交代码（git_dirty_code 非空）。"
            "请先提交代码，再在 clean worktree 上运行；"
            f"dirty files: {dirty_code}"
        )

    e0_yaml = _IMPL_ROOT / "configs" / "e0_full.yaml"
    baseline: dict[str, Any] = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_version": config["protocol_version"],
        "landing_version": config["landing_version"],
        "experiment_id": config["experiment_id"],
        "rule_version": config["rule_version"],
        "parent_baseline": {
            "path": "patent_preexperiment/data_registry/design_baseline.json",
            "commit": _parent_commit(),
        },
        "code_sha": code_sha,
        "git_status": {
            "code_dirty_files": dirty_code,
            "code_clean": not dirty_code,
            "note": (
                "已跟踪文件修改（证据产物输出路径除外）与 src/configs/experiments/tests "
                "下 untracked 文件均视为未提交代码"
            ),
        },
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
        "split_registry": split_registry,
        "session_response": session_response,
        "pool_state": pool_state,
        "output_manifest": [
            "data_registry/e0_full_source_manifest.parquet",
            "data_registry/e0_full_quality_summary.json",
            "data_registry/e0_full_connection_time_audit.parquet",
            "data_registry/e0_full_dup_ts_classification.csv",
            "data_registry/e0_full_dup_collapse_impact.json",
            "data_registry/e0_full_dup_current_only_sensitivity.json",
            "reports/E0_Full_input_audit.md",
            "data_registry/e0_full_split_registry.parquet",
            "data_registry/e0_full_field_mode_registry.parquet",
            "reports/E0_Full_split_audit.md",
            "data_registry/e0_full_baseline.json",
        ]
        + (["data_registry/e0_full_session_response_partitions.json"] if session_response else [])
        + (["reports/E0_Full_session_response_audit.md"] if session_response else [])
        + (["data_registry/pool_registry.csv", "data_registry/e0_full_pool_state_registry.json"]
           if pool_state else [])
        + (["reports/E0_Full_pool_state_audit.md"] if pool_state else []),
        "source_manifest_sha256": manifest_hash_hex,
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    return baseline
