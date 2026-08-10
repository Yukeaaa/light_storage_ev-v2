"""P1 runner 测试（Review 56 检查点 1-7）：train-only fit、test loader 隔离、
once-only state machine、hard gate。用合成数据，不读取真实 test outcome。
"""

from __future__ import annotations

import json
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


def _write_minute_dataset(root: Path) -> pd.DataFrame:
    """构造 office001 matched 分钟表：S1(train) / S2(validation) / S_TEST(test)。"""
    rows: list[dict] = []
    for sid, _split, n_min in (
        ("S1", "train", 120), ("S2", "validation", 120), ("S_TEST", "test", 120),
    ):
        t0 = pd.Timestamp("2019-06-01 08:00:00", tz="UTC")
        for m in range(n_min):
            ts = t0 + pd.Timedelta(minutes=m)
            rows.append({
                "session_id": sid,
                "station_id": "PL-0",
                "site": "office001",
                "garage": "Parking_Lot_01",
                "field_mode": "measured_pilot",
                "match_status": "matched",
                "timestamp_utc": ts,
                "actual_power_kw": float(6.0 if m < 100 else 2.0),
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


def _make_impl(impl_root: Path) -> None:
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
    _write_minute_dataset(impl_root)


def test_fit_train_edges_train_only(tmp_path: Path, monkeypatch):
    _make_impl(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = run_fit_train_edges(tmp_path)
    edges_path = tmp_path / "data_registry" / "p1_train_edges.json"
    assert edges_path.exists()
    assert out["train"]["n_sessions"] == 1  # 只读 S1(train)，未读 test
    assert isinstance(out["train"]["q50"], float)
    assert out["train"]["n_evaluable_cycles"] >= 1


def test_formal_test_once_only_and_sentinel(tmp_path: Path, monkeypatch):
    _make_impl(tmp_path)
    monkeypatch.chdir(tmp_path)
    run_fit_train_edges(tmp_path)

    # 制造 train edges provenance 以通过 hard gate（合成测试不依赖真实 git）
    edges_path = tmp_path / "data_registry" / "p1_train_edges.json"
    payload = json.loads(edges_path.read_text(encoding="utf-8"))
    payload["provenance"] = {"code_sha": "deadbeef", "worktree_clean": True}
    edges_path.write_text(json.dumps(payload), encoding="utf-8")

    class _FakeProv:
        @staticmethod
        def __call__(_repo):
            return {"code_sha": "deadbeef", "worktree_clean": True}

    monkeypatch.setattr(
        "patent_preexperiment.p1.runner.git_provenance", _FakeProv()
    )

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
    monkeypatch.chdir(tmp_path)
    run_fit_train_edges(tmp_path)
    edges_path = tmp_path / "data_registry" / "p1_train_edges.json"
    payload = json.loads(edges_path.read_text(encoding="utf-8"))
    payload["provenance"] = {"code_sha": "expected_sha_123", "worktree_clean": True}
    edges_path.write_text(json.dumps(payload), encoding="utf-8")

    class _FakeProv:
        @staticmethod
        def __call__(_repo):
            return {"code_sha": "different_sha", "worktree_clean": True}

    monkeypatch.setattr(
        "patent_preexperiment.p1.runner.git_provenance", _FakeProv()
    )
    with pytest.raises(RuntimeError, match="expected code SHA"):
        run_formal_test(tmp_path)
    # sentinel 未写入（gate 失败于读取 test 之前）
    assert not (tmp_path / "results" / "raw" / "phase3_p1" / "p1_test_sentinel.json").exists()
