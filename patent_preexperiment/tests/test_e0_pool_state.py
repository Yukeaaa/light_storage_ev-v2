"""E0F-04 控制池状态表单测（issue #15；V2.0 §6.3；V1.0 A.4.2）。"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.e0_full.pool_state import (
    _POOL_1MIN_COLUMNS,
    _POOL_5MIN_COLUMNS,
    aggregate_5min_from_1min,
    aggregate_partition_1min,
    build_pool_registry,
    gold_consistency,
    verify_cross_granularity,
    verify_session_source,
    write_pool_1min_partitions,
    write_pool_5min,
)

PP = Path(__file__).resolve().parents[1]
CFG = load_yaml(PP / "configs" / "e0_full.yaml")


def _mini_cfg() -> dict:
    cfg = copy.deepcopy(CFG)
    cfg["pool"]["gold"]["stations_frozen"] = 3
    cfg["pool"]["gold"]["tolerance_median_rel_dev"] = 0.02
    cfg["pool"]["gold"]["pools"] = [
        {"site": "caltech", "garage": "California_Garage_01"},
        {"site": "jpl", "garage": "Arroyo_Garage_01"},
    ]
    return cfg


def _mini_registry() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_id": ["m1", "m2", "s3", "s4"],
            "site": ["caltech", "caltech", "jpl", "caltech"],
            "garage": [
                "California_Garage_01",
                "California_Garage_01",
                "Arroyo_Garage_01",
                "California_Garage_01",
            ],
            "station": ["CA-01", "CA-02", "AR-01", "CA-03"],
            "match_status": ["matched", "matched", "matched", "static_only"],
        }
    )


def _mini_session_partition() -> pd.DataFrame:
    def _ts(minute: int) -> pd.Timestamp:
        return pd.Timestamp("2018-05-01 17:00:00", tz="UTC") + pd.Timedelta(minutes=minute)

    rows: list[dict] = []
    for minute in (0, 1):
        rows.append(
            {
                "session_id": "m1", "site": "caltech", "garage": "California_Garage_01",
                "match_status": "matched", "timestamp_utc": _ts(minute),
                "actual_power_kw": 2.4, "power_source": "measured",
                "pilot_available": True, "pilot_power_kw": 4.8, "current_a": 10.0,
                "state_available": True, "state_norm": "charging",
            }
        )
        rows.append(
            {
                "session_id": "m2", "site": "caltech", "garage": "California_Garage_01",
                "match_status": "matched", "timestamp_utc": _ts(minute),
                "actual_power_kw": 2.88, "power_source": "estimated",
                "pilot_available": True, "pilot_power_kw": 7.2, "current_a": 12.0,
                "state_available": True, "state_norm": "charging",
            }
        )
        rows.append(
            {
                "session_id": "s3", "site": "jpl", "garage": "Arroyo_Garage_01",
                "match_status": "matched", "timestamp_utc": _ts(minute),
                "actual_power_kw": 1.5, "power_source": "estimated",
                "pilot_available": False, "pilot_power_kw": np.nan, "current_a": 8.0,
                "state_available": False, "state_norm": "",
            }
        )
        rows.append(
            {
                "session_id": "s4", "site": "caltech", "garage": "California_Garage_01",
                "match_status": "static_only", "timestamp_utc": _ts(minute),
                "actual_power_kw": 2.0, "power_source": "measured",
                "pilot_available": True, "pilot_power_kw": 5.0, "current_a": 9.0,
                "state_available": True, "state_norm": "charging",
            }
        )
    return pd.DataFrame(rows)


def _expected_caltech_bucket(minutes: int) -> dict:
    return {
        "n_active": 2,
        "n_matched": 2,
        "n_charging": 2,
        "actual_power_kw_total": 5.28,
        "pilot_upper_kw_total": 12.0,
        "current_a_total": 22.0,
        "measured_kwh": 0.04,
        "estimated_kwh": 0.048,
        "pilot_coverage": 1.0,
        "state_coverage": 1.0,
        "measured_ratio": 0.5,
    }


def test_build_pool_registry() -> None:
    reg = build_pool_registry(_mini_registry(), _mini_cfg())
    assert reg["pool_id"].tolist() == [
        "caltech__California_Garage_01",
        "caltech__California_Garage_01",
        "jpl__Arroyo_Garage_01",
    ]
    assert reg["station"].tolist() == ["CA-01", "CA-02", "AR-01"]
    assert reg["gold"].tolist() == [True, True, True]
    assert reg["pool_id"].nunique() == 2


def test_build_pool_registry_gold_station_mismatch_stops() -> None:
    cfg = _mini_cfg()
    cfg["pool"]["gold"]["stations_frozen"] = 115
    with pytest.raises(RuntimeError, match="gold 池 station 数"):
        build_pool_registry(_mini_registry(), cfg)


def test_build_pool_registry_missing_gold_pool_stops() -> None:
    cfg = _mini_cfg()
    cfg["pool"]["gold"]["stations_frozen"] = 2
    cfg["pool"]["gold"]["pools"] = [
        {"site": "caltech", "garage": "California_Garage_01"},
        {"site": "office001", "garage": "Parking_Lot_01"},
    ]
    with pytest.raises(RuntimeError, match="gold 池在 matched registry 中缺失"):
        build_pool_registry(_mini_registry(), cfg)


def test_aggregate_partition_1min_golden() -> None:
    out = aggregate_partition_1min(_mini_session_partition())
    assert list(out.columns) == _POOL_1MIN_COLUMNS
    assert out["pool_id"].tolist() == [
        "caltech__California_Garage_01",
        "caltech__California_Garage_01",
        "jpl__Arroyo_Garage_01",
        "jpl__Arroyo_Garage_01",
    ]
    cal = out[out["pool_id"] == "caltech__California_Garage_01"].reset_index(drop=True)
    for i in range(2):
        exp = _expected_caltech_bucket(i)
        for k, v in exp.items():
            assert cal.loc[i, k] == pytest.approx(v), f"caltech bucket {i} {k}"
    jpl = out[out["pool_id"] == "jpl__Arroyo_Garage_01"].reset_index(drop=True)
    for i in range(2):
        assert jpl.loc[i, "n_active"] == 1
        assert jpl.loc[i, "actual_power_kw_total"] == pytest.approx(1.5)
        assert jpl.loc[i, "estimated_kwh"] == pytest.approx(1.5 / 60.0)
        assert jpl.loc[i, "measured_kwh"] == 0.0
        assert jpl.loc[i, "pilot_upper_kw_total"] == 0.0
        assert jpl.loc[i, "pilot_coverage"] == 0.0
        assert jpl.loc[i, "state_coverage"] == 0.0
        assert jpl.loc[i, "measured_ratio"] == 0.0
        assert jpl.loc[i, "n_charging"] == 0
    # static_only 不进池表
    assert set(out["site"].unique()) == {"caltech", "jpl"}


def test_aggregate_5min_from_1min_block() -> None:
    p1 = aggregate_partition_1min(_mini_session_partition())
    p5 = aggregate_5min_from_1min(p1)
    assert list(p5.columns) == _POOL_5MIN_COLUMNS
    assert len(p5) == 2  # 两个池各一个 5 分钟块
    cal = p5[p5["pool_id"] == "caltech__California_Garage_01"].iloc[0]
    assert cal["n_active"] == pytest.approx(2.0)
    assert cal["measured_kwh"] == pytest.approx(0.08)  # 2 分钟求和
    assert cal["estimated_kwh"] == pytest.approx(0.096)
    assert cal["actual_power_kw_total"] == pytest.approx(5.28)  # mean
    jpl = p5[p5["pool_id"] == "jpl__Arroyo_Garage_01"].iloc[0]
    assert jpl["estimated_kwh"] == pytest.approx(0.05)
    assert jpl["pilot_upper_kw_total"] == 0.0


def _write_mini_session_partition(tmp_path: Path) -> Path:
    d = tmp_path / "session_response_1min" / "site=caltech" / "year=2018" / "month=05"
    d.mkdir(parents=True)
    p = d / "data.parquet"
    _mini_session_partition().to_parquet(p, index=False)
    return p


def test_write_and_verify_pool_1min(tmp_path: Path) -> None:
    _write_mini_session_partition(tmp_path)
    pool_dir = tmp_path / "pool_state_1min"
    summary = write_pool_1min_partitions(
        tmp_path / "session_response_1min", _mini_cfg(), pool_dir
    )
    assert summary["n_partitions"] == 1
    assert summary["n_rows"] == 4
    # 篡改一行 → session 同源校验必须 STOP
    stored = pd.read_parquet(pool_dir / "site=caltech" / "year=2018" / "month=05" / "data.parquet")
    stored.loc[0, "actual_power_kw_total"] += 1.0
    stored.to_parquet(
        pool_dir / "site=caltech" / "year=2018" / "month=05" / "data.parquet",
        index=False,
    )
    with pytest.raises(RuntimeError, match="session 同源不一致"):
        verify_session_source(tmp_path / "session_response_1min", pool_dir)


def test_verify_cross_granularity_stops_on_tamper(tmp_path: Path) -> None:
    _write_mini_session_partition(tmp_path)
    pool_dir = tmp_path / "pool_state_1min"
    write_pool_1min_partitions(tmp_path / "session_response_1min", _mini_cfg(), pool_dir)
    p5_dir = tmp_path / "pool_state_5min"
    summary5 = write_pool_5min(pool_dir, p5_dir)
    assert summary5["n_rows"] == 2
    ok = verify_cross_granularity(pool_dir, p5_dir)
    assert ok["cross_granularity"] is True
    # 篡改 5min 表 → 跨粒度校验必须 STOP
    p5 = pd.read_parquet(p5_dir / "pool_state_5min.parquet")
    p5.loc[0, "measured_kwh"] += 1.0
    p5.to_parquet(p5_dir / "pool_state_5min.parquet", index=False)
    with pytest.raises(RuntimeError, match="跨粒度不一致"):
        verify_cross_granularity(pool_dir, p5_dir)


def _write_gold(tmp_path: Path, caltech_scale: float, jpl_scale: float) -> None:
    gd = tmp_path / "gold" / "benchmark_5min"
    gd.mkdir(parents=True, exist_ok=True)
    # 池级 5min 能量（无篡改时）：caltech=0.176，jpl=0.05
    rows_ca = pd.DataFrame(
        {
            "timestamp": ["2018-05-01T17:00:00+00:00"],
            "energy_kwh": [0.08 * caltech_scale],
        }
    )
    rows_ca2 = pd.DataFrame(
        {
            "timestamp": ["2018-05-01T17:00:00+00:00"],
            "energy_kwh": [0.096 * caltech_scale],
        }
    )
    rows_ar = pd.DataFrame(
        {
            "timestamp": ["2018-05-01T17:00:00+00:00"],
            "energy_kwh": [0.05 * jpl_scale],
        }
    )
    rows_ca.to_csv(gd / "CA-01.csv", index=False)
    rows_ca2.to_csv(gd / "CA-02.csv", index=False)
    rows_ar.to_csv(gd / "AR-01.csv", index=False)


def _mini_pool_registry() -> pd.DataFrame:
    reg = build_pool_registry(_mini_registry(), _mini_cfg())
    return reg


def test_gold_consistency_pass_and_fail(tmp_path: Path) -> None:
    p5 = aggregate_5min_from_1min(aggregate_partition_1min(_mini_session_partition()))
    cfg = _mini_cfg()

    _write_gold(tmp_path, caltech_scale=1.0, jpl_scale=1.0)
    ok = gold_consistency(_mini_pool_registry(), tmp_path / "gold", cfg, p5)
    assert ok["gold_consistency"] is True
    assert ok["median_abs_rel_dev"] < cfg["pool"]["gold"]["tolerance_median_rel_dev"]
    assert set(ok["per_pool"].keys()) == {
        "caltech__California_Garage_01",
        "jpl__Arroyo_Garage_01",
    }

    _write_gold(tmp_path, caltech_scale=2.0, jpl_scale=2.0)
    bad = gold_consistency(_mini_pool_registry(), tmp_path / "gold", cfg, p5)
    assert bad["gold_consistency"] is False
    assert bad["median_abs_rel_dev"] > cfg["pool"]["gold"]["tolerance_median_rel_dev"]
