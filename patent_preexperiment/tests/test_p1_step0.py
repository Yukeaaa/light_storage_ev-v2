"""P1 Step 0 测试（Phase 3 v1.0.2 §1.5）：test query-isolation fail-closed + pretest E1 计数正确性。

Review 56：session membership 必须在 Arrow query predicate 层过滤（不能只靠 pandas
后过滤）；test 行不进入 query result / analysis dataframe。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest

from patent_preexperiment.p1.step0 import _load_train_val_minutes, _pretest_e1_events
from patent_preexperiment.response.events import GapThresholds

_THR = GapThresholds(
    p_on_kw=0.5, delta_r=0.25, delta_p_kw=0.5, t_event_min=5,
    initial_exclusion_min=5, tail_exclusion_min=10, pilot_active_min_a=1.0,
)


def _build_minutes_df() -> pd.DataFrame:
    """S1(train) 含一个 20 分钟 core gap 事件；S2(validation) 无事件；S_TEST(test) 有事件。"""
    rows: list[dict] = []
    for sid, n_min, gap_start in (
        ("S1", 200, 40),
        ("S2", 120, None),
        ("S_TEST", 200, 40),
    ):
        t0 = pd.Timestamp("2019-06-01 08:00:00", tz="UTC")
        done = t0 + pd.Timedelta(minutes=n_min)
        disc = done + pd.Timedelta(minutes=1)
        for m in range(n_min):
            ts = t0 + pd.Timedelta(minutes=m)
            if gap_start is not None and gap_start <= m < gap_start + 20:
                actual, pilot = 2.0, 6.0
            else:
                actual, pilot = 6.0, 6.0
            rows.append({
                "session_id": sid,
                "station_id": "PL-0",
                "site": "office001",
                "garage": "Parking_Lot_01",
                "field_mode": "measured_pilot",
                "match_status": "matched",
                "timestamp_utc": ts,
                "actual_power_kw": actual,
                "pilot_power_kw": pilot,
                "current_a": 5.0,
                "pilot_a": 32.0,
                "pilot_available": True,
                "connected_elapsed_min": float(m),
                "gap_flag": False,
                "disconnect_time": disc,
                "done_charging_time": done,
            })
    return pd.DataFrame(rows)


def _write_minutes(path: Path) -> pd.DataFrame:
    df = _build_minutes_df()
    pq.write_table(pa.Table.from_pandas(df), path / "data.parquet")
    return df


def _registry(rows: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["session_id", "split"])


def test_test_rows_physically_excluded(tmp_path: Path):
    _write_minutes(tmp_path)
    reg = _registry([("S1", "train"), ("S2", "validation"), ("S_TEST", "test")])
    out = _load_train_val_minutes(tmp_path, reg)
    assert set(out["session_id"]) == {"S1", "S2"}
    assert "S_TEST" not in set(out["session_id"])


def test_query_predicate_contains_session_restriction(tmp_path: Path, monkeypatch):
    """Review 56：session membership 必须在 Arrow query predicate 层，不能只靠 pandas 过滤。

    spy dataset.to_table()，断言传入 predicate 已包含 session_id.isin(train_val_ids)。
    这样 test 行不进入 query result（不只是 analysis dataframe）。
    """
    _write_minutes(tmp_path)
    reg = _registry([("S1", "train"), ("S2", "validation"), ("S_TEST", "test")])

    real_dataset = ds.dataset(str(tmp_path))
    captured: dict = {}

    class _SpyDataset:
        def __init__(self, inner):
            self._inner = inner

        def to_table(self, **kwargs):
            captured["filter"] = kwargs.get("filter")
            return self._inner.to_table(**kwargs)

    monkeypatch.setattr(ds, "dataset", lambda *a, **k: _SpyDataset(real_dataset))

    out = _load_train_val_minutes(tmp_path, reg)
    assert set(out["session_id"]) == {"S1", "S2"}

    pred = captured["filter"]
    assert pred is not None
    assert "session_id" in str(pred)
    assert "is_in" in str(pred).lower()
    assert "S1" in str(pred) and "S2" in str(pred)
    assert "S_TEST" not in str(pred)


def test_fail_closed_on_test_leak(tmp_path: Path):
    _write_minutes(tmp_path)
    # registry 不一致：S_TEST 同时出现在 train 与 test → 泄漏面，必须 RuntimeError
    reg = _registry([
        ("S1", "train"), ("S2", "validation"),
        ("S_TEST", "train"), ("S_TEST", "test"),
    ])
    with pytest.raises(RuntimeError, match="fail-closed"):
        _load_train_val_minutes(tmp_path, reg)


def test_fail_closed_when_test_set_empty(tmp_path: Path):
    _write_minutes(tmp_path)
    # registry 无 test 会话 → split 冻结异常，必须拦截
    reg = _registry([("S1", "train"), ("S2", "validation")])
    with pytest.raises(ValueError, match="test 会话集为空"):
        _load_train_val_minutes(tmp_path, reg)


def test_pretest_e1_event_count():
    df = _build_minutes_df()
    df = df[df["session_id"].isin(["S1", "S2"])]
    labeled, core, summary = _pretest_e1_events(df, _THR)
    assert len(core) == 1
    assert core.iloc[0]["session_id"] == "S1"
    assert int(summary.loc[summary["session_id"] == "S1", "n_events"].iloc[0]) == 1


def test_pretest_e1_no_event_session():
    df = _build_minutes_df()
    df = df[df["session_id"] == "S2"]
    labeled, core, summary = _pretest_e1_events(df, _THR)
    assert len(core) == 0
