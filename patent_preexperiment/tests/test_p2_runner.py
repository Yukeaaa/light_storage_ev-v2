"""P2 runner 治理单测：exit code（fail-closed）、sentinel 一次性锁、只读冻结。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from patent_preexperiment.phase3_p2.runner import (
    _SENTINEL_PATH,
    _STEP0_SUMMARY_PATH,
    p2_exit_code,
    read_frozen,
    run_formal_test,
)

PP = Path(__file__).resolve().parents[1]


def test_p2_exit_code_fail_closed() -> None:
    assert p2_exit_code({"step0_verdict": "PROCEED"}) == 0
    assert p2_exit_code({"step0_verdict": "STOP"}) == 1
    assert p2_exit_code({"step0_verdict": "PROJECT_NO_GO"}) == 1
    # 缺失/异常 verdict 一律 fail-closed
    assert p2_exit_code({}) == 1
    assert p2_exit_code({"step0_verdict": "RUN_ANYWAY"}) == 1


def _fake_impl(tmp_path: Path) -> Path:
    """构造含 step0 evidence + configs 的临时 impl root（无 registry/minutes）。"""
    impl = tmp_path / "impl"
    (impl / "configs").mkdir(parents=True)
    (impl / "results" / "raw" / "phase3_p2").mkdir(parents=True)
    shutil.copyfile(
        PP / "configs" / "phase3_p2_action_schema.yaml",
        impl / "configs" / "phase3_p2_action_schema.yaml",
    )
    step0 = {
        "step0_verdict": "PROCEED",
        "provenance": {"code_sha": "unknown", "worktree_clean": None},
    }
    (impl / _STEP0_SUMMARY_PATH).write_text(
        json.dumps(step0, ensure_ascii=False), encoding="utf-8"
    )
    return impl


def test_run_formal_test_requires_step0_evidence(tmp_path: Path) -> None:
    impl = tmp_path / "impl2"
    (impl / "configs").mkdir(parents=True)
    shutil.copyfile(
        PP / "configs" / "phase3_p2_action_schema.yaml",
        impl / "configs" / "phase3_p2_action_schema.yaml",
    )
    with pytest.raises(FileNotFoundError, match="必须先跑 --step0"):
        run_formal_test(impl)


def test_run_formal_test_sentinel_blocks_rerun(tmp_path: Path) -> None:
    """sentinel 存在（consumed）即永久禁止重跑（Review 63 P0）。"""
    impl = _fake_impl(tmp_path)
    (impl / _SENTINEL_PATH).write_text(
        json.dumps({"status": "completed", "exposed_sha": "abc"}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="sentinel already exists"):
        run_formal_test(impl)


def test_read_frozen_missing_stops(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="不存在"):
        read_frozen(tmp_path / "impl_missing")
