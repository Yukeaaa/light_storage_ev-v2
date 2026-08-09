"""R1 E1 runner 治理测试（审查结论26）：正式门退出码与 provenance。

覆盖：
- formal_exit_code：PASS summary → 0；FAIL summary → 1（P0：FAIL 不得返回 0）；
- 不存在的 verdict / 非 PASS → 非 0（fail-closed，防未来字段改名静默放过）。
纯合成 summary，不触真实数据、不重跑 E1 test。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from patent_preexperiment.e1_full.gate import formal_exit_code


def _summary(verdict: str) -> dict:
    return {"r1_verdict_on_test": {"verdict": verdict, "test_gates": {}, "test_core_rate": 0.0}}


def test_exit_code_pass_is_zero() -> None:
    assert formal_exit_code(_summary("PASS")) == 0


def test_exit_code_fail_is_one() -> None:
    assert formal_exit_code(_summary("FAIL")) == 1


@pytest.mark.parametrize("bad", ["", "pass", "True", None, "UNKNOWN"])
def test_exit_code_non_pass_is_one(bad: str | None) -> None:
    assert formal_exit_code(_summary(bad)) == 1


def test_exit_code_missing_verdict_is_one() -> None:
    with pytest.raises(KeyError):
        formal_exit_code({"r1_verdict_on_test": {}})


def test_git_provenance_reports_repo_state() -> None:
    from patent_preexperiment.e1_full.gate import git_provenance

    pp = Path(__file__).resolve().parents[1]
    prov = git_provenance(pp)
    assert "code_sha" in prov
    assert len(prov["code_sha"]) == 40


def test_git_provenance_unknown_for_bad_repo() -> None:
    from patent_preexperiment.e1_full.gate import git_provenance

    prov = git_provenance(Path(__file__).resolve().parents[0] / "does_not_exist")
    assert prov["code_sha"] == "unknown"
    assert prov["worktree_clean"] is None
