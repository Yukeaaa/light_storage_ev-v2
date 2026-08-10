"""P1 runner 测试（Review 56 检查点 1-7 + Review 57 X1 + Review 58 X1.1 + Review 59 X1.2）：
train-only fit、test loader 隔离、once-only state machine、hard gate、state-missing 短路、
artifact-clean 生命周期闭环、pre-exposure artifact-integrity gate。
用合成数据，不读取真实 test outcome。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest

from patent_preexperiment.p1.runner import (
    _load_split_minutes,
    read_frozen,
    run_fit_train_edges,
    run_formal_test,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_minute_dataset(root: Path, constant_test: bool = False) -> pd.DataFrame:
    """构造 office001 matched 分钟表：S1(train) / S2(validation) / S_TEST(test)。

    constant_test=True 时 S_TEST 恒功率 → recent_var 全 0 → 全 S1 → state_missing。
    """
    rows: list[dict] = []
    for sid, _split, n_min in (
        ("S1", "train", 120), ("S2", "validation", 120), ("S_TEST", "test", 120),
    ):
        t0 = pd.Timestamp("2019-06-01 08:00:00", tz="UTC")
        for m in range(n_min):
            ts = t0 + pd.Timedelta(minutes=m)
            actual = 6.0
            if sid == "S_TEST" and not constant_test:
                actual = 6.0 if m < 100 else 2.0
            if sid != "S_TEST":
                actual = 6.0 if m < 100 else 2.0
            rows.append({
                "session_id": sid,
                "station_id": "PL-0",
                "site": "office001",
                "garage": "Parking_Lot_01",
                "field_mode": "measured_pilot",
                "match_status": "matched",
                "timestamp_utc": ts,
                "actual_power_kw": float(actual),
                "pilot_power_kw": 6.0,
                "current_a": 5.0,
                "pilot_a": 32.0,
                "pilot_available": True,
                "connected_elapsed_min": float(m),
                "minutes_from_end": float(n_min - m),
                "gap_flag": False,
                "severe_gap_before": False,
                "disconnect_time": t0 + pd.Timedelta(minutes=n_min + 1),
                "done_charging_time": t0 + pd.Timedelta(minutes=n_min),
            })
    df = pd.DataFrame(rows)
    out_dir = root / "datasets" / "session_response_1min"
    out_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df), out_dir / "data.parquet")
    return df


def _registry() -> pd.DataFrame:
    return pd.DataFrame({
        "session_id": ["S1", "S2", "S_TEST"],
        "site_canonical": ["office001"] * 3,
        "match_status": ["matched"] * 3,
        "split": ["train", "validation", "test"],
    })


def _fake_git_provenance(monkeypatch, sha: str, clean: bool):
    """把 runner.git_provenance 替换为返回固定 sha/clean 的假实现。"""
    state = {"sha": sha, "clean": clean}

    def _fake(_repo):
        return {"code_sha": state["sha"], "worktree_clean": state["clean"]}

    monkeypatch.setattr("patent_preexperiment.p1.runner.git_provenance", _fake)
    return state


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout.strip()


def test_artifact_lifecycle_clean_worktree_closure(tmp_path: Path):
    """X1.1 集成：真实 git 仓库 + 真实仓库 .gitignore → fit 后 worktree 仍 clean，
    artifact provenance.code_sha == current SHA → formal hard gate 两侧闭合可继续。"""
    repo_root = tmp_path
    impl_root = repo_root / "patent_preexperiment"
    _make_impl(impl_root)

    shutil.copyfile(_REPO_ROOT / ".gitignore", repo_root / ".gitignore")
    _git(repo_root, "init", "-q", "-b", "main")
    _git(repo_root, "config", "user.email", "p1-test@example.com")
    _git(repo_root, "config", "user.name", "P1 Test")
    _git(repo_root, "add", "-A")
    _git(repo_root, "commit", "-q", "-m", "fixture: clean committed impl")
    head = _git(repo_root, "rev-parse", "HEAD")
    assert head and head != "unknown"

    # fit 只写 .gitignore 覆盖的 artifact → worktree 保持 clean，code_sha 即 HEAD
    out = run_fit_train_edges(impl_root)
    assert out["provenance"]["code_sha"] == head
    assert out["provenance"]["worktree_clean"] is True
    assert _git(repo_root, "status", "--porcelain") == ""

    # formal hard gate 两侧闭合：expected sha == current，且两侧 clean → 可继续
    summary = run_formal_test(impl_root)
    assert summary["verdict"]["verdict"] in {
        "Go", "Conditional", "No-Go", "NOT_EVALUABLE",
    }
    sentinel = json.loads(
        (impl_root / "results" / "raw" / "phase3_p1" / "p1_test_sentinel.json").read_text("utf-8")
    )
    manifest = json.loads(
        (impl_root / "results" / "raw" / "phase3_p1" / "p1_manifest.json").read_text("utf-8")
    )
    file_sha = hashlib.sha256(
        (impl_root / "data_registry" / "p1_train_edges.json").read_bytes()
    ).hexdigest()
    assert manifest["code_sha"] == head
    # X1.2：sentinel / manifest 记录同一个 artifact SHA，且与文件一致
    assert sentinel["train_edges_sha256"] == file_sha
    assert manifest["train_edges_sha256"] == file_sha


def test_formal_rejects_tampered_artifact_even_when_git_clean(tmp_path: Path):
    """X1.2 fail-closed：fit 后手工改 q50 → artifact 被 .gitignore 掩盖，git 仍 clean →
    formal 必须靠确定性重算在 test/sentinel 前拒绝（不依赖 git 状态）。"""
    repo_root = tmp_path
    impl_root = repo_root / "patent_preexperiment"
    _make_impl(impl_root)
    shutil.copyfile(_REPO_ROOT / ".gitignore", repo_root / ".gitignore")
    _git(repo_root, "init", "-q", "-b", "main")
    _git(repo_root, "config", "user.email", "p1-test@example.com")
    _git(repo_root, "config", "user.name", "P1 Test")
    _git(repo_root, "add", "-A")
    _git(repo_root, "commit", "-q", "-m", "fixture: clean committed impl")
    _git(repo_root, "rev-parse", "HEAD")

    run_fit_train_edges(impl_root)

    edges_path = impl_root / "data_registry" / "p1_train_edges.json"
    payload = json.loads(edges_path.read_text(encoding="utf-8"))
    payload["train"]["q50"] = float(payload["train"]["q50"]) + 1.0
    edges_path.write_text(json.dumps(payload), encoding="utf-8")

    # 关键：artifact 被忽略 → git status 仍 clean，formal 只能靠 integrity gate 拒绝
    assert _git(repo_root, "status", "--porcelain") == ""
    with pytest.raises(RuntimeError, match="integrity"):
        run_formal_test(impl_root)
    # fail-closed：sentinel / summary 均未落盘
    assert not (impl_root / "results" / "raw" / "phase3_p1" / "p1_test_sentinel.json").exists()
    assert not (impl_root / "results" / "raw" / "phase3_p1" / "p1_test_summary.json").exists()


def test_formal_rejects_tampered_quartile_edges(tmp_path: Path, monkeypatch):
    """X1.2 fail-closed（fake provenance 快路径）：quartile edges 被改 → 同样拒绝。"""
    _make_impl(tmp_path)
    _fake_git_provenance(monkeypatch, sha="deadbeef", clean=True)
    run_fit_train_edges(tmp_path)

    edges_path = tmp_path / "data_registry" / "p1_train_edges.json"
    payload = json.loads(edges_path.read_text(encoding="utf-8"))
    payload["quartile_edges"]["edges"][1] = 999.0
    edges_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="integrity"):
        run_formal_test(tmp_path)
    assert not (tmp_path / "results" / "raw" / "phase3_p1" / "p1_test_sentinel.json").exists()


def test_load_split_minutes_query_filter(tmp_path: Path, monkeypatch):
    _write_minute_dataset(tmp_path)
    reg = _registry()
    captured: dict = {}
    real_dataset = ds.dataset(str(tmp_path / "datasets" / "session_response_1min"))

    class _Spy:
        def __init__(self, inner):
            self._inner = inner

        def to_table(self, **kwargs):
            captured["filter"] = kwargs.get("filter")
            return self._inner.to_table(**kwargs)

    monkeypatch.setattr(ds, "dataset", lambda *a, **k: _Spy(real_dataset))
    out = _load_split_minutes(tmp_path / "datasets" / "session_response_1min", reg, "test")
    assert set(out["session_id"]) == {"S_TEST"}
    assert "S_TEST" in str(captured["filter"])


def test_load_split_minutes_fail_closed(tmp_path: Path, monkeypatch):
    _write_minute_dataset(tmp_path)
    reg = _registry()
    # 模拟上游回归：dataset 层忽略 filter，把全部会话都读回来
    real_dataset = ds.dataset(str(tmp_path / "datasets" / "session_response_1min"))

    class _NoFilterDataset:
        def __init__(self, inner):
            self._inner = inner

        def to_table(self, **kwargs):
            kwargs.pop("filter", None)
            return self._inner.to_table(**kwargs)

    monkeypatch.setattr(ds, "dataset", lambda *a, **k: _NoFilterDataset(real_dataset))
    with pytest.raises(RuntimeError, match="fail-closed"):
        _load_split_minutes(tmp_path / "datasets" / "session_response_1min", reg, "test")


def _make_impl(impl_root: Path, constant_test: bool = False) -> None:
    """搭 P1 所需的 configs / registry / 分钟表。"""
    cfg_dir = impl_root / "configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "p1.yaml").write_text(
        "experiment_id: P1_office001_replication_v1\n"
        "protocol_version: Phase3_v1.0.2\n"
        "site: office001\n",
        encoding="utf-8",
    )
    (cfg_dir / "k1_preregister.yaml").write_text(
        "primary_threshold:\n"
        "  P_on_kw: 0.5\n"
        "  delta_r: 0.25\n"
        "  delta_p_kw: 0.5\n"
        "  T_event_min: 5\n"
        "  initial_exclusion_min: 5\n"
        "  tail_exclusion_min: 10\n"
        "pilot_active_min_a: 1.0\n",
        encoding="utf-8",
    )
    reg = _registry()
    (impl_root / "data_registry").mkdir(parents=True, exist_ok=True)
    reg.to_parquet(impl_root / "data_registry" / "p1_office001_split_registry.parquet", index=False)
    _write_minute_dataset(impl_root, constant_test=constant_test)


def test_fit_train_edges_train_only(tmp_path: Path, monkeypatch):
    _make_impl(tmp_path)
    _fake_git_provenance(monkeypatch, sha="deadbeef", clean=True)
    out = run_fit_train_edges(tmp_path)
    edges_path = tmp_path / "data_registry" / "p1_train_edges.json"
    assert edges_path.exists()
    assert out["train"]["n_sessions"] == 1  # 只读 S1(train)，未读 test
    assert isinstance(out["train"]["q50"], float)
    assert out["train"]["n_evaluable_cycles"] >= 1
    # Review 57 X1-C：artifact 记录 clean 闭环 provenance
    payload = json.loads(edges_path.read_text(encoding="utf-8"))
    assert payload["provenance"]["code_sha"] == "deadbeef"
    assert payload["provenance"]["worktree_clean"] is True


def test_fit_train_edges_refuses_dirty_worktree(tmp_path: Path, monkeypatch):
    _make_impl(tmp_path)
    _fake_git_provenance(monkeypatch, sha="deadbeef", clean=False)
    with pytest.raises(RuntimeError, match="clean committed worktree"):
        run_fit_train_edges(tmp_path)
    # 不产出 artifact（fail-closed）
    assert not (tmp_path / "data_registry" / "p1_train_edges.json").exists()


def test_fit_train_edges_refuses_unknown_sha(tmp_path: Path, monkeypatch):
    _make_impl(tmp_path)
    _fake_git_provenance(monkeypatch, sha="unknown", clean=True)
    with pytest.raises(RuntimeError, match="clean committed worktree"):
        run_fit_train_edges(tmp_path)


def test_formal_test_once_only_and_sentinel(tmp_path: Path, monkeypatch):
    _make_impl(tmp_path)
    _fake_git_provenance(monkeypatch, sha="deadbeef", clean=True)
    summary = run_fit_train_edges(tmp_path)
    assert summary["provenance"]["code_sha"] == "deadbeef"

    summary = run_formal_test(tmp_path)
    sentinel = json.loads(
        (tmp_path / "results" / "raw" / "phase3_p1" / "p1_test_sentinel.json").read_text("utf-8")
    )
    assert sentinel["status"] == "completed"
    assert sentinel["exposed_sha"] == "deadbeef"

    with pytest.raises(RuntimeError, match="already exposed"):
        run_formal_test(tmp_path)

    frozen = read_frozen(tmp_path)
    assert frozen["scope"] == summary["scope"]


def test_formal_test_hard_gate_mismatch_sha(tmp_path: Path, monkeypatch):
    _make_impl(tmp_path)
    state = _fake_git_provenance(monkeypatch, sha="expected_sha_123", clean=True)
    run_fit_train_edges(tmp_path)
    state["sha"] = "different_sha"
    with pytest.raises(RuntimeError, match="expected code SHA"):
        run_formal_test(tmp_path)
    # sentinel 未写入（gate 失败于读取 test 之前）
    assert not (tmp_path / "results" / "raw" / "phase3_p1" / "p1_test_sentinel.json").exists()


def test_formal_test_hard_gate_dirty_worktree(tmp_path: Path, monkeypatch):
    _make_impl(tmp_path)
    state = _fake_git_provenance(monkeypatch, sha="abc123", clean=True)
    run_fit_train_edges(tmp_path)
    state["clean"] = False
    with pytest.raises(RuntimeError, match="worktree 不洁净"):
        run_formal_test(tmp_path)
    assert not (tmp_path / "results" / "raw" / "phase3_p1" / "p1_test_sentinel.json").exists()


def test_formal_test_state_missing_skips_bootstrap(tmp_path: Path, monkeypatch):
    """Review 57 X1-A：test 全 S1（state_missing）→ bootstrap 前落 NOT_EVALUABLE，不崩溃。"""
    _make_impl(tmp_path, constant_test=True)
    _fake_git_provenance(monkeypatch, sha="deadbeef", clean=True)
    run_fit_train_edges(tmp_path)

    summary = run_formal_test(tmp_path)
    assert summary["s1_s2"]["n_s2"] == 0
    assert summary["verdict"]["verdict"] == "NOT_EVALUABLE"
    assert summary["inferential"]["ci95"] is None
    assert "state_missing" in summary["inferential"]["skipped"]
    sentinel = json.loads(
        (tmp_path / "results" / "raw" / "phase3_p1" / "p1_test_sentinel.json").read_text("utf-8")
    )
    assert sentinel["status"] == "completed"
