"""R1 E1 runner 治理测试（审查结论26/27）：正式门退出码、provenance 与重跑锁。

覆盖：
- formal_exit_code：PASS summary → 0；FAIL summary → 1（P0：FAIL 不得返回 0）；
- 不存在的 verdict / 非 PASS → 非 0（fail-closed，防未来字段改名静默放过）；
- assert_formal_test_not_exposed：无 exposure → 放行；有 exposure → 硬 STOP（P0）；
- frozen_gate_exit_code：只读冻结 summary 返回门判定，不重算；
- run_e1_full 正式入口第一行执行重跑锁（exposure 存在时任何计算前直接拒绝）。
纯合成 summary，不触真实数据、不重跑 E1 test。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from patent_preexperiment.e1_full.gate import (
    assert_formal_test_not_exposed,
    formal_exit_code,
    frozen_gate_exit_code,
)


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


def test_rerun_lock_allows_when_no_exposure(tmp_path: Path) -> None:
    assert_formal_test_not_exposed(tmp_path / "missing_provenance.json")


def test_rerun_lock_allows_when_provenance_without_exposure(tmp_path: Path) -> None:
    p = tmp_path / "provenance.json"
    p.write_text(json.dumps({"record_type": "plan"}), encoding="utf-8")
    assert_formal_test_not_exposed(p)


def test_rerun_lock_blocks_when_exposed(tmp_path: Path) -> None:
    p = tmp_path / "provenance.json"
    p.write_text(json.dumps({"formal_test_exposure": "44fa88c"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="rerun prohibited"):
        assert_formal_test_not_exposed(p)


def test_rerun_lock_blocks_before_any_computation(tmp_path: Path) -> None:
    """run_e1_full 正式入口第一行必须执行重跑锁：exposure 存在即拒绝，不产生任何输出。"""
    import importlib.util

    run_py = (
        Path(__file__).resolve().parents[1]
        / "experiments" / "e1_full" / "run.py"
    )
    spec = importlib.util.spec_from_file_location("e1_full_run", run_py)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["e1_full_run"] = mod
    spec.loader.exec_module(mod)

    provenance = tmp_path / "provenance.json"
    provenance.write_text(
        json.dumps({"formal_test_exposure": "44fa88c"}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="rerun prohibited"):
        mod.run_e1_full(provenance_path=provenance)
    assert set(tmp_path.iterdir()) == {provenance}


def test_frozen_gate_exit_code_reads_frozen_summary(tmp_path: Path) -> None:
    p = tmp_path / "summary.json"
    p.write_text(json.dumps(_summary("FAIL")), encoding="utf-8")
    assert frozen_gate_exit_code(p) == 1


def test_frozen_gate_exit_code_pass(tmp_path: Path) -> None:
    p = tmp_path / "summary.json"
    p.write_text(json.dumps(_summary("PASS")), encoding="utf-8")
    assert frozen_gate_exit_code(p) == 0


def test_frozen_gate_exit_code_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        frozen_gate_exit_code(tmp_path / "nope.json")
