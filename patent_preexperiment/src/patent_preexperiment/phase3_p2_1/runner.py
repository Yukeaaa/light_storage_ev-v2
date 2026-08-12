"""P2.1A formal runner（v1.3 §7 执行顺序）——Step-0 只读 sufficiency + 单次 A-gate exposure。

执行序列（镜像 P2 runner 纪律）：
    --step0        : 构建 eligible / B3 map / trigger counts（**全部不读 Y/gain/Δ/CI**），
                     只输出 sufficiency 计数（§5）。可重跑（非 formal exposure），
                     但必须在 clean committed worktree 上产出（X1）。
    --formal-test  : 单次 exposure。前置：sentinel==UNCONSUMED + step0 SUFFICIENT +
                     step0 sha 稳定 + code_sha 匹配 + 双侧 clean worktree。
                     sentinel 在读取 outcome 之前写入并锁定 code_sha（§7 [6]）；
                     完成后 sentinel → CONSUMED，永久禁止重跑（once_only）。
    --read-frozen  : 只读已冻结 summary，绝不重算。
    --exit-code    : A-gate PASS → 0，FAIL/DATA_INSUFFICIENT → 1（fail-closed）。

数据：E0 minutes JPL train current_only（matched，v1.3 §8）；无合成、无重采样。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.e1_full.gate import git_provenance
from patent_preexperiment.phase3_p2.pipeline import load_pool_minutes
from patent_preexperiment.phase3_p2.schema import load_schema
from patent_preexperiment.phase3_p2_1.b3_map import build_b3_map, load_b3_map, save_b3_map
from patent_preexperiment.phase3_p2_1.bootstrap import (
    bootstrap_delta_distributions,
    percentile_ci,
)
from patent_preexperiment.phase3_p2_1.frozen import FROZEN
from patent_preexperiment.phase3_p2_1.gate import a_gate_verdict
from patent_preexperiment.phase3_p2_1.metrics import (
    build_trigger_counts,
    build_trigger_table,
    point_metrics,
)
from patent_preexperiment.phase3_p2_1.outcome import compute_y
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


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _update_sentinel(impl_root: Path, **fields: Any) -> dict[str, Any]:
    path = impl_root / _SENTINEL_PATH
    payload = _read_json(path) if path.exists() else {
        "experiment_id": FROZEN.experiment_id,
        "protocol_version": FROZEN.protocol_version,
        "status": "UNCONSUMED",
        "once_only": True,
    }
    payload.update(fields)
    _write_json(path, payload)
    return payload


def _load_pool(impl_root: Path) -> tuple[Any, pd.DataFrame]:
    scfg = load_schema(impl_root / "configs" / "phase3_p2_action_schema.yaml")
    registry = pd.read_parquet(impl_root / "data_registry" / "e0_full_split_registry.parquet")
    pool = load_pool_minutes(
        impl_root / "datasets" / "session_response_1min",
        registry,
        site=FROZEN.risk_set_site,
        field_mode=FROZEN.risk_set_field_mode,
        split=FROZEN.risk_set_split,
    )
    return scfg, pool


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
    b3_map = build_b3_map(eligible)
    trigger_counts = build_trigger_counts(eligible, masks_elig, b3_map)

    out_dir = impl_root / "results" / "raw" / "phase3_p2_1"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "boundary_frame": out_dir / _BF_PATH.split("/")[-1],
        "eligible": out_dir / _ELIGIBLE_PATH.split("/")[-1],
        "b3_map": out_dir / _B3MAP_PATH.split("/")[-1],
        "trigger_counts": out_dir / _TRIGGER_COUNTS_PATH.split("/")[-1],
    }
    bf[_BF_KEEP].to_parquet(paths["boundary_frame"], index=False)
    eligible.to_parquet(paths["eligible"], index=False)
    save_b3_map(b3_map, paths["b3_map"])
    trigger_counts.to_parquet(paths["trigger_counts"], index=False)
    return {
        "paths": {k: str(v.as_posix()) for k, v in paths.items()},
        "sha256": {k: _file_sha256(v) for k, v in paths.items()},
    }


def run_step0(impl_root: Path) -> dict[str, Any]:
    """Step-0：只读 eligible/trigger counts（§5 sufficiency）。禁止读 Y/gain/Δ/CI。"""
    prov = git_provenance(impl_root.parent)
    if prov["code_sha"] == "unknown" or prov.get("worktree_clean") is not True:
        raise RuntimeError(
            "P2.1A hard gate（step0）：step0 evidence 只允许在 clean committed worktree 上"
            f"产出，当前 code_sha={prov['code_sha']!r}, "
            f"worktree_clean={prov.get('worktree_clean')!r}"
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
        "provenance": prov,
    }
    _write_json(impl_root / _STEP0_PATH, step0)
    _update_sentinel(
        impl_root,
        status="UNCONSUMED",
        step0_data_sufficiency_status="SUFFICIENT" if suff.sufficient else "INSUFFICIENT",
        step0_summary_sha256=_file_sha256(impl_root / _STEP0_PATH),
        step0_artifacts=artifacts["paths"],
        step0_counts={
            "n_eligible_segments": suff.n_eligible_segments,
            "trigger_distinct_sessions": dict(suff.trigger_sessions),
        },
    )
    return step0


def _load_step0(impl_root: Path) -> dict[str, Any]:
    path = impl_root / _STEP0_PATH
    if not path.exists():
        raise FileNotFoundError("P2.1A formal test 前必须先跑 --step0")
    return _read_json(path)


def run_formal_test(impl_root: Path) -> dict[str, Any]:
    """正式 A-gate exposure：单次；sentinel 先锁 code_sha 再读 outcome（§7 [6]）。"""
    sentinel_path = impl_root / _SENTINEL_PATH
    if sentinel_path.exists():
        sentinel_now = _read_json(sentinel_path)
        if sentinel_now.get("status") != "UNCONSUMED":
            raise RuntimeError(
                "P2.1A formal exposure already consumed "
                f"(sentinel status={sentinel_now.get('status')!r}); rerun prohibited (once_only)"
            )
    else:
        raise RuntimeError("P2.1A sentinel 缺失，禁止 formal exposure（先建 sentinel）")

    step0 = _load_step0(impl_root)
    if not step0["sufficiency"]["sufficient"]:
        raise RuntimeError(
            "P2.1A hard gate：DATA INSUFFICIENT，停在 Step-0，禁止 formal exposure"
        )
    step0_path = impl_root / _STEP0_PATH
    step0_sha = _file_sha256(step0_path)
    if step0_sha != sentinel_now.get("step0_summary_sha256"):
        raise RuntimeError(
            "P2.1A hard gate：step0 summary sha 与 sentinel 记录不一致，禁止 exposure"
        )
    expected_sha = step0["provenance"].get("code_sha")
    prov = git_provenance(impl_root.parent)
    if not expected_sha or expected_sha == "unknown":
        raise RuntimeError("P2.1A hard gate：step0 evidence 时代码 SHA 未知")
    if prov["code_sha"] != expected_sha:
        raise RuntimeError(
            f"P2.1A hard gate：expected {expected_sha} != current {prov['code_sha']}"
        )
    if prov.get("worktree_clean") is not True:
        raise RuntimeError("P2.1A hard gate：worktree 不洁净，禁止暴露 formal test")

    # sentinel 在读取 test outcome 之前写入并锁定 code_sha
    _update_sentinel(
        impl_root,
        status="RUNNING",
        code_sha=prov["code_sha"],
        code_sha_locked=True,
        worktree_clean_at_code_lock=prov["worktree_clean"],
        formal_exposure_started_at=pd.Timestamp.now(tz="UTC").isoformat(),
        step0_summary_sha256=step0_sha,
        step0_data_sufficiency_status=(
            "SUFFICIENT" if step0["sufficiency"]["sufficient"] else "INSUFFICIENT"
        ),
    )

    # 只加载 Step-0 已冻结 artifact（不重算 masks / eligible / B3 map）
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
        raise RuntimeError("P2.1A fail-closed：eligible 行存在未定义的 Y")
    trigger_table = build_trigger_table(
        trigger_counts, eligible, elig_y.astype(bool)
    )

    n_eligible_segments = int(eligible["segment_id"].nunique())
    point = point_metrics(trigger_table, n_eligible_segments)

    dist = bootstrap_delta_distributions(trigger_table)
    ci = {
        "delta_b1": percentile_ci(dist["delta_b1"]),
        "delta_b3": percentile_ci(dist["delta_b3"]),
        "delta_b2": percentile_ci(dist["delta_b2"]),
    }
    gate = a_gate_verdict(point, ci)

    # step0 evidence 运行期间被替换 → fail-closed
    if _file_sha256(step0_path) != step0_sha:
        _update_sentinel(impl_root, status="ABORTED", reason="step0_summary_sha256 changed mid-run")
        raise RuntimeError("P2.1A hard gate（integrity）：step0 evidence 运行期间被替换，未落盘")

    summary = {
        "experiment_id": FROZEN.experiment_id,
        "protocol_version": FROZEN.protocol_version,
        "scope": "P2.1A A-gate formal exposure（单次；JPL train current_only，不合成）",
        "data": "E0 minutes JPL train current_only（matched）",
        "sufficiency": step0["sufficiency"],
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
            "ci": {
                "delta_b1": [_r(ci["delta_b1"][0]), _r(ci["delta_b1"][1])],
                "delta_b3": [_r(ci["delta_b3"][0]), _r(ci["delta_b3"][1])],
                "delta_b2": [_r(ci["delta_b2"][0]), _r(ci["delta_b2"][1])],
            },
        },
        "a_gate": gate.to_dict(),
        "provenance": prov,
        "step0_summary_sha256": step0_sha,
    }
    _write_json(impl_root / _SUMMARY_PATH, summary)
    trigger_table.to_parquet(impl_root / _TRIGGER_TABLE_PATH, index=False)
    np.savez(
        impl_root / _BOOTSTRAP_PATH,
        delta_b1=dist["delta_b1"], delta_b3=dist["delta_b3"], delta_b2=dist["delta_b2"],
        n_boot=dist["n_boot"], seed=dist["seed"],
    )
    _write_outcome_report(impl_root, summary)

    _update_sentinel(
        impl_root,
        status="CONSUMED",
        formal_verdict=gate.verdict,
        formal_exposure_completed_at=pd.Timestamp.now(tz="UTC").isoformat(),
        outcome_report=str((impl_root / _REPORT_PATH).as_posix()),
        once_only=True,
    )

    manifest = {
        "experiment_id": FROZEN.experiment_id,
        "protocol_version": FROZEN.protocol_version,
        "summary": str((impl_root / _SUMMARY_PATH).as_posix()),
        "sentinel": str((impl_root / _SENTINEL_PATH).as_posix()),
        "report": str((impl_root / _REPORT_PATH).as_posix()),
        "step0_summary": str(step0_path.as_posix()),
        "artifacts": step0["artifacts"]["paths"],
        "trigger_table": str((impl_root / _TRIGGER_TABLE_PATH).as_posix()),
        "bootstrap_deltas": str((impl_root / _BOOTSTRAP_PATH).as_posix()),
        "code_sha": prov["code_sha"],
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


def _write_outcome_report(impl_root: Path, summary: dict[str, Any]) -> None:
    """v1.3 §4.5：metadata / sufficiency / trigger tables / gain-Δ / CI / verdict。"""
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
        f"- code_sha：{summary['provenance']['code_sha']}",
        f"- worktree_clean：{summary['provenance']['worktree_clean']}",
        f"- step0_summary_sha256：{summary['step0_summary_sha256']}",
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
    lines.append(f"| gain(B0)−gain(B4)（monotonic dominance，独立检查） | {b4_delta} |")
    lines += ["", "## (5) Bootstrap CI（session cluster，percentile 95%，N=2000）", ""]
    lines += ["| Δ | CI_lower | CI_upper |", "|---|---|---|"]
    lines.append(f"| Δ(B1) | {_fmt(bt['ci']['delta_b1'][0])} | {_fmt(bt['ci']['delta_b1'][1])} |")
    lines.append(f"| Δ(B3) | {_fmt(bt['ci']['delta_b3'][0])} | {_fmt(bt['ci']['delta_b3'][1])} |")
    lines.append(f"| Δ(B2) | {_fmt(bt['ci']['delta_b2'][0])} | {_fmt(bt['ci']['delta_b2'][1])} |")
    lines.append(
        f"\n- 无效 replicate：ΔB1={bt['n_invalid_delta_b1']}，ΔB3={bt['n_invalid_delta_b3']}，"
        f"ΔB2={bt['n_invalid_delta_b2']}（方法 0 trigger 的 replicate 不计入分位数）"
    )
    lines += ["", "## (6) A-gate Verdict", ""]
    lines.append(f"**verdict：`{gate['verdict']}`**（C1：PASS=CI_lower>0，FAIL=CI_lower<=0）")
    lines += [""]
    for cond in ("c1_delta_b1", "c2_delta_b3", "c3_delta_b2", "c4_coverage_ni", "c5_latency_ni"):
        ok = gate["conditions"][cond]
        det = gate["condition_details"][cond]
        lines.append(f"- **{cond}**：`{'PASS' if ok else 'FAIL'}`　{det}")
    lines.append(
        f"- **b4_dominance**（独立点检查 gain(B0)>gain(B4)）："
        f"{'PASS' if gate['b4_dominance'] else 'FAIL'}　{gate['condition_details']['b4_dominance']}"
    )
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


def main() -> None:
    impl_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="P2.1A Step-0 + A-gate formal runner")
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
