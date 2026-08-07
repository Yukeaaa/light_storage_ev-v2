"""E0F-01 全量输入 manifest / 数据质量审计 / connectionTime 审计测试（审查结论9；V2.1 §10）。

覆盖：
- scan_static_file 独立扫描正确性（覆盖/短文件/重复/倒序/缺口/gzip 尾部垃圾）；
- source manifest 确定性：同输入跑两遍 manifest 哈希与 parquet 完全一致；
- connectionTime 只审计不切分：矛盾样本 → anomaly 而非 fallback（审查结论9 强制）；
- 工程卫生：无 configs/paths.yaml 时 import + 明确报错提示 paths.example.yaml。
本测试只使用合成小样本，不依赖全量数据与 paths.yaml。
"""

from __future__ import annotations

import gzip
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from patent_preexperiment.e0_full.input_audit import (
    ScanConfig,
    audit_connection_time,
    build_source_manifest,
    classify_dup_ts,
    dup_collapse_impact,
    file_role,
    manifest_hash,
    scan_static_file,
    site_canonical,
)

PP = Path(__file__).resolve().parents[1]
REPO = PP.parent

_HEADER = (
    ",Charging Current (A),Actual Pilot (A),Voltage (V),"
    "Charging State,Energy Delivered (kWh),Power (kW)"
)


def _write_static(tmp_path: Path, rel: str, rows: list[str], header: str = _HEADER) -> Path:
    """写一个合成静态 csv.gz（首行表头 + 数据行）。"""
    p = tmp_path / rel.replace("/", "/")
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wb") as fh:
        fh.write((header + "\n").encode("utf-8"))
        for line in rows:
            fh.write((line + "\n").encode("utf-8"))
    return p


def _iso(minutes: int, sec: int = 0) -> str:
    base = pd.Timestamp("2018-05-01 17:00:00", tz="UTC")
    return (base + pd.Timedelta(minutes=minutes, seconds=sec)).isoformat()


def _index_df(*rows: dict[str, object]) -> pd.DataFrame:
    cols = ["file", "site", "garage", "stationID", "file_size", "rows"]
    return pd.DataFrame(rows, columns=cols)


def test_scan_static_file_coverage_and_stats(tmp_path: Path) -> None:
    f = _write_static(
        tmp_path,
        "caltech/California_Garage_01/a.csv.gz",
        [
            f"{_iso(0)},10.0,20.0,240.0,CHARGING,0.5,6.0",
            f"{_iso(1)},10.5,21.0,240.1,CHARGING,1.0,6.3",
            f"{_iso(2)},10.5,21.0,240.1,CHARGING,1.5,6.3",   # 重复时间戳
            f"{_iso(1)},10.0,20.0,240.0,CHARGING,0.6,6.1",   # 倒序
            f"{_iso(120)},11.0,22.0,240.2,DONE,1.6,6.6",     # 缺口 118 min
        ],
    )
    res = scan_static_file(f)
    assert res["read_ok"] is True and res["gzip_ok"] is True
    assert res["rows"] == 5
    assert res["n_dup_ts"] == 1
    assert res["n_reversed"] == 1
    assert res["max_gap_min"] == pytest.approx(119.0)
    assert res["has_current"] is True
    assert res["has_pilot"] is True
    assert res["has_voltage"] is True
    assert res["has_state"] is True
    assert res["has_energy"] is True
    assert res["has_power"] is True


def test_scan_static_file_current_only_and_short(tmp_path: Path) -> None:
    header = ",Charging Current (A)"
    f = _write_static(
        tmp_path,
        "jpl/LIGO_01/b.csv.gz",
        [f"{_iso(0)},5.0", f"{_iso(1)},5.5", f"{_iso(2)},6.0"],
        header=header,
    )
    res = scan_static_file(f)
    assert res["read_ok"] is True
    assert res["has_current"] is True
    assert res["has_pilot"] is False
    assert res["has_voltage"] is False
    assert res["has_state"] is False
    assert res["has_power"] is False
    assert res["rows"] == 3


def test_scan_static_file_gzip_trailing_garbage(tmp_path: Path) -> None:
    p = tmp_path / "jpl/LIGO_01/trailing.csv.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = gzip.compress(("ts\n" + f"{_iso(0)},5.0\n").encode("utf-8"))
    p.write_bytes(raw + b"GARBAGE")
    res = scan_static_file(p)
    assert res["gzip_ok"] is False
    assert res["trailing_garbage"] is True
    assert res["read_ok"] is True


def test_build_source_manifest_deterministic(tmp_path: Path) -> None:
    f1 = _write_static(
        tmp_path,
        "caltech/California_Garage_01/a.csv.gz",
        [f"{_iso(i)},10.0,20.0,240.0,CHARGING,{0.5 * i},6.0" for i in range(12)],
    )
    f2 = _write_static(
        tmp_path,
        "jpl/LIGO_01/b.csv.gz",
        [f"{_iso(0)},5.0", f"{_iso(1)},5.5"],
        header=",Charging Current (A)",
    )
    idx = _index_df(
        {
            "file": "caltech/California_Garage_01/a.csv.gz",
            "site": "caltech",
            "garage": "California_Garage_01",
            "stationID": "a",
            "file_size": f1.stat().st_size,
            "rows": 12,
        },
        {
            "file": "jpl/LIGO_01/b.csv.gz",
            "site": "jpl",
            "garage": "LIGO_01",
            "stationID": "b",
            "file_size": f2.stat().st_size,
            "rows": 2,
        },
    )

    a = build_source_manifest(idx, tmp_path)
    b = build_source_manifest(idx, tmp_path)

    assert manifest_hash(a) == manifest_hash(b)
    pd.testing.assert_frame_equal(a, b)

    # 确定性排序：logical_path 升序
    assert a["logical_path"].tolist() == sorted(a["logical_path"].tolist())
    # 独立扫描出的 rows 与 index rows 一致
    assert a["rows_match_index"].all()
    # 短文件标记：10 行以下
    assert bool(a.loc[a["site"] == "jpl", "short_file"].iloc[0]) is True
    assert bool(a.loc[a["site"] == "caltech", "short_file"].iloc[0]) is False


def test_build_source_manifest_short_file_threshold(tmp_path: Path) -> None:
    rows = [f"{_iso(i)},10.0" for i in range(12)]
    f = _write_static(
        tmp_path,
        "caltech/California_Garage_01/c.csv.gz",
        rows,
        header=",Charging Current (A)",
    )
    idx = _index_df(
        {
            "file": "caltech/California_Garage_01/c.csv.gz",
            "site": "caltech",
            "garage": "California_Garage_01",
            "stationID": "c",
            "file_size": f.stat().st_size,
            "rows": 12,
        },
    )
    m = build_source_manifest(idx, tmp_path)
    assert bool(m.loc[0, "short_file"]) is False
    assert m.loc[0, "rows"] == 12

    m10 = build_source_manifest(idx, tmp_path, cfg=ScanConfig(min_rows_per_file=13))
    assert bool(m10.loc[0, "short_file"]) is True


def _conn_fixtures() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """合成 mapping/api/manifest 小样本 + 冻结 e0_full 配置。"""
    mapping = pd.DataFrame(
        {
            "sessionID": ["s1", "s2", "s3"],
            "site_static": ["caltech", "caltech", "jpl"],
            "garage": ["California_Garage_01"] * 3,
            "stationID": ["a", "b", "c"],
            "static_file": [
                "caltech/California_Garage_01/a.csv.gz",
                "caltech/California_Garage_01/b.csv.gz",
                "jpl/LIGO_01/c.csv.gz",
            ],
            "match_status": ["matched", "matched", "matched"],
        }
    )
    api = pd.DataFrame(
        {
            "sessionID": ["s1", "s2", "s3"],
            # s1 缺失 API connectionTime（→ fallback）；s2 正常；s3 可解析但与首条观测明显矛盾
            "connectionTime": [None, "2018-05-01T17:00:30+00:00", "2018-05-01T18:00:00+00:00"],
        }
    )
    manifest = pd.DataFrame(
        {
            "logical_path": [
                "caltech/California_Garage_01/a.csv.gz",
                "caltech/California_Garage_01/b.csv.gz",
                "jpl/LIGO_01/c.csv.gz",
            ],
            "time_min": [
                "2018-05-01T17:00:05+00:00",
                "2018-05-01T17:00:10+00:00",
                "2018-05-01T17:00:00+00:00",
            ],
        }
    )
    cfg = {
        "session_join": {
            "connection_time": {
                "audit": {
                    "rule": "矛盾样本 → anomaly，禁止自动替换",
                    "contradiction_tolerance_ahead_min": 5,
                    "contradiction_tolerance_behind_h": 24,
                }
            }
        }
    }
    return mapping, api, manifest, cfg


def test_scan_config_from_cfg() -> None:
    cfg = {
        "short_files": {"min_rows_per_file": 7},
        "gaps": {"severe_gap_min": 30},
    }
    sc = ScanConfig.from_cfg(cfg)
    assert sc.min_rows_per_file == 7
    assert sc.severe_gap_min == 30.0
    # 与 e0_full.yaml 冻结值一致（短文件=10 / 严重缺口=20 分钟）
    assert ScanConfig().min_rows_per_file == 10
    assert ScanConfig().severe_gap_min == 20.0


def test_classify_dup_ts_identical_vs_same_timestamp(tmp_path: Path) -> None:
    # 相同 timestamp 且逐字节相同 → identical_dup_rows；相同 timestamp 不同值 → distinct
    f1 = _write_static(
        tmp_path,
        "jpl/Arroyo_Garage_01/1-1-178-817-2019-11-06T14-19-07-900778.csv.gz",
        [
            f"{_iso(0)},0.0",
            f"{_iso(0)},0.0",
            f"{_iso(1)},5.0",
        ],
        header=",Charging Current (A)",
    )
    f2 = _write_static(
        tmp_path,
        "caltech/California_Garage_01/2-39-123-23-2019-03-01T10-00-00-000000.csv.gz",
        [
            f"{_iso(0)},5.0",
            f"{_iso(0)},5.5",
            f"{_iso(1)},6.0",
        ],
        header=",Charging Current (A)",
    )
    m = pd.DataFrame(
        {
            "logical_path": [str(f1.relative_to(tmp_path)), str(f2.relative_to(tmp_path))],
            "site": ["jpl", "caltech"],
            "garage": ["Arroyo_Garage_01", "California_Garage_01"],
            "station": ["s1", "s2"],
            "n_dup_ts": [1, 1],
            "time_min": [None, None],
        }
    )
    sm = {"raw_to_canonical": {"jpl": "jpl", "caltech": "caltech"}}
    rm = {
        "caltech_main": ["2019-03"],
        "jpl_boundary_2020": ["2020-06", "2020-07"],
        "jpl_current_only": ["2019-11"],
    }
    res = classify_dup_ts(m, tmp_path, site_mapping=sm, role_months=rm)
    assert res["dup_ts_files"] == 2
    assert res["identical_dup_rows"] == 1
    assert res["identical_zero_idle_rows"] == 1
    assert res["identical_nonzero_rows"] == 0
    assert res["identical_dup_files"] == 1
    assert res["same_timestamp_distinct_rows"] == 1
    # 文件名嵌入月份：jpl 2019-11 → jpl_current_only；caltech 2019-03 → caltech_main_frozen
    assert res["by_role"]["jpl_current_only"]["identical_dup_rows"] == 1
    assert res["by_role"]["caltech_main_frozen"]["same_timestamp_distinct_rows"] == 1


def test_classify_dup_ts_zero_idle_and_nonzero_split(tmp_path: Path) -> None:
    f = _write_static(
        tmp_path,
        "jpl/Arroyo_Garage_01/1-1-178-817-2019-11-06T14-19-07-900778.csv.gz",
        [
            f"{_iso(0)},0.0",
            f"{_iso(0)},0.0",
            f"{_iso(1)},5.0",
            f"{_iso(1)},5.0",
        ],
        header=",Charging Current (A)",
    )
    m = pd.DataFrame(
        {
            "logical_path": [str(f.relative_to(tmp_path))],
            "site": ["jpl"],
            "garage": ["Arroyo_Garage_01"],
            "station": ["x"],
            "n_dup_ts": [2],
            "time_min": [None],
        }
    )
    res = classify_dup_ts(
        m,
        tmp_path,
        site_mapping={"raw_to_canonical": {"jpl": "jpl"}},
        role_months={"caltech_main": [], "jpl_boundary_2020": [], "jpl_current_only": ["2019-11"]},
    )
    assert res["identical_dup_rows"] == 2
    assert res["identical_zero_idle_rows"] == 1
    assert res["identical_nonzero_rows"] == 1
    assert res["by_role"]["jpl_current_only"]["identical_dup_rows"] == 2
    assert res["by_role"]["jpl_current_only"]["identical_zero_idle_rows"] == 1


def test_classify_dup_ts_writes_csv(tmp_path: Path) -> None:
    f = _write_static(
        tmp_path,
        "jpl/LIGO_01/dup.csv.gz",
        [f"{_iso(0)},0.0", f"{_iso(0)},0.0", f"{_iso(1)},5.0"],
        header=",Charging Current (A)",
    )
    m = pd.DataFrame({"logical_path": [str(f.relative_to(tmp_path))], "n_dup_ts": [1]})
    out = tmp_path / "cls.csv"
    res = classify_dup_ts(m, tmp_path, out_csv=out)
    assert out.exists()
    df = pd.read_csv(out)
    assert df["identical_dup_rows"].sum() == 1
    assert res["identical_dup_rows"] == 1
    # 明细必须带 site_raw/site_canonical/month/role 列（审查结论10 P0-2 机器可验证）
    for col in ("site_raw", "site_canonical", "garage", "station", "month", "role"):
        assert col in df.columns, f"分类 CSV 缺列 {col}"


def test_site_canonical_and_file_role() -> None:
    sm = {"raw_to_canonical": {"office_01": "office001", "caltech": "caltech", "jpl": "jpl"}}
    assert site_canonical("office_01", sm) == "office001"
    assert site_canonical("caltech", sm) == "caltech"
    assert site_canonical("unknown", sm) == "unknown"
    rm = {
        "caltech_main": ["2019-03"],
        "jpl_boundary_2020": ["2020-06", "2020-07"],
        "jpl_current_only": ["2019-03"],
    }
    assert file_role("caltech", "California_Garage_01", "2019-03", sm, rm) == "caltech_main_frozen"
    assert file_role("caltech", "LIGO_01", "2019-03", sm, rm) == "caltech_other"
    assert file_role("jpl", "Arroyo_Garage_01", "2020-06", sm, rm) == "jpl_boundary_2020"
    assert file_role("jpl", "Arroyo_Garage_01", "2019-03", sm, rm) == "jpl_current_only"
    assert file_role("jpl", "Arroyo_Garage_01", "2019-11", sm, rm) == "jpl_other"
    assert file_role("office_01", "Parking_Lot_01", "2020-06", sm, rm) == "office_external"


def test_month_from_logical_path() -> None:
    from patent_preexperiment.e0_full.input_audit import _month_from_logical_path

    assert (
        _month_from_logical_path(
            "jpl/Arroyo_Garage_01/1-1-178-817-2019-09-25T12-27-05-647151.csv.gz"
        )
        == "2019-09"
    )
    assert _month_from_logical_path("no_date.csv.gz") is None


def test_dup_collapse_impact_shares_minute(tmp_path: Path) -> None:
    # identical dup 与同一分钟的异值行并存 → 1-min 均值受影响（否则为零）
    f = _write_static(
        tmp_path,
        "jpl/Arroyo_Garage_01/1-1-178-817-2019-11-06T14-19-07-900778.csv.gz",
        [
            f"{_iso(0)},0.0",
            f"{_iso(0)},0.0",
            f"{_iso(0, sec=30)},5.0",
            f"{_iso(1)},5.0",
        ],
        header=",Charging Current (A)",
    )
    m = pd.DataFrame(
        {
            "logical_path": [str(f.relative_to(tmp_path))],
            "site": ["jpl"],
            "garage": ["Arroyo_Garage_01"],
            "station": ["x"],
            "n_dup_ts": [1],
            "time_min": [None],
        }
    )
    sm = {"raw_to_canonical": {"jpl": "jpl"}}
    rm = {"caltech_main": [], "jpl_boundary_2020": [], "jpl_current_only": []}
    res = dup_collapse_impact(m, tmp_path, site_mapping=sm, role_months=rm)
    assert res["files_scanned"] == 1
    cur = res["by_role"]["jpl_other"]["fields"]["current"]
    assert cur["affected_minutes"] == 1
    assert cur["max_abs_diff"] > 0


def test_dup_collapse_impact_no_effect_when_isolated(tmp_path: Path) -> None:
    # identical dup 独占分钟 → collapse 后 1-min 均值不变
    f = _write_static(
        tmp_path,
        "jpl/Arroyo_Garage_01/1-1-178-817-2019-11-06T14-19-07-900778.csv.gz",
        [f"{_iso(0)},0.0", f"{_iso(0)},0.0", f"{_iso(1)},5.0"],
        header=",Charging Current (A)",
    )
    m = pd.DataFrame(
        {
            "logical_path": [str(f.relative_to(tmp_path))],
            "site": ["jpl"],
            "garage": ["Arroyo_Garage_01"],
            "station": ["x"],
            "n_dup_ts": [1],
            "time_min": [None],
        }
    )
    res = dup_collapse_impact(
        m, tmp_path, site_mapping={"raw_to_canonical": {"jpl": "jpl"}},
        role_months={"caltech_main": [], "jpl_boundary_2020": [], "jpl_current_only": []},
    )
    assert res["files_scanned"] == 1
    assert res["by_role"]["jpl_other"]["affected_files_any_field"] == 0


def test_connection_time_audit_anomaly_not_fallback() -> None:
    # 审查结论9 强制：API connectionTime 可解析但与首条观测明显矛盾 → anomaly，禁止自动替换
    mapping, api, manifest, cfg = _conn_fixtures()
    audit, summary = audit_connection_time(mapping, api, manifest, cfg)

    assert summary["matched"] == 3
    assert summary["fallback"] == 1    # s1：API connectionTime 缺失
    assert summary["api_metadata"] == 1  # s2：可解析且一致
    assert summary["anomaly"] == 1     # s3：可解析但与首条观测明显矛盾（晚 60 min > 5 min）

    by_session = audit.set_index("session_id")["connection_time_source"]
    assert by_session["s1"] == "first_observation_fallback"
    assert by_session["s2"] == "api_metadata"
    assert by_session["s3"] == "anomaly"  # 绝不落入 fallback

    anom = audit[audit["connection_time_source"] == "anomaly"]
    assert (anom["anomaly_reason"] != "").all() and anom["anomaly_reason"].notna().all()


def test_connection_time_audit_missing_unparseable_fallback() -> None:
    mapping, api, manifest, cfg = _conn_fixtures()
    api.loc[api["sessionID"] == "s2", "connectionTime"] = "NOT-A-DATE"
    audit, summary = audit_connection_time(mapping, api, manifest, cfg)
    by_session = audit.set_index("session_id")["connection_time_source"]
    assert by_session["s1"] == "first_observation_fallback"
    assert by_session["s2"] == "first_observation_fallback"  # 无法解析 → 允许自动回退
    assert summary["fallback"] == 2
    assert summary["anomaly"] == 1


def test_connection_time_audit_empty_matched() -> None:
    mapping, api, manifest, cfg = _conn_fixtures()
    mapping["match_status"] = "static_only"
    audit, summary = audit_connection_time(mapping, api, manifest, cfg)
    assert audit.empty
    assert summary["matched"] == 0


def test_load_paths_missing_yaml_gives_copy_hint(tmp_path: Path) -> None:
    # 工程卫生：路径配置缺失时必须提示复制 paths.example.yaml（只在读取路径时触发）
    from patent_preexperiment.io.paths import load_paths

    with pytest.raises(FileNotFoundError, match="paths.example.yaml"):
        load_paths(tmp_path / "does_not_exist.yaml")


def test_fresh_clone_import_works_without_paths_yaml() -> None:
    """审查结论9 工程卫生：fresh clone 无 configs/paths.yaml 时 import 与 pytest 收集可运行。

    将本仓库 configs/paths.yaml 临时移走（若存在），子进程 import 全部顶层模块必须成功。
    """
    paths_yaml = PP / "configs" / "paths.yaml"
    backup: bytes | None = None
    if paths_yaml.exists():
        backup = paths_yaml.read_bytes()
        paths_yaml.unlink()
    try:
        code = (
            "import patent_preexperiment.io.paths; "
            "import patent_preexperiment.io.static; "
            "import patent_preexperiment.registry.k0; "
            "import patent_preexperiment.e0_full.input_audit; "
            "import patent_preexperiment.e0_full.baseline; "
            "print('OK')"
        )
        env = {"PYTHONPATH": str(PP / "src")}
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            cwd=PP,
        )
        assert r.returncode == 0, r.stderr
        assert "OK" in r.stdout
    finally:
        if backup is not None:
            paths_yaml.write_bytes(backup)
