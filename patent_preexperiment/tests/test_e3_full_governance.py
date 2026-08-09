"""E3-Full 治理测试（审查结论29 P0-1/P0-2）：once-only sentinel 状态机 + clean/SHA hard gate。

覆盖：
- assert_formal_test_not_started_or_exposed：absent → 通过；state∈{started,completed} → STOP；
  formal_test_exposure 非空 → STOP（即使 state 缺失）。
- write_started_sentinel：写 state=started；之后 assert 硬拒（模拟崩溃后不获第二次 test）。
- seal_completed：state=completed + formal_test_exposure 填充。
- assert_clean_and_sha：code_sha=unknown → STOP；!=expected → STOP；worktree 非 clean → STOP；
  全满足 → 通过。
- 端到端：absent → started → assert 硬拒 → completed → assert 硬拒。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patent_preexperiment.e3_full.gate import (
    assert_clean_and_sha,
    assert_formal_test_not_started_or_exposed,
    seal_completed,
    write_started_sentinel,
)


def _write_prov(p: Path, payload: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_assert_passes_when_absent(tmp_path: Path) -> None:
    p = tmp_path / "prov.json"
    assert_formal_test_not_started_or_exposed(p)  # 不存在 → 通过


def test_assert_rejects_started(tmp_path: Path) -> None:
    p = tmp_path / "prov.json"
    _write_prov(p, {"state": "started"})
    with pytest.raises(RuntimeError, match="started"):
        assert_formal_test_not_started_or_exposed(p)


def test_assert_rejects_completed(tmp_path: Path) -> None:
    p = tmp_path / "prov.json"
    _write_prov(p, {"state": "completed"})
    with pytest.raises(RuntimeError, match="completed"):
        assert_formal_test_not_started_or_exposed(p)


def test_assert_rejects_exposure_even_without_state(tmp_path: Path) -> None:
    p = tmp_path / "prov.json"
    _write_prov(p, {"formal_test_exposure": "abc123"})
    with pytest.raises(RuntimeError, match="exposed"):
        assert_formal_test_not_started_or_exposed(p)


def test_write_started_then_assert_rejects(tmp_path: Path) -> None:
    """P0-1 核心：写 started sentinel 后，即使'崩溃'（无 completed），下次也硬拒。"""
    p = tmp_path / "prov.json"
    write_started_sentinel(p, {"code_sha": "abc123"})
    with pytest.raises(RuntimeError, match="started"):
        assert_formal_test_not_started_or_exposed(p)


def test_seal_completed_sets_state_and_exposure(tmp_path: Path) -> None:
    p = tmp_path / "prov.json"
    write_started_sentinel(p, {"code_sha": "abc123"})
    seal_completed(p, {"code_sha": "abc123"}, {"code_sha": "abc123", "worktree_clean": True})
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["state"] == "completed"
    assert payload["formal_test_exposure"] == "abc123"


def test_end_to_end_once_only(tmp_path: Path) -> None:
    """absent → started → 硬拒 → completed → 硬拒。"""
    p = tmp_path / "prov.json"
    assert_formal_test_not_started_or_exposed(p)  # absent OK
    write_started_sentinel(p, {"code_sha": "s1"})
    with pytest.raises(RuntimeError, match="started"):
        assert_formal_test_not_started_or_exposed(p)  # 崩溃后不获第二次
    seal_completed(p, {"code_sha": "s1"}, {"code_sha": "s1", "worktree_clean": True})
    with pytest.raises(RuntimeError, match="completed"):
        assert_formal_test_not_started_or_exposed(p)  # 完成后永拒


# ---- P0-2: assert_clean_and_sha hard gate ----


def test_assert_clean_sha_passes(tmp_path: Path) -> None:
    prov = {"code_sha": "abc123", "worktree_clean": True}
    assert_clean_and_sha(prov, "abc123")  # 全满足 → 通过


def test_assert_clean_sha_rejects_unknown() -> None:
    prov = {"code_sha": "unknown", "worktree_clean": True}
    with pytest.raises(RuntimeError, match="git 溯源不可用"):
        assert_clean_and_sha(prov, "abc123")


def test_assert_clean_sha_rejects_sha_mismatch() -> None:
    prov = {"code_sha": "wrong", "worktree_clean": True}
    with pytest.raises(RuntimeError, match="!= 最终 code-only SHA"):
        assert_clean_and_sha(prov, "abc123")


def test_assert_clean_sha_rejects_dirty_worktree() -> None:
    prov = {"code_sha": "abc123", "worktree_clean": False}
    with pytest.raises(RuntimeError, match="worktree 非洁净"):
        assert_clean_and_sha(prov, "abc123")


def test_assert_clean_sha_rejects_none_clean() -> None:
    prov = {"code_sha": "abc123", "worktree_clean": None}
    with pytest.raises(RuntimeError, match="worktree 非洁净"):
        assert_clean_and_sha(prov, "abc123")


def test_assert_clean_sha_skip_clean_when_disabled() -> None:
    prov = {"code_sha": "abc123", "worktree_clean": False}
    assert_clean_and_sha(prov, "abc123", require_clean=False)  # 不要求 clean → 通过
