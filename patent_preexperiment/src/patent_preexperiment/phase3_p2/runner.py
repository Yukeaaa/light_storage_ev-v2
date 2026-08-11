"""P2 正式 test runner（Phase 3 v1.0.2 §5.8；formal exposure 单次 + sentinel 锁死）。

执行序列（镜像 P1 Review 55/56/57/63 纪律）：
    --step0          : K1/K2/K3 kill gates（JPL train natural + 固定 Caltech replay）。
                       Step0 不是 formal exposure，可重跑；但 step0 evidence 是 formal
                       前置 artifact，必须与正式门一样在 clean committed worktree 上产出
                       （X1 规则），正式门用其 code_sha 做两侧闭合。
    --formal-test    : 单次 exposure。sentinel 在读取 test outcome **之前**写入；
                       硬门：sentinel 不存在 + step0 evidence code_sha 匹配当前 + 两侧
                       clean worktree + step0 summary sha256 运行前后一致（防被替换）。
                       完成后 sentinel 存在即视为 consumed，永久禁止重跑（Review 63）。
    --read-frozen    : 只读已冻结 test summary / manifest / exit code，绝不重算。
    --exit-code      : step0 verdict == PROCEED → 0；STOP/PROJECT_NO_GO → 1（fail-closed）。

formal test 池（只含 matched 会话，不做 replay —— replay 是 train-side 机制证据，
不是 test outcome）：
    - jpl_test_current_only      ：JPL test 主口径（约 90% 文件 current-only）。
    - caltech_test_measured_pilot：Caltech test 主口径（pilot 实测，M2/M4 分支）。
    - caltech_test_current_only  ：L0 传感器降级 stress（同站 current-only，M3/M4 分支）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.e1_full.gate import git_provenance
from patent_preexperiment.phase3_p2.pipeline import (
    ReplayTransform,
    load_pool_minutes,
    process_pool,
    seeds_for_pool,
)
from patent_preexperiment.phase3_p2.schema import load_schema
from patent_preexperiment.phase3_p2.step0 import NATURAL, run_step0, write_step0_evidence

_STEP0_SUMMARY_PATH = "results/raw/phase3_p2/p2_step0_summary.json"
_SENTINEL_PATH = "results/raw/phase3_p2/p2_test_sentinel.json"
_SUMMARY_PATH = "results/raw/phase3_p2/p2_test_summary.json"
_MANIFEST_PATH = "results/raw/phase3_p2/p2_manifest.json"
_TRACES_PATH = "results/raw/phase3_p2/p2_test_traces.parquet"


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def p2_exit_code(summary: dict[str, Any]) -> int:
    """P2 正式门退出码：step0 verdict == PROCEED → 0，否则 1（fail-closed）。"""
    return 0 if summary.get("step0_verdict") == "PROCEED" else 1


def run_step0_cli(impl_root: Path, *, chunk_sessions: int = 800) -> dict[str, Any]:
    """Step0 CLI 入口：hard gate = clean committed worktree（X1），然后计算并落盘。"""
    prov = git_provenance(impl_root.parent)
    if prov["code_sha"] == "unknown" or prov.get("worktree_clean") is not True:
        raise RuntimeError(
            "P2 hard gate（step0）：step0 evidence 只允许在 clean committed worktree 上"
            f"产出，当前 code_sha={prov['code_sha']!r}, "
            f"worktree_clean={prov.get('worktree_clean')!r}；先 commit 冻结代码再跑"
        )
    summary = run_step0(impl_root, chunk_sessions=chunk_sessions)
    assert summary["provenance"]["code_sha"] == prov["code_sha"]
    json_path, report_path = write_step0_evidence(impl_root, summary)
    summary["evidence_files"] = {
        "summary": str(json_path.as_posix()),
        "report": str(report_path.as_posix()),
    }
    _write_json(json_path, summary)
    return summary


def run_formal_test(impl_root: Path, *, chunk_sessions: int = 800) -> dict[str, Any]:
    """正式 test：单次 exposure，after 锁死。sentinel 先于读取 test outcome 写入。"""
    scfg = load_schema(impl_root / "configs" / "phase3_p2_action_schema.yaml")

    step0_path = impl_root / _STEP0_SUMMARY_PATH
    if not step0_path.exists():
        raise FileNotFoundError("P2 formal test 前必须先跑 --step0")
    step0_sha = _file_sha256(step0_path)

    sentinel_path = impl_root / _SENTINEL_PATH
    if sentinel_path.exists():
        # Review 63 P0：sentinel 是 exposure boundary——存在即 consumed，永久禁止重跑
        raise RuntimeError(
            "P2 formal test sentinel already exists; "
            f"formal exposure is consumed and rerun is prohibited (sentinel: {sentinel_path})"
        )

    step0 = _read_json(step0_path)
    prov = git_provenance(impl_root.parent)
    expected_sha = step0["provenance"].get("code_sha")
    if not expected_sha or expected_sha == "unknown":
        raise RuntimeError("P2 hard gate：step0 evidence 时代码 SHA 未知，不能暴露 test")
    if prov["code_sha"] != expected_sha:
        raise RuntimeError(
            f"P2 hard gate：expected code SHA {expected_sha} != current {prov['code_sha']}"
        )
    if prov.get("worktree_clean") is not True:
        raise RuntimeError("P2 hard gate：worktree 不洁净，禁止暴露 formal test")
    if step0["provenance"].get("worktree_clean") is not True:
        raise RuntimeError("P2 hard gate：step0 evidence 并非在 clean worktree 上产出，禁止暴露")
    if step0["step0_verdict"] not in ("PROCEED", "STOP", "PROJECT_NO_GO"):
        raise RuntimeError(f"P2 hard gate：step0_verdict 异常：{step0['step0_verdict']!r}")

    # sentinel 在读取 test outcome 之前写入（Review 56 check-4）
    sentinel = {
        "status": "running",
        "started_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "expected_code_sha": expected_sha,
        "code_sha": prov["code_sha"],
        "worktree_clean": prov["worktree_clean"],
        "step0_summary_sha256": step0_sha,
        "step0_verdict": step0["step0_verdict"],
        "integrity": "step0 summary sha recorded pre-exposure; rechecked pre-write",
        "exposed_sha": None,
    }
    _write_json(sentinel_path, sentinel)

    registry = pd.read_parquet(impl_root / "data_registry" / "e0_full_split_registry.parquet")
    minute_root = impl_root / "datasets" / "session_response_1min"
    pools: dict[str, pd.DataFrame] = {}
    pool_meta: dict[str, dict[str, Any]] = {}
    for name, site, field_mode, split in [
        ("jpl_test_current_only", "jpl", "current_only", "test"),
        ("caltech_test_measured_pilot", "caltech", "measured_pilot", "test"),
        ("caltech_test_current_only", "caltech", "current_only", "test"),
    ]:
        pool = load_pool_minutes(minute_root, registry, site=site, field_mode=field_mode, split=split)
        pools[name] = pool
        pool_meta[name] = {
            "site": site,
            "field_mode": field_mode,
            "split": split,
            "n_sessions": int(pool["session_id"].nunique()),
            "n_minutes": int(len(pool)),
        }

    summaries: dict[str, dict[str, Any]] = {}
    traces_frames: list[pd.DataFrame] = []
    for name, pool in pools.items():
        pool_summary, traces = process_pool(
            pool, scfg, seeds_for_pool(pool), ReplayTransform(name=NATURAL),
            chunk_sessions=chunk_sessions,
        )
        summaries[name] = pool_summary
        if not traces.empty:
            traces_frames.append(traces.assign(pool=name))
    trace_df = pd.concat(traces_frames, ignore_index=True) if traces_frames else pd.DataFrame()

    # step0 evidence 运行期间被替换 → fail-closed（sentinel 记 aborted）
    if _file_sha256(step0_path) != step0_sha:
        sentinel.update({"status": "aborted", "reason": "step0_summary_sha256 changed mid-run"})
        _write_json(sentinel_path, sentinel)
        raise RuntimeError(
            "P2 hard gate（integrity）：formal 运行期间 step0 evidence 被替换，结果未落盘"
        )

    summary = {
        "experiment_id": scfg.experiment_id,
        "protocol_version": scfg.protocol_version,
        "scope": "P2 formal test（单次 exposure；test 池只做 natural，不做 replay）",
        "step0_verdict": step0["step0_verdict"],
        "kill_gates_verdicts": step0["kill_gates"],
        "pools": pool_meta,
        "pool_summaries": summaries,
        "traces": {
            "path": str(Path(_TRACES_PATH).as_posix()),
            "n_total": int(len(trace_df)),
            "n_complete": int(trace_df["complete"].sum()) if not trace_df.empty else 0,
        },
        "provenance": prov,
        "step0_summary_sha256": step0_sha,
    }
    _write_json(impl_root / _SUMMARY_PATH, summary)
    trace_df.to_parquet(impl_root / _TRACES_PATH, index=False)

    sentinel.update({"status": "completed", "exposed_sha": prov["code_sha"]})
    _write_json(sentinel_path, sentinel)

    manifest = {
        "experiment_id": scfg.experiment_id,
        "protocol_version": scfg.protocol_version,
        "batch": "p2_formal",
        "summary": str(Path(_SUMMARY_PATH).as_posix()),
        "sentinel": str(Path(_SENTINEL_PATH).as_posix()),
        "step0_summary": str(Path(_STEP0_SUMMARY_PATH).as_posix()),
        "traces": str(Path(_TRACES_PATH).as_posix()),
        "step0_summary_sha256": step0_sha,
        "step0_verdict": step0["step0_verdict"],
        "code_sha": prov["code_sha"],
        "worktree_clean": prov["worktree_clean"],
        "once_only": True,
        "exit_code": p2_exit_code(summary),
    }
    _write_json(impl_root / _MANIFEST_PATH, manifest)
    return summary


def read_frozen(impl_root: Path) -> dict[str, Any]:
    """只读已冻结 test summary，绝不重算、不写任何输出。"""
    summary_path = impl_root / _SUMMARY_PATH
    if not summary_path.exists():
        raise FileNotFoundError(f"P2 frozen summary 不存在：{summary_path}")
    return _read_json(summary_path)


def main() -> None:
    import argparse

    impl_root = Path(__file__).resolve().parents[3]

    parser = argparse.ArgumentParser(description="P2 kill gates + formal test runner")
    parser.add_argument("--step0", action="store_true", help="跑 K1/K2/K3 kill gates")
    parser.add_argument("--formal-test", action="store_true", help="正式 test（单次 exposure）")
    parser.add_argument("--read-frozen", action="store_true", help="只读已冻结 summary")
    parser.add_argument("--exit-code", action="store_true", help="输出 exit code（不写盘）")
    parser.add_argument("--chunk-sessions", type=int, default=800)
    args = parser.parse_args()

    if args.exit_code:
        import sys

        if not (impl_root / _SUMMARY_PATH).exists():
            sys.exit(1)
        sys.exit(p2_exit_code(read_frozen(impl_root)))

    if args.read_frozen:
        summary = read_frozen(impl_root)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.step0:
        run_step0_cli(impl_root, chunk_sessions=args.chunk_sessions)
        print(f"step0 done: {impl_root / _STEP0_SUMMARY_PATH}")
        return

    if args.formal_test:
        summary = run_formal_test(impl_root, chunk_sessions=args.chunk_sessions)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
