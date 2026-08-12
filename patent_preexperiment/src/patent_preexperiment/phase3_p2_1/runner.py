"""P2.1A formal runner（v1.3 §7 执行顺序）——Step-0 只读 sufficiency + 单次 A-gate exposure。

执行序列（Freeze manifest 治理顺序；区分 implementation SHA 与 evidence commit SHA）：
    --lock-impl    : Implementation Review PASS 后锁 implementation_code_sha（clean worktree，
                     HEAD = 纯代码 commit）。写入 sentinel，不触碰 status（仍 UNCONSUMED）。
    --step0        : 要求 sentinel UNCONSUMED + implementation_code_sha 已锁 + clean worktree
                     + 当前 HEAD == locked impl SHA。构建 eligible / B3 map / trigger counts
                     （**全部不读 Y/gain/Δ/CI**），只输出 sufficiency 计数（§5）。
                     Step-0 **不写 status**，只附加 sufficiency/artifact 信息。
                     产出 evidence → worktree 变 dirty → evidence-only commit。
    --formal-test  : 单次 exposure。前置：sentinel UNCONSUMED + step0 SUFFICIENT +
                     step0 summary sha 与 sentinel 一致 + 4 个 step0 artifact SHA 逐个校验 +
                     当前 HEAD 相对 locked impl SHA 只变化 allowlisted evidence paths
                     （src/config/protocol/tests 不得变）+ clean worktree。
                     sentinel 在读取 outcome 之前写 RUNNING；完成后 → CONSUMED（once_only）。
    --read-frozen  : 只读已冻结 summary，绝不重算。
    --exit-code    : A-gate PASS → 0，FAIL/DATA_INSUFFICIENT → 1（fail-closed）。

数据：E0 minutes JPL train current_only（matched，v1.3 §8）；无合成、无重采样。

Step-0 import 物理隔离：本模块顶层 **不** import outcome/bootstrap/gate/formal-metrics；
执行 --step0 的进程根本不加载这些 outcome 计算 API（Freeze manifest 要求）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.e1_full.gate import git_provenance
from patent_preexperiment.phase3_p2.pipeline import load_pool_minutes
from patent_preexperiment.phase3_p2.schema import load_schema
from patent_preexperiment.phase3_p2_1.b3_map import build_or_load_b3_map
from patent_preexperiment.phase3_p2_1.frozen import FROZEN, assert_d3_trigger_params_match
from patent_preexperiment.phase3_p2_1.metrics import build_trigger_counts
from patent_preexperiment.phase3_p2_1.risk_set import (
    build_boundary_frame_sorted,
    eligible_mask,
)
from patent_preexperiment.phase3_p2_1.sufficiency import evaluate_sufficiency
from patent_preexperiment.phase3_p2_1.triggers import trigger_masks

_SENTINEL_PATH = FROZEN.sentinel_path  # results/raw/phase3_p2_1/p2_1a_sentinel.json
_STEP0_PATH = "results/raw/phase3_p2_1/p2_1a_step0.json"
_SUMMARY_PATH = "results/raw/phase3_p2_1/p2_1a_summary.json"
_MANIFEST_PATH = "results/raw/phase3_p2_1/p2_1a_manifest.json"
_REPORT_PATH = "results/raw/phase3_p2_1/P2_1A_outcome_report.md"  # v1.3 §4.5

_BF_PATH = "results/raw/phase3_p2_1/p2_1a_boundary_frame.parquet"
_ELIGIBLE_PATH = "results/raw/phase3_p2_1/p2_1a_eligible.parquet"
_B3MAP_PATH = "results/raw/phase3_p2_1/p2_1a_b3_map.parquet"
_TRIGGER_COUNTS_PATH = "results/raw/phase3_p2_1/p2_1a_trigger_counts.parquet"
_TRIGGER_TABLE_PATH = "results/raw/phase3_p2_1/p2_1a_trigger_table.parquet"
_BOOTSTRAP_PATH = "results/raw/phase3_p2_1/p2_1a_bootstrap_deltas.npz"

_BF_KEEP = [
    "session_id", "run_id", "segment_id", "timestamp_utc", "cycle_index",
    "protective_bound", "actual_power_kw", "post_window_ok",
]

_EVIDENCE_PREFIXES = ("patent_preexperiment/results/raw/phase3_p2_1/",)

_STEP0_ARTIFACT_KEYS = ("boundary_frame", "eligible", "b3_map", "trigger_counts")


# ---------------------------------------------------------------------------
# 基础 IO / provenance helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_diff_name_only(repo: Path, a: str, b: str) -> list[str]:
    """`git diff --name-only a b` 的路径列表（a/b 是 commit-ish）。失败 → RuntimeError。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "diff", "--name-only", a, b],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip()
        return [ln for ln in out.splitlines() if ln]
    except Exception as e:
        raise RuntimeError(f"P2.1A git diff 失败（{a}..{b}）：{e}") from e


# ---------------------------------------------------------------------------
# sentinel 治理（Blocker 4：不复活、验冻结身份、Step-0 不写 status）
# ---------------------------------------------------------------------------

def _read_sentinel_strict(impl_root: Path) -> dict[str, Any]:
    """读 sentinel；不存在 → fail；验冻结身份字段与 v1.3 一致。"""
    path = impl_root / _SENTINEL_PATH
    if not path.exists():
        raise RuntimeError("P2.1A sentinel 缺失；禁止任何 Step-0/formal 操作（先建 sentinel）")
    s = _read_json(path)
    _assert_sentinel_identity(s, path)
    return s


def _assert_sentinel_identity(s: dict[str, Any], path: Path) -> None:
    """验证 sentinel 的冻结身份字段与 v1.3 frozen 协议一致（防 sentinel 被篡改/复活）。"""
    checks = [
        ("experiment_id", s.get("experiment_id"), FROZEN.experiment_id),
        ("protocol_version", s.get("protocol_version"), FROZEN.protocol_version),
        ("frozen_protocol_commit_sha", s.get("frozen_protocol_commit_sha"),
         FROZEN.frozen_protocol_commit_sha),
        ("frozen_protocol_blob_sha", s.get("frozen_protocol_blob_sha"),
         FROZEN.frozen_protocol_blob_sha),
    ]
    for name, got, want in checks:
        if got != want:
            raise RuntimeError(
                f"P2.1A sentinel 身份字段 {name} 漂移：{got!r} != frozen {want!r}（{path}）"
            )
    if s.get("once_only") is not True:
        raise RuntimeError(f"P2.1A sentinel once_only 必须 True（{path}）")


def _require_unconsumed(s: dict[str, Any], action: str) -> None:
    status = s.get("status")
    if status != "UNCONSUMED":
        raise RuntimeError(
            f"P2.1A {action} 拒绝：sentinel status={status!r}（非 UNCONSUMED）；"
            f"once_only 已锁死，RUNNING/CONSUMED/ABORTED 永久拒绝"
        )


def _write_sentinel(impl_root: Path, payload: dict[str, Any]) -> None:
    _write_json(impl_root / _SENTINEL_PATH, payload)


# ---------------------------------------------------------------------------
# schema / pool
# ---------------------------------------------------------------------------

def _load_pool(impl_root: Path) -> tuple[Any, pd.DataFrame]:
    scfg = load_schema(impl_root / "configs" / "phase3_p2_action_schema.yaml")
    assert_d3_trigger_params_match(scfg)  # Blocker 3：D3 trigger 参数防漂移
    registry = pd.read_parquet(impl_root / "data_registry" / "e0_full_split_registry.parquet")
    pool = load_pool_minutes(
        impl_root / "datasets" / "session_response_1min",
        registry,
        site=FROZEN.risk_set_site,
        field_mode=FROZEN.risk_set_field_mode,
        split=FROZEN.risk_set_split,
    )
    return scfg, pool


# ---------------------------------------------------------------------------
# --lock-impl（Blocker 6：锁 implementation SHA）
# ---------------------------------------------------------------------------

def lock_implementation(impl_root: Path) -> dict[str, Any]:
    """Implementation Review PASS 后锁 implementation_code_sha。

    要求：sentinel 存在且 UNCONSUMED、clean committed worktree、code_sha 非 unknown。
    只写 implementation_* 字段，不触碰 status（仍 UNCONSUMED）。
    """
    s = _read_sentinel_strict(impl_root)
    _require_unconsumed(s, "--lock-impl")
    prov = git_provenance(impl_root.parent)
    if prov["code_sha"] == "unknown" or prov.get("worktree_clean") is not True:
        raise RuntimeError(
            "P2.1A --lock-impl：要求 clean committed worktree（纯代码 commit），"
            f"当前 code_sha={prov['code_sha']!r}, worktree_clean={prov.get('worktree_clean')!r}"
        )
    s.update(
        {
            "implementation_code_sha": prov["code_sha"],
            "implementation_worktree_clean": prov["worktree_clean"],
            "implementation_locked_at": pd.Timestamp.now(tz="UTC").isoformat(),
        }
    )
    _write_sentinel(impl_root, s)
    return s


# ---------------------------------------------------------------------------
# --step0（Blocker 4/6：UNCONSUMED only、不写 status、locked impl SHA 匹配）
# ---------------------------------------------------------------------------

def _step0_artifacts(impl_root: Path) -> dict[str, Any]:
    """构建并落盘 eligible / boundary frame / B3 map / trigger counts（Step-0 全流程）。"""
    scfg, pool = _load_pool(impl_root)
    bf = build_boundary_frame_sorted(pool, scfg)
    elig_series = eligible_mask(bf)
    eligible = bf.loc[elig_series].copy()

    masks = trigger_masks(bf, scfg)
    masks_elig = {
        method: mask.reindex(eligible.index)
        for method, mask in masks.items()
    }
    out_dir = impl_root / "results" / "raw" / "phase3_p2_1"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "boundary_frame": out_dir / _BF_PATH.split("/")[-1],
        "eligible": out_dir / _ELIGIBLE_PATH.split("/")[-1],
        "b3_map": out_dir / _B3MAP_PATH.split("/")[-1],
        "trigger_counts": out_dir / _TRIGGER_COUNTS_PATH.split("/")[-1],
    }
    # B3 map：一次生成、永久固定（C2）；已存在则 load+语义校验，不覆盖
    b3_map = build_or_load_b3_map(eligible, paths["b3_map"])
    trigger_counts = build_trigger_counts(eligible, masks_elig, b3_map)

    bf[_BF_KEEP].to_parquet(paths["boundary_frame"], index=False)
    eligible.to_parquet(paths["eligible"], index=False)
    trigger_counts.to_parquet(paths["trigger_counts"], index=False)
    return {
        "paths": {k: str(v.as_posix()) for k, v in paths.items()},
        "sha256": {k: _file_sha256(v) for k, v in paths.items()},
    }


def run_step0(impl_root: Path) -> dict[str, Any]:
    """Step-0：只读 eligible/trigger counts（§5 sufficiency）。禁止读 Y/gain/Δ/CI。"""
    s = _read_sentinel_strict(impl_root)
    _require_unconsumed(s, "--step0")
    locked_impl = s.get("implementation_code_sha")
    if not locked_impl or locked_impl == "unknown":
        raise RuntimeError("P2.1A --step0：implementation_code_sha 未锁，先跑 --lock-impl")

    prov = git_provenance(impl_root.parent)
    if prov["code_sha"] == "unknown" or prov.get("worktree_clean") is not True:
        raise RuntimeError(
            "P2.1A --step0：要求 clean committed worktree（HEAD == locked impl SHA），"
            f"当前 code_sha={prov['code_sha']!r}, worktree_clean={prov.get('worktree_clean')!r}"
        )
    if prov["code_sha"] != locked_impl:
        raise RuntimeError(
            f"P2.1A --step0：当前 HEAD {prov['code_sha']} != locked implementation "
            f"{locked_impl}；Step-0 必须在锁定的实现 commit 上跑"
        )

    artifacts = _step0_artifacts(impl_root)
    eligible = pd.read_parquet(impl_root / artifacts["paths"]["eligible"])
    trigger_counts = pd.read_parquet(impl_root / artifacts["paths"]["trigger_counts"])
    suff = evaluate_sufficiency(eligible, trigger_counts)

    step0 = {
        "experiment_id": FROZEN.experiment_id,
        "protocol_version": FROZEN.protocol_version,
        "scope": "P2.1A Step-0 data sufficiency（read-only counts；禁止读 Y/gain/Δ/CI）",
        "data": "E0 minutes JPL train current_only（matched）",
        "sufficiency": suff.to_dict(),
        "artifacts": artifacts,
        "implementation_code_sha": locked_impl,
        "provenance": prov,
    }
    _write_json(impl_root / _STEP0_PATH, step0)

    # Blocker 4：Step-0 **不写 status**，只附加 sufficiency/artifact 信息
    s.update(
        {
            "step0_data_sufficiency_status": (
                "SUFFICIENT" if suff.sufficient else "INSUFFICIENT"
            ),
            "step0_summary_sha256": _file_sha256(impl_root / _STEP0_PATH),
            "step0_artifacts": artifacts["paths"],
            "step0_artifact_sha256": artifacts["sha256"],
            "step0_counts": {
                "n_eligible_segments": suff.n_eligible_segments,
                "trigger_distinct_sessions": dict(suff.trigger_sessions),
            },
            "step0_code_sha": prov["code_sha"],
        }
    )
    _write_sentinel(impl_root, s)
    return step0


def _load_step0(impl_root: Path) -> dict[str, Any]:
    path = impl_root / _STEP0_PATH
    if not path.exists():
        raise FileNotFoundError("P2.1A formal test 前必须先跑 --step0")
    return _read_json(path)


# ---------------------------------------------------------------------------
# evidence-diff 校验（Blocker 6：locked impl SHA → HEAD 只变化 evidence paths）
# ---------------------------------------------------------------------------

def _assert_evidence_only_diff(impl_root: Path, locked_impl: str, head_sha: str) -> None:
    """HEAD 相对 locked implementation SHA 只允许变化 allowlisted evidence paths。"""
    if locked_impl == head_sha:
        return  # 无 evidence commit（Step-0 证据尚未 commit 也允许，只要 worktree 此刻 clean）
    changed = _git_diff_name_only(impl_root.parent, locked_impl, head_sha)
    violations = [
        p for p in changed if not p.startswith(_EVIDENCE_PREFIXES)
    ]
    if violations:
        raise RuntimeError(
            "P2.1A hard gate（evidence-only diff）：HEAD 相对 locked implementation SHA "
            f"变化了非 evidence 路径：{violations}（允许前缀：{_EVIDENCE_PREFIXES}）；"
            "src/config/protocol/tests 不得在 lock-impl 后变化"
        )


# ---------------------------------------------------------------------------
# --formal-test（Blocker 4/5/6：UNCONSUMED + artifact SHA + evidence diff + 单次）
# ---------------------------------------------------------------------------

def run_formal_test(impl_root: Path) -> dict[str, Any]:
    """正式 A-gate exposure：单次；sentinel 先锁 code_sha 再读 outcome（§7 [6]）。

    outcome 计算 API（compute_y/bootstrap/gate/build_trigger_table/point_metrics）在此函数
    内延迟 import——Step-0 进程根本不加载它们（import 物理隔离，Freeze manifest 要求）。
    """
    s = _read_sentinel_strict(impl_root)
    _require_unconsumed(s, "--formal-test")
    locked_impl = s.get("implementation_code_sha")
    if not locked_impl or locked_impl == "unknown":
        raise RuntimeError("P2.1A --formal-test：implementation_code_sha 未锁，先跑 --lock-impl")

    step0 = _load_step0(impl_root)
    if not step0["sufficiency"]["sufficient"]:
        raise RuntimeError("P2.1A hard gate：DATA INSUFFICIENT，停在 Step-0，禁止 formal exposure")

    step0_path = impl_root / _STEP0_PATH
    step0_sha = _file_sha256(step0_path)
    if step0_sha != s.get("step0_summary_sha256"):
        raise RuntimeError("P2.1A hard gate：step0 summary sha 与 sentinel 记录不一致")

    prov = git_provenance(impl_root.parent)
    if prov["code_sha"] == "unknown":
        raise RuntimeError("P2.1A hard gate：当前 code_sha 未知")
    if prov.get("worktree_clean") is not True:
        raise RuntimeError("P2.1A hard gate：worktree 不洁净，禁止 formal exposure")
    _assert_evidence_only_diff(impl_root, locked_impl, prov["code_sha"])

    # Blocker 5：逐个 SHA256 校验 4 个 step0 artifact（fail-closed）
    artifact_sha = step0["artifacts"]["sha256"]
    for name in _STEP0_ARTIFACT_KEYS:
        apath = impl_root / step0["artifacts"]["paths"][name]
        if not apath.exists():
            raise RuntimeError(f"P2.1A hard gate：step0 artifact 缺失：{apath}")
        actual = _file_sha256(apath)
        if actual != artifact_sha[name]:
            raise RuntimeError(
                f"P2.1A hard gate（artifact integrity）：{name} SHA256 漂移 "
                f"step0 记录={artifact_sha[name]} != 当前={actual}；禁止 exposure"
            )

    # sentinel 在读取 test outcome 之前写 RUNNING（锁 formal code_sha）
    s.update(
        {
            "status": "RUNNING",
            "formal_code_sha": prov["code_sha"],
            "code_sha_locked": True,
            "worktree_clean_at_code_lock": prov["worktree_clean"],
            "formal_exposure_started_at": pd.Timestamp.now(tz="UTC").isoformat(),
        }
    )
    _write_sentinel(impl_root, s)

    # 延迟 import：outcome 计算 API（Step-0 进程不加载）
    from patent_preexperiment.phase3_p2_1.b3_map import load_b3_map  # noqa: E402
    from patent_preexperiment.phase3_p2_1.bootstrap import (  # noqa: E402
        bootstrap_delta_distributions,
        percentile_ci,
    )
    from patent_preexperiment.phase3_p2_1.gate import a_gate_verdict  # noqa: E402
    from patent_preexperiment.phase3_p2_1.metrics import (  # noqa: E402
        build_trigger_table,
        point_metrics,
    )
    from patent_preexperiment.phase3_p2_1.outcome import compute_y  # noqa: E402

    bf = pd.read_parquet(impl_root / step0["artifacts"]["paths"]["boundary_frame"])
    eligible = pd.read_parquet(impl_root / step0["artifacts"]["paths"]["eligible"])
    load_b3_map(impl_root / step0["artifacts"]["paths"]["b3_map"])  # 校验 artifact 可读
    trigger_counts = pd.read_parquet(impl_root / step0["artifacts"]["paths"]["trigger_counts"])

    # Y 按 (segment_id, timestamp_utc) 映射（artifact reload 后 index 不再与 bf 对齐）
    y_full = compute_y(bf)
    y_frame = pd.DataFrame(
        {
            "segment_id": bf["segment_id"].to_numpy(),
            "timestamp_utc": bf["timestamp_utc"].to_numpy(),
            "y": y_full.to_numpy(dtype=float),
        }
    )
    elig_y = eligible[["segment_id", "timestamp_utc"]].merge(
        y_frame, on=["segment_id", "timestamp_utc"], how="left"
    )["y"]
    if elig_y.isna().any():
        s.update({"status": "ABORTED", "reason": "eligible Y undefined"})
        _write_sentinel(impl_root, s)
        raise RuntimeError("P2.1A fail-closed：eligible 行存在未定义的 Y")
    trigger_table = build_trigger_table(trigger_counts, eligible, elig_y.astype(bool))

    n_eligible_segments = int(eligible["segment_id"].nunique())
    point = point_metrics(trigger_table, n_eligible_segments)

    # Blocker 2：bootstrap universe = 全部 eligible session IDs
    eligible_sessions = eligible["session_id"].unique()
    dist = bootstrap_delta_distributions(trigger_table, eligible_sessions)
    ci = {
        "delta_b1": percentile_ci(dist["delta_b1"]),
        "delta_b3": percentile_ci(dist["delta_b3"]),
        "delta_b2": percentile_ci(dist["delta_b2"]),
    }
    gate = a_gate_verdict(point, ci)

    # step0 evidence 运行期间被替换 → fail-closed
    if _file_sha256(step0_path) != step0_sha:
        s.update({"status": "ABORTED", "reason": "step0_summary_sha256 changed mid-run"})
        _write_sentinel(impl_root, s)
        raise RuntimeError("P2.1A hard gate（integrity）：step0 evidence 运行期间被替换，未落盘")

    summary = {
        "experiment_id": FROZEN.experiment_id,
        "protocol_version": FROZEN.protocol_version,
        "scope": "P2.1A A-gate formal exposure（单次；JPL train current_only，不合成）",
        "data": "E0 minutes JPL train current_only（matched）",
        "sufficiency": step0["sufficiency"],
        "implementation_code_sha": locked_impl,
        "point_metrics": {
            "gains": {k: _r(v) for k, v in point["gains"].items()},
            "delta_b1": _r(point["delta_b1"]),
            "delta_b3": _r(point["delta_b3"]),
            "delta_b2": _r(point["delta_b2"]),
            "best_rolling": _r(point["best_rolling"]),
            "coverage": {k: _r(v) for k, v in point["coverage"].items()},
            "latency": {k: _r(v) for k, v in point["latency"].items()},
            "n_triggers": point["n_triggers"],
            "n_eligible_segments": point["n_eligible_segments"],
        },
        "bootstrap": {
            "n_boot": dist["n_boot"],
            "n_invalid_delta_b1": dist["n_invalid_delta_b1"],
            "n_invalid_delta_b3": dist["n_invalid_delta_b3"],
            "n_invalid_delta_b2": dist["n_invalid_delta_b2"],
            "seed": dist["seed"],
            "universe_n_sessions": dist["n_sessions"],
            "ci": {
                "delta_b1": [_r(ci["delta_b1"][0]), _r(ci["delta_b1"][1])],
                "delta_b3": [_r(ci["delta_b3"][0]), _r(ci["delta_b3"][1])],
                "delta_b2": [_r(ci["delta_b2"][0]), _r(ci["delta_b2"][1])],
            },
        },
        "a_gate": gate.to_dict(),
        "provenance": prov,
        "step0_summary_sha256": step0_sha,
        "artifact_sha256_verified": True,
    }
    _write_json(impl_root / _SUMMARY_PATH, summary)
    trigger_table.to_parquet(impl_root / _TRIGGER_TABLE_PATH, index=False)
    np.savez(
        impl_root / _BOOTSTRAP_PATH,
        delta_b1=dist["delta_b1"], delta_b3=dist["delta_b3"], delta_b2=dist["delta_b2"],
        n_boot=dist["n_boot"], seed=dist["seed"],
    )
    _write_outcome_report(impl_root, summary)

    s.update(
        {
            "status": "CONSUMED",
            "formal_verdict": gate.verdict,
            "formal_exposure_completed_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "outcome_report": str((impl_root / _REPORT_PATH).as_posix()),
            "once_only": True,
        }
    )
    _write_sentinel(impl_root, s)

    manifest = {
        "experiment_id": FROZEN.experiment_id,
        "protocol_version": FROZEN.protocol_version,
        "summary": str((impl_root / _SUMMARY_PATH).as_posix()),
        "sentinel": str((impl_root / _SENTINEL_PATH).as_posix()),
        "report": str((impl_root / _REPORT_PATH).as_posix()),
        "step0_summary": str(step0_path.as_posix()),
        "artifacts": step0["artifacts"]["paths"],
        "artifact_sha256": step0["artifacts"]["sha256"],
        "trigger_table": str((impl_root / _TRIGGER_TABLE_PATH).as_posix()),
        "bootstrap_deltas": str((impl_root / _BOOTSTRAP_PATH).as_posix()),
        "implementation_code_sha": locked_impl,
        "formal_code_sha": prov["code_sha"],
        "worktree_clean": prov["worktree_clean"],
        "once_only": True,
        "exit_code": p2_1a_exit_code(summary),
    }
    _write_json(impl_root / _MANIFEST_PATH, manifest)
    return summary


def p2_1a_exit_code(summary: dict[str, Any]) -> int:
    """A-gate verdict PASS → 0，其余 → 1（fail-closed）。"""
    return 0 if summary["a_gate"]["verdict"] == "PASS" else 1


def read_frozen(impl_root: Path) -> dict[str, Any]:
    path = impl_root / _SUMMARY_PATH
    if not path.exists():
        raise FileNotFoundError(f"P2.1A frozen summary 不存在：{path}")
    return _read_json(path)


def _r(v: float) -> float | None:
    return round(float(v), 6) if v is not None and np.isfinite(v) else None


# ---------------------------------------------------------------------------
# outcome report（v1.3 §4.5；6 条件）
# ---------------------------------------------------------------------------

def _write_outcome_report(impl_root: Path, summary: dict[str, Any]) -> None:
    """v1.3 §4.5：metadata / sufficiency / trigger tables / gain-Δ / CI / verdict（6 条件）。"""
    pm = summary["point_metrics"]
    bt = summary["bootstrap"]
    gate = summary["a_gate"]
    lines: list[str] = []

    lines += [
        "# P2.1A A-gate Outcome Report",
        "",
        f"- experiment_id：{summary['experiment_id']}",
        f"- protocol_version：{summary['protocol_version']}",
        f"- 数据：{summary['data']}",
        f"- implementation_code_sha：{summary['implementation_code_sha']}",
        f"- formal_code_sha：{summary['provenance']['code_sha']}",
        f"- worktree_clean：{summary['provenance']['worktree_clean']}",
        f"- step0_summary_sha256：{summary['step0_summary_sha256']}",
        f"- artifact_sha256_verified：{summary['artifact_sha256_verified']}",
        "",
        "## (2) Sufficiency",
        "",
        f"- eligible M3 segments：{summary['sufficiency']['n_eligible_segments']}"
        f"（要求 ≥ {summary['sufficiency']['min_eligible_segments']}）",
    ]
    for method, n in summary["sufficiency"]["trigger_distinct_sessions"].items():
        lines.append(
            f"- trigger distinct sessions {method}：{n}"
            f"（要求 ≥ {summary['sufficiency']['min_trigger_sessions']}）"
        )
    lines += ["", "## (3) Trigger counts", ""]
    for method, n in sorted(pm["n_triggers"].items()):
        lines.append(f"- {method}：{n} 个 segment 触发")
    lines += ["", "## (4) Point estimates（gain / coverage / latency）", ""]
    header = "| method | gain | coverage | latency(cycle) | n_triggers |"
    lines += [header, "|---|---|---|---|---|"]
    for method in sorted(pm["gains"].keys()):
        lines.append(
            f"| {method} | {_fmt(pm['gains'][method])} | {_fmt(pm['coverage'][method])} | "
            f"{_fmt(pm['latency'][method])} | {pm['n_triggers'][method]} |"
        )
    lines += ["", "| Δ | point |", "|---|---|"]
    lines.append(f"| Δ(B1)=gain(B0)−gain(B1) | {_fmt(pm['delta_b1'])} |")
    lines.append(f"| Δ(B3)=gain(B0)−gain(B3) | {_fmt(pm['delta_b3'])} |")
    lines.append(f"| Δ(B2)=gain(B0)−max(gain(B2a),gain(B2b)) | {_fmt(pm['delta_b2'])} |")
    g_b0, g_b4 = pm["gains"]["B0"], pm["gains"]["B4"]
    b4_delta = _fmt(g_b0 - g_b4) if (g_b0 is not None and g_b4 is not None) else "n/a"
    lines.append(f"| gain(B0)−gain(B4)（null control sanity，正式条件 c3） | {b4_delta} |")
    lines += ["", "## (5) Bootstrap CI（session cluster，percentile 95%，N=2000）", ""]
    lines += [
        f"- universe：全部 eligible session（n={bt['universe_n_sessions']}），"
        "非『仅含 trigger 的 session』"
    ]
    lines += ["| Δ | CI_lower | CI_upper |", "|---|---|---|"]
    lines.append(f"| Δ(B1) | {_fmt(bt['ci']['delta_b1'][0])} | {_fmt(bt['ci']['delta_b1'][1])} |")
    lines.append(f"| Δ(B3) | {_fmt(bt['ci']['delta_b3'][0])} | {_fmt(bt['ci']['delta_b3'][1])} |")
    lines.append(f"| Δ(B2) | {_fmt(bt['ci']['delta_b2'][0])} | {_fmt(bt['ci']['delta_b2'][1])} |")
    lines.append(
        f"- 无效 replicate：ΔB1={bt['n_invalid_delta_b1']}，ΔB3={bt['n_invalid_delta_b3']}，"
        f"ΔB2={bt['n_invalid_delta_b2']}（方法 0 trigger 的 replicate 不计入分位数）"
    )
    lines += ["", "## (6) A-gate Verdict（6 条件，C1 穷尽）", ""]
    lines.append(f"**verdict：`{gate['verdict']}`**（PASS=6 条件全成立；FAIL=任一不成立）")
    lines += [""]
    cond_order = (
        "c1_delta_b1", "c2_delta_b3", "c3_b4_dominance",
        "c4_coverage_ni", "c5_latency_ni", "c6_delta_b2",
    )
    for cond in cond_order:
        ok = gate["conditions"][cond]
        det = gate["condition_details"][cond]
        lines.append(f"- **{cond}**：`{'PASS' if ok else 'FAIL'}`　{det}")
    if gate["failed_conditions"]:
        lines += ["", "失败条件：", ""]
        for fc in gate["failed_conditions"]:
            lines.append(f"- {fc}")
    report_path = impl_root / _REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    try:
        f = float(v)
        if not np.isfinite(f):
            return "n/a"
        return f"{f:.6g}"
    except (TypeError, ValueError):
        return str(v)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    impl_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="P2.1A Step-0 + A-gate formal runner")
    parser.add_argument("--lock-impl", action="store_true",
                        help="锁 implementation_code_sha（Implementation Review PASS 后）")
    parser.add_argument("--step0", action="store_true", help="Step-0 data sufficiency（只读计数）")
    parser.add_argument("--formal-test", action="store_true", help="正式 A-gate exposure（单次）")
    parser.add_argument("--read-frozen", action="store_true", help="只读已冻结 summary")
    parser.add_argument("--exit-code", action="store_true", help="输出 exit code（不写盘）")
    args = parser.parse_args()

    if args.exit_code:
        if not (impl_root / _SUMMARY_PATH).exists():
            sys.exit(1)
        sys.exit(p2_1a_exit_code(read_frozen(impl_root)))

    if args.read_frozen:
        print(json.dumps(read_frozen(impl_root), ensure_ascii=False, indent=2))
        return

    if args.lock_impl:
        s = lock_implementation(impl_root)
        print(json.dumps(
            {"implementation_code_sha": s.get("implementation_code_sha"),
             "implementation_locked_at": s.get("implementation_locked_at")},
            ensure_ascii=False, indent=2,
        ))
        return

    if args.step0:
        step0 = run_step0(impl_root)
        print(json.dumps(step0["sufficiency"], ensure_ascii=False, indent=2))
        return

    if args.formal_test:
        summary = run_formal_test(impl_root)
        print(json.dumps(summary["a_gate"], ensure_ascii=False, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
