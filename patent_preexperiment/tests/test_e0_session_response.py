"""E0F-03 会话分钟响应表测试（V2.1 §10.1/§10.2；issue #14 验收；审查结论17 授权）。

覆盖：
- parse_session_lines：缺列补齐、非法时间戳跳过、state 原文保留；
- exact_dup_extras：逐字节相同行 collapse 的额外份数按分钟登记；
- aggregate_session_minutes 金标准：均值/功率优先级/state_norm/能量前向保持/
  缺口标记/严重缺口/raw_duplicate_count/connected_elapsed_min/sample_count；
- 会话级能量审计与硬 STOP；
- build_session_response 集成：分区写出/分区注册表/会话覆盖/主键唯一；
- 输出列与 schema 对齐。
本测试只使用合成小样本，不依赖全量数据与 paths.yaml。
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.e0_full.session_response import (
    _OUTPUT_COLUMNS,
    _build_meta,
    _session_worker,
    aggregate_session_minutes,
    build_session_response,
    exact_dup_extras,
    parse_session_lines,
    session_energy_audit,
)

PP = Path(__file__).resolve().parents[1]
CFG = load_yaml(PP / "configs" / "e0_full.yaml")

_HEADER = (
    ",Charging Current (A),Actual Pilot (A),Voltage (V),"
    "Charging State,Energy Delivered (kWh),Power (kW)"
)


def _write_static(tmp_path: Path, rel: str, rows: list[str], header: str = _HEADER) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wb") as fh:
        fh.write((header + "\n").encode("utf-8"))
        for line in rows:
            fh.write((line + "\n").encode("utf-8"))
    return p


def _iso(minutes: int, sec: int = 0) -> str:
    base = pd.Timestamp("2018-05-01 17:00:00", tz="UTC")
    return (base + pd.Timedelta(minutes=minutes, seconds=sec)).isoformat()


def _meta(session_id: str = "s1", **overrides: object) -> dict[str, object]:
    m: dict[str, object] = {
        "session_id": session_id,
        "station_id": "CA-01",
        "site": "caltech",
        "garage": "California_Garage_01",
        "split": "train",
        "role": "main",
        "sample_layer": "L1_strict_matched",
        "field_mode": "measured_pilot",
        "match_status": "matched",
        "external": False,
        "stress": False,
        "connection_time": pd.Timestamp("2018-05-01 17:00:00", tz="UTC"),
        "disconnect_time": None,
        "done_charging_time": None,
        "kwh_delivered": None,
        "energy_source": "raw",
        "source_file": "caltech/x.csv.gz",
        "static_root": str(PP),
        "rated_v": 240.0,
        "minute_sample_threshold": 10,
        "severe_gap_min": 20.0,
        "tz_local": "America/Los_Angeles",
    }
    m.update(overrides)
    return m


# ---------------------------------------------------------------- parse / collapse

def test_parse_session_lines_missing_columns_and_bad_rows() -> None:
    lines = [
        ",Charging Current (A),Charging State,Power (kW)",  # 缺 pilot/voltage/energy
        _iso(0) + ",10.0,CHARGING,2.4",
        "garbage-timestamp,10.0,CHARGING,2.4",            # 非法时间戳 → 跳过
        _iso(1) + ",11.0,IDLE,not-a-number",              # 非法数值 → NaN
        _iso(2) + ",,CONNECTED,",                          # 空字段 → NaN
    ]
    df = parse_session_lines(lines)
    assert list(df.columns) == [
        "timestamp", "current_a", "pilot_a", "voltage_v", "state", "energy_kwh", "power_kw"
    ]
    assert len(df) == 3
    assert df["current_a"].iloc[0] == 10.0
    assert df["current_a"].iloc[1] == 11.0
    assert np.isnan(df["current_a"].iloc[2])
    assert np.isnan(df["power_kw"].iloc[1])
    assert df["state"].tolist() == ["CHARGING", "IDLE", "CONNECTED"]
    assert df["pilot_a"].isna().all()
    assert df["voltage_v"].isna().all()


def test_parse_session_lines_empty_returns_empty() -> None:
    assert parse_session_lines([]).empty
    assert parse_session_lines(["header only"]).empty


def test_exact_dup_extras_counts_collapsed_rows() -> None:
    lines = [
        _iso(0) + ",10.0,20.0,240.0,CHARGING,0.5,2.4",
        _iso(0) + ",10.0,20.0,240.0,CHARGING,0.5,2.4",   # exact dup → 1 extra
        _iso(0) + ",10.0,20.0,240.0,CHARGING,0.5,2.4",   # exact dup → 2nd extra
        _iso(0) + ",11.0,20.0,240.0,CHARGING,0.5,2.5",   # 同时间戳不同观测 → 保留
        _iso(1) + ",12.0,20.0,240.0,CHARGING,0.6,2.6",
        _iso(1) + ",12.0,20.0,240.0,CHARGING,0.6,2.6",   # exact dup → 1 extra
    ]
    extras = exact_dup_extras(lines)
    assert extras == {
        "2018-05-01T17:00:00Z": 2,
        "2018-05-01T17:01:00Z": 1,
    }


def test_exact_dup_extras_no_duplicate_timestamps_is_empty() -> None:
    lines = [_iso(i) + ",10.0" for i in range(5)]
    assert exact_dup_extras(lines) == {}


# ---------------------------------------------------------------- 分钟聚合金标准

def test_aggregate_session_minutes_golden() -> None:
    rows = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    _iso(0), _iso(0, 30),
                    _iso(1), _iso(1, 10),
                    _iso(2), _iso(2, 5),
                    _iso(6), _iso(6, 2),
                    _iso(26), _iso(26, 3),
                ],
                utc=True,
            ),
            "current_a": [10.0, 12.0, 10.0, 10.0, 11.0, 11.0, 10.0, 10.0, 5.0, 5.0],
            "voltage_v": [
                240.0, 240.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan
            ],
            "pilot_a": [20.0, 20.0, 20.0, 20.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan],
            "state": ["CHARGING", "CHARGING", "IDLE", "IDLE", None, None, None, None, None, None],
            "energy_kwh": [0.5, 0.6, 0.6, 0.6, np.nan, np.nan, 0.8, 0.8, 0.8, 0.8],
            "power_kw": [2.4, 2.9, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan],
        }
    )
    n_extra = {"2018-05-01T17:00:00Z": 1}
    meta = _meta()
    out = aggregate_session_minutes(rows, meta, n_extra)

    assert len(out) == 5
    assert out["timestamp_utc"].tolist() == pd.to_datetime(
        [_iso(i) for i in (0, 1, 2, 6, 26)], utc=True
    ).tolist()

    r0 = out.iloc[0]
    assert r0["current_a"] == pytest.approx(11.0)
    assert r0["voltage_v"] == pytest.approx(240.0)
    assert r0["power_kw"] == pytest.approx(2.65)          # measured 均值
    assert r0["actual_power_kw"] == pytest.approx(2.65)
    assert r0["power_source"] == "measured"
    assert r0["pilot_a"] == pytest.approx(20.0)
    assert r0["pilot_power_kw"] == pytest.approx(4.8)      # 20 × 240 / 1000
    assert r0["pilot_available"]
    assert r0["state_raw"] == "CHARGING"
    assert r0["state_norm"] == "charging"
    assert r0["state_available"]
    assert r0["energy_cum_kwh"] == pytest.approx(0.6)
    assert r0["sample_count"] == 2
    assert r0["raw_duplicate_count"] == 1
    assert r0["gap_flag"]      # 2 样本 < 10 → 缺口（冻结参考线）
    assert r0["connected_elapsed_min"] == pytest.approx(0.0)

    r1 = out.iloc[1]  # estimated：无 power/voltage → current×240/1000
    assert r1["actual_power_kw"] == pytest.approx(2.4)
    assert r1["power_source"] == "estimated"
    assert r1["state_norm"] == "idle"
    assert r1["energy_cum_kwh"] == pytest.approx(0.6)
    assert r1["sample_count"] == 2
    assert r1["gap_flag"]
    assert r1["connected_elapsed_min"] == pytest.approx(1.0)

    r2 = out.iloc[2]  # pilot 缺失 / state 缺失 → available False
    assert not r2["pilot_available"]
    assert r2["pilot_a"] != r2["pilot_a"]                   # NaN
    assert not r2["state_available"]
    assert r2["state_norm"] == ""
    assert r2["energy_cum_kwh"] == pytest.approx(0.6)       # 前向保持
    assert r2["actual_power_kw"] == pytest.approx(2.64)     # 11 × 240 / 1000
    assert r2["sample_count"] == 2
    assert r2["gap_flag"]

    r3 = out.iloc[3]  # 与 17:02 相隔 4 分钟 → gap_before=4，非严重
    assert r3["gap_before_min"] == pytest.approx(4.0)
    assert not r3["severe_gap_before"]
    assert r3["energy_cum_kwh"] == pytest.approx(0.8)
    assert r3["connected_elapsed_min"] == pytest.approx(6.0)

    r4 = out.iloc[4]  # 与 17:06 相隔 20 分钟 → 严重缺口
    assert r4["gap_before_min"] == pytest.approx(20.0)
    assert r4["severe_gap_before"]
    assert r4["actual_power_kw"] == pytest.approx(1.2)

    assert out["split"].eq("train").all()
    assert out["site"].eq("caltech").all()
    assert out["cluster"].eq("California_Garage_01").all()
    assert out["match_status"].eq("matched").all()
    assert out["energy_source"].eq("raw").all()
    assert out["timestamp_utc"].is_unique


def test_full_minute_no_gap_flag() -> None:
    n = 10
    rows = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([_iso(0, sec) for sec in range(n)], utc=True),
            "current_a": [10.0] * n,
            "voltage_v": [240.0] * n,
            "pilot_a": [np.nan] * n,
            "state": [None] * n,
            "energy_kwh": [np.nan] * n,
            "power_kw": [np.nan] * n,
        }
    )
    out = aggregate_session_minutes(rows, _meta(), {})
    r = out.iloc[0]
    assert r["sample_count"] == 10
    assert not r["gap_flag"]


def test_aggregate_power_priority_within_minute() -> None:
    rows = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([_iso(0), _iso(0, 10)], utc=True),
            "current_a": [10.0, 10.0],
            "voltage_v": [240.0, np.nan],
            "pilot_a": [np.nan, np.nan],
            "state": [None, None],
            "energy_kwh": [np.nan, np.nan],
            "power_kw": [2.4, np.nan],   # 首行 measured
        }
    )
    out = aggregate_session_minutes(rows, _meta(), {})
    r = out.iloc[0]
    # measured 2.4 与 estimated 2.4 同值 → 均值 2.4，但 source 是混合分钟，取众数
    assert r["actual_power_kw"] == pytest.approx(2.4)
    assert r["power_source"] == "measured" or r["power_source"] == "estimated"

    # 纯 computed：有 voltage+current 无 power
    rows2 = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([_iso(0), _iso(0, 10)], utc=True),
            "current_a": [10.0, 12.0],
            "voltage_v": [240.0, 240.0],
            "pilot_a": [np.nan, np.nan],
            "state": [None, None],
            "energy_kwh": [np.nan, np.nan],
            "power_kw": [np.nan, np.nan],
        }
    )
    out2 = aggregate_session_minutes(rows2, _meta(), {})
    r2 = out2.iloc[0]
    assert r2["actual_power_kw"] == pytest.approx(2.4 * 11.0 / 10.0)  # 11×240/1000
    assert r2["power_source"] == "computed"


# ---------------------------------------------------------------- 会话级审计与 STOP

def test_session_energy_audit() -> None:
    rows = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([_iso(0), _iso(1)], utc=True),
            "current_a": [10.0, 10.0],
            "voltage_v": [np.nan, np.nan],
            "pilot_a": [np.nan, np.nan],
            "state": [None, None],
            "energy_kwh": [0.0, 0.08],
            "power_kw": [np.nan, np.nan],
        }
    )
    out = aggregate_session_minutes(rows, _meta(), {})
    a = session_energy_audit(out, rows, _meta())
    assert a["integral_kwh"] == pytest.approx((2.4 + 2.4) / 60.0)
    assert a["energy_first"] == pytest.approx(0.0)
    assert a["energy_last"] == pytest.approx(0.08)
    assert a["has_energy"]
    assert a["match_status"] == "matched"


def test_session_energy_audit_ignores_trailing_meter_reset() -> None:
    # 会话末尾 UNPLUGGED 复位行把能量计数 re-arm 到 0.0（已知伪影）：
    # energy_last 取峰值读数，不用聚合末值，避免能量跨度被污染。
    rows = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([_iso(0), _iso(1), _iso(2)], utc=True),
            "current_a": [10.0, 10.0, 0.0],
            "voltage_v": [np.nan, np.nan, np.nan],
            "pilot_a": [np.nan, np.nan, np.nan],
            "state": ["CHARGING", "CHARGING", "UNPLUGGED"],
            "energy_kwh": [0.0, 0.08, 0.0],
            "power_kw": [np.nan, np.nan, np.nan],
        }
    )
    out = aggregate_session_minutes(rows, _meta(), {})
    a = session_energy_audit(out, rows, _meta())
    assert a["energy_last"] == pytest.approx(0.08)
    assert a["energy_first"] == pytest.approx(0.0)
    assert a["integral_kwh"] == pytest.approx((2.4 + 2.4) / 60.0)


def test_worker_returns_error_frame_for_empty_file(tmp_path: Path) -> None:
    _write_static(tmp_path, "caltech/x.csv.gz", [])
    meta = _meta(static_root=str(tmp_path))
    frame, audit = _session_worker(meta)
    assert "parse_error" in frame.columns
    assert frame["session_id"].iloc[0] == "s1"
    assert audit is None


def test_worker_full_file_minutes(tmp_path: Path) -> None:
    rows = [
        _iso(0) + ",10.0,20.0,240.0,CHARGING,0.5,2.4",
        _iso(0) + ",10.0,20.0,240.0,CHARGING,0.5,2.4",
        _iso(1) + ",11.0,20.0,240.0,CHARGING,0.6,2.6",
        _iso(22) + ",12.0,20.0,240.0,CHARGING,0.7,2.9",   # 与 17:01 相隔 21 min
    ]
    _write_static(tmp_path, "caltech/x.csv.gz", rows)
    meta = _meta(static_root=str(tmp_path))
    frame, audit = _session_worker(meta)
    assert "parse_error" not in frame.columns
    assert len(frame) == 3
    r0 = frame.iloc[0]
    assert r0["raw_duplicate_count"] == 1
    assert r0["sample_count"] == 1      # 逐字节相同行 collapse 后只保留 1 个观测
    assert not frame.iloc[1]["severe_gap_before"]
    assert frame.iloc[2]["gap_before_min"] == pytest.approx(21.0)
    assert frame.iloc[2]["severe_gap_before"]
    assert audit is not None and audit["n_minutes"] == 3


# ---------------------------------------------------------------- 集成：分区写出

def _mini_registry() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_id": ["m1", "m2", "s3"],
            "site": ["caltech", "caltech", "jpl"],
            "garage": ["California_Garage_01", "California_Garage_01", "Arroyo_Garage_01"],
            "station": ["CA-01", "CA-02", "AR-01"],
            "split": ["train", "validation", "stress"],
            "role": ["main", "main", "current_only_fallback"],
            "sample_layer": ["L1_strict_matched", "L1_strict_matched", "L0_static_extension"],
            "field_mode": ["measured_pilot", "measured_pilot", "current_only"],
            "match_status": ["matched", "matched", "static_only"],
            "external": [False, False, False],
            "stress": [False, False, True],
            "connection_time": pd.to_datetime(
                [
                    "2018-05-01 17:00:00+00:00",
                    "2018-05-01 17:10:00+00:00",
                    "2018-05-02 08:00:00+00:00",
                ],
                utc=True,
            ),
            "disconnect_time": pd.to_datetime(
                ["2018-05-01 18:00:00+00:00", "2018-05-01 18:10:00+00:00", None], utc=True
            ),
            "source_file": ["caltech/m1.csv.gz", "caltech/m2.csv.gz", "jpl/s3.csv.gz"],
        }
    )


def _mini_manifest() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "logical_path": ["caltech/m1.csv.gz", "caltech/m2.csv.gz", "jpl/s3.csv.gz"],
            "has_energy": [True, True, False],
            "has_current": [True, True, True],
            "has_power": [True, True, False],
            "has_voltage": [True, True, False],
            "has_pilot": [True, True, False],
            "has_state": [True, True, False],
        }
    )


def _mini_api_meta() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sessionID": ["m1", "m2"],
            "doneChargingTime": ["2018-05-01 17:55:00+00:00", "2018-05-01 18:05:00+00:00"],
            "kWhDelivered": ["8.0", "8.0"],
        }
    )


def _seed_files(tmp_path: Path) -> None:
    # m1：首分钟空闲（能量基线 0.0）→ 10 个充电分钟 10A×240V=2.4kW，
    # 能量读数逐分钟 +0.04（2.4/60），末读数 0.40 → span==integral，能量一致。
    rows1 = [_iso(0) + ",0.0,0.0,240.0,CONNECTED,0.00,0.0"]
    rows1 += [
        f"{_iso(i + 1)},{10.0},{20.0},{240.0},CHARGING,{0.04 * i:.2f},{2.4}"
        for i in range(1, 11)
    ]
    _write_static(tmp_path, "caltech/m1.csv.gz", rows1)
    # m2：首分钟空闲 → 10 个充电分钟 12A×240V=2.88kW，每分 +0.048
    rows2 = [_iso(10) + ",0.0,0.0,240.0,CONNECTED,0.00,0.0"]
    rows2 += [
        f"{_iso(10 + i + 1)},{12.0},{20.0},{240.0},CHARGING,{0.048 * i:.3f},{2.88}"
        for i in range(1, 11)
    ]
    _write_static(tmp_path, "caltech/m2.csv.gz", rows2)
    rows3 = [f"{_iso(i)},{8.0},{0.0},,,," for i in range(12)]  # jpl current-only，无能量
    _write_static(tmp_path, "jpl/s3.csv.gz", rows3)


def test_build_session_response_integration(tmp_path: Path) -> None:
    _seed_files(tmp_path)
    out_dir = tmp_path / "out" / "session_response_1min"
    part_reg = tmp_path / "out" / "partitions.json"
    registry = _mini_registry()
    manifest = _mini_manifest()
    api_meta = _mini_api_meta()

    summary = build_session_response(
        registry=registry,
        manifest=manifest,
        api_meta=api_meta,
        cfg=CFG,
        static_root=tmp_path,
        out_dir=out_dir,
        partition_registry_out=part_reg,
        max_workers=2,
    )
    assert summary["n_sessions"] == 3
    assert summary["n_partitions"] == 2
    assert summary["n_failed_sessions"] == 0

    p_cal = out_dir / "site=caltech" / "year=2018" / "month=05" / "data.parquet"
    p_jpl = out_dir / "site=jpl" / "year=2018" / "month=05" / "data.parquet"
    assert p_cal.exists() and p_jpl.exists()

    cal = pd.read_parquet(p_cal)
    jpl = pd.read_parquet(p_jpl)
    assert set(cal["session_id"]) == {"m1", "m2"}
    assert set(jpl["session_id"]) == {"s3"}
    assert not cal.duplicated(subset=["session_id", "timestamp_utc"]).any()
    assert not jpl.duplicated(subset=["session_id", "timestamp_utc"]).any()

    # jpl 无能量列 → energy_source=none，全部 estimated（rated 192.7）
    assert jpl["energy_source"].eq("none").all()
    assert jpl["power_source"].eq("estimated").all()
    assert jpl["actual_power_kw"].iloc[0] == pytest.approx(8.0 * 192.7 / 1000.0)

    # m1 能量一致性：integral=2.4×10/60=0.4，span=0.40-0.00=0.40 → dev≈0
    m1 = cal[cal["session_id"] == "m1"]
    assert m1["connected_elapsed_min"].iloc[0] == pytest.approx(0.0)
    assert m1["done_charging_time"].notna().all()
    assert m1["kwh_delivered"].iloc[0] == pytest.approx(8.0)

    reg_json = json.loads(part_reg.read_text(encoding="utf-8"))
    assert reg_json["n_sessions"] == 3
    assert reg_json["n_rows"] == int(len(cal) + len(jpl))
    assert len(reg_json["partitions"]) == 2


def test_build_empty_session_stops(tmp_path: Path) -> None:
    _seed_files(tmp_path)
    _write_static(tmp_path, "jpl/empty.csv.gz", [])   # 有 header 无数据行
    reg = _mini_registry()
    reg = pd.concat(
        [reg, pd.DataFrame([{
            "session_id": "empty1", "site": "jpl", "garage": "Arroyo_Garage_01",
            "station": "AR-02", "split": "stress", "role": "current_only_fallback",
            "sample_layer": "L0_static_extension", "field_mode": "current_only",
            "match_status": "static_only", "external": False, "stress": True,
            "connection_time": pd.Timestamp("2018-05-03 08:00:00", tz="UTC"),
            "disconnect_time": pd.NaT, "source_file": "jpl/empty.csv.gz",
        }])],
        ignore_index=True,
    )
    manifest = _mini_manifest()
    manifest = pd.concat(
        [manifest, pd.DataFrame([{
            "logical_path": "jpl/empty.csv.gz", "has_energy": False, "has_current": False,
            "has_power": False, "has_voltage": False, "has_pilot": False, "has_state": False,
        }])],
        ignore_index=True,
    )
    with pytest.raises(RuntimeError, match="读取/解析失败"):
        build_session_response(
            registry=reg,
            manifest=manifest,
            api_meta=_mini_api_meta(),
            cfg=CFG,
            static_root=tmp_path,
            out_dir=tmp_path / "out2",
            partition_registry_out=tmp_path / "out2" / "partitions.json",
            max_workers=2,
        )


def test_energy_consistency_stop(tmp_path: Path) -> None:
    # m1 能量跨度 2.0 而 integral 0.4 → 中位 |dev|>1% → 硬 STOP
    rows1 = [_iso(0) + ",0.0,0.0,240.0,CONNECTED,0.00,0.0"]
    rows1 += [
        f"{_iso(i + 1)},{10.0},{20.0},{240.0},CHARGING,{0.2 if i == 10 else 0.0:.2f},{2.4}"
        for i in range(1, 11)
    ]
    _write_static(tmp_path, "caltech/m1.csv.gz", rows1)
    _write_static(tmp_path, "caltech/m2.csv.gz", [
        f"{_iso(10 + i)},{12.0},{20.0},{240.0},CHARGING,{0.048 * i:.3f},{2.88}" for i in range(10)
    ])
    _write_static(tmp_path, "jpl/s3.csv.gz", [f"{_iso(i)},{8.0},,,,," for i in range(12)])

    with pytest.raises(RuntimeError, match="能量一致性 STOP"):
        build_session_response(
            registry=_mini_registry(),
            manifest=_mini_manifest(),
            api_meta=_mini_api_meta(),
            cfg=CFG,
            static_root=tmp_path,
            out_dir=tmp_path / "out3",
            partition_registry_out=tmp_path / "out3" / "partitions.json",
            max_workers=2,
        )


def test_build_meta_joins_offline_labels() -> None:
    registry = _mini_registry()
    manifest = _mini_manifest()
    api_meta = _mini_api_meta()
    metas = _build_meta(registry, manifest, api_meta, CFG, static_root=".")
    by_id = {m["session_id"]: m for m in metas}
    assert by_id["m1"]["done_charging_time"] == "2018-05-01 17:55:00+00:00"
    assert by_id["m1"]["kwh_delivered"] == "8.0"
    assert by_id["m1"]["energy_source"] == "raw"
    assert by_id["s3"]["done_charging_time"] is None
    assert by_id["s3"]["kwh_delivered"] is None
    assert by_id["s3"]["energy_source"] == "none"
    assert by_id["s3"]["rated_v"] == pytest.approx(192.7)


def test_output_columns_match_schema() -> None:
    schema = json.loads(
        (PP / "data_registry" / "e0_full_session_response_1min.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(schema["columns"]) == _OUTPUT_COLUMNS
    assert set(schema["unique_columns"]) <= set(_OUTPUT_COLUMNS)

