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
    _sensitivity_stop_reason,
    audit_connection_time,
    build_source_manifest,
    classify_dup_ts,
    current_only_full_pool_sensitivity,
    current_only_sensitivity,
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
        "caltech_main_window": ["2019-03"],
        "jpl_boundary_window": ["2020-06", "2020-07"],
        "jpl_current_only_window": ["2019-11"],
    }
    res = classify_dup_ts(m, tmp_path, site_mapping=sm, role_months=rm)
    assert res["dup_ts_files"] == 2
    assert res["identical_dup_rows"] == 1
    assert res["identical_zero_idle_rows"] == 1
    assert res["identical_nonzero_rows"] == 0
    assert res["identical_dup_files"] == 1
    assert res["same_timestamp_distinct_rows"] == 1
    # 文件名嵌入月份：jpl 2019-11 → jpl_current_only_window；caltech 2019-03 → caltech_main_window
    assert res["by_role"]["jpl_current_only_window"]["identical_dup_rows"] == 1
    assert res["by_role"]["caltech_main_window"]["same_timestamp_distinct_rows"] == 1


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
        role_months={
            "caltech_main_window": [],
            "jpl_boundary_window": [],
            "jpl_current_only_window": ["2019-11"],
        },
    )
    assert res["identical_dup_rows"] == 2
    assert res["identical_zero_idle_rows"] == 1
    assert res["identical_nonzero_rows"] == 1
    assert res["by_role"]["jpl_current_only_window"]["identical_dup_rows"] == 2
    assert res["by_role"]["jpl_current_only_window"]["identical_zero_idle_rows"] == 1


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
    # 审查结论11 P1：明细逐文件登记 eligibility，role 仅作月份窗口代理
    for col in ("has_current", "has_pilot", "has_voltage", "has_power"):
        assert col in df.columns, f"分类 CSV 缺 eligibility 列 {col}"


def test_site_canonical_and_file_role() -> None:
    sm = {"raw_to_canonical": {"office_01": "office001", "caltech": "caltech", "jpl": "jpl"}}
    assert site_canonical("office_01", sm) == "office001"
    assert site_canonical("caltech", sm) == "caltech"
    assert site_canonical("unknown", sm) == "unknown"
    rm = {
        "caltech_main_window": ["2019-03"],
        "jpl_boundary_window": ["2020-06", "2020-07"],
        "jpl_current_only_window": ["2019-03"],
    }
    assert file_role("caltech", "California_Garage_01", "2019-03", sm, rm) == "caltech_main_window"
    assert file_role("caltech", "LIGO_01", "2019-03", sm, rm) == "caltech_other"
    assert file_role("jpl", "Arroyo_Garage_01", "2020-06", sm, rm) == "jpl_boundary_window"
    assert file_role("jpl", "Arroyo_Garage_01", "2019-03", sm, rm) == "jpl_current_only_window"
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
    rm = {
        "caltech_main_window": [],
        "jpl_boundary_window": [],
        "jpl_current_only_window": [],
    }
    rated = {"jpl": 192.7, "caltech": 240.0, "office001": 240.0}
    res = dup_collapse_impact(
        m, tmp_path, site_mapping=sm, role_months=rm, rated_voltage=rated
    )
    assert res["files_scanned"] == 1
    cur = res["by_role"]["jpl_other"]["fields"]["current"]
    assert cur["affected_minutes"] == 1
    assert cur["max_abs_diff"] > 0
    # 审查结论11 P0：current-only 在派生层经 rated 192.7 传播，actual_power 不再零影响
    dp = res["derived_power"]["by_role"]["jpl_other"]
    assert dp["affected_minutes"] == 1
    assert dp["max_abs_diff_kw"] == pytest.approx(0.833333 * 192.7 / 1000.0, abs=1e-6)
    assert res["derived_power"]["rule"] != ""


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
        role_months={
            "caltech_main_window": [],
            "jpl_boundary_window": [],
            "jpl_current_only_window": [],
        },
        rated_voltage={"jpl": 192.7, "caltech": 240.0, "office001": 240.0},
    )
    assert res["files_scanned"] == 1
    assert res["by_role"]["jpl_other"]["affected_files_any_field"] == 0
    # 派生层同分钟均值：独立独占分钟的 0.0 与 5.0 两口径一致 → actual_power 也不受影响
    assert res["derived_power"]["by_role"]["jpl_other"]["affected_minutes"] == 0


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


def _iso19(minutes: int, sec: int = 0) -> str:
    base = pd.Timestamp("2019-03-06 14:00:00", tz="UTC")
    return (base + pd.Timedelta(minutes=minutes, seconds=sec)).isoformat()


def test_current_only_sensitivity_structure_and_active_flip(tmp_path: Path) -> None:
    """审查结论11 P0：current-only exact-duplicate 在冻结月份窗口上跑 E3 门敏感性。

    min0 同分钟含 0.0×3（identical dup）+ 6.0（distinct）：keep 分钟均值 1.5A（0.289kW，非工作），
    collapse 分钟均值 3.0A（0.578kW，工作）→ 该分钟工作状态翻转 → 5min 周期活跃标记翻转。
    """
    f = _write_static(
        tmp_path,
        "jpl/Arroyo_Garage_01/1-1-178-817-2019-03-06T14-19-07-900778.csv.gz",
        [
            f"{_iso19(0)},0.0",
            f"{_iso19(0)},0.0",
            f"{_iso19(0)},0.0",
            f"{_iso19(0)},6.0",
            f"{_iso19(1)},0.0",
            f"{_iso19(2)},0.0",
            f"{_iso19(3)},6.0",
            f"{_iso19(4)},6.0",
        ],
        header=",Charging Current (A)",
    )
    m = pd.DataFrame(
        {
            "logical_path": [str(f.relative_to(tmp_path))],
            "site": ["jpl"],
            "garage": ["Arroyo_Garage_01"],
            "station": ["x"],
            "n_dup_ts": [3],
            "time_min": [None],
        }
    )
    sm = {"raw_to_canonical": {"jpl": "jpl"}}
    rm = {
        "caltech_main_window": [],
        "jpl_boundary_window": [],
        "jpl_current_only_window": ["2019-03"],
    }
    rated = {"jpl": 192.7, "caltech": 240.0, "office001": 240.0}
    res = current_only_sensitivity(
        m, tmp_path, site_mapping=sm, role_months=rm,
        rated_voltage=rated, p_on_kw=0.5, e3_stop={
            "caltech_a2_daily_ci_lower_rate": 0.01,
            "daily_energy_share_each_pool": 0.005,
        },
    )
    assert res["input_untouched"] is True
    assert res["files_scanned"] == 1
    assert res["frozen_months"] == ["2019-03"]
    # low_power_state：keep 0.6（min0 被 0.0 复制拖低） vs collapse 0.4
    assert res["low_power_state"]["keep"]["ratio"] == pytest.approx(0.6)
    assert res["low_power_state"]["collapse"]["ratio"] == pytest.approx(0.4)
    # 单会话池 n_active<2 → 无候选窗口；结构必须齐全
    assert res["e3_a2"]["keep"]["cycle_weighted_rate"] == 0.0
    assert res["e3_a2"]["collapse"]["day_rate_ci_lower"] is None
    assert res["gate"]["gate_flipped"] is False
    # 周期级活跃标记翻转（keep 0.4 → collapse 0.6）
    assert res["flips"]["active_flips"] == 1


def test_current_only_sensitivity_empty_when_no_dup(tmp_path: Path) -> None:
    """非重复（n_dup_ts=0）current-only 文件不进入敏感性。"""
    f = _write_static(
        tmp_path,
        "jpl/Arroyo_Garage_01/1-1-178-817-2019-03-06T14-19-07-900778.csv.gz",
        [f"{_iso19(0)},6.0"],
        header=",Charging Current (A)",
    )
    m = pd.DataFrame(
        {
            "logical_path": [str(f.relative_to(tmp_path))],
            "site": ["jpl"],
            "garage": ["Arroyo_Garage_01"],
            "station": ["x"],
            "n_dup_ts": [0],
            "time_min": [None],
        }
    )
    res = current_only_sensitivity(
        m, tmp_path, site_mapping={"raw_to_canonical": {"jpl": "jpl"}},
        role_months={"jpl_current_only_window": ["2019-03"]},
        rated_voltage={"jpl": 192.7},
    )
    assert res["files_scanned"] == 0
    assert res["gate"]["gate_flipped"] is False


# ---- 审查结论12 P0：完整 JPL current-only 母体 keep-vs-collapse 敏感性（E0F-01.3）----


def _build_jpl_session_minute(
    raw_rows: list[str], sid: str, station: str, rated_v: float = 192.7
) -> pd.DataFrame:
    """合成静态 csv.gz 行 → 生产路径 1min 会话表（aggregate_session_minute）。"""
    import tempfile

    from patent_preexperiment.io.static import read_static_csv
    from patent_preexperiment.response.session import aggregate_session_minute

    with tempfile.NamedTemporaryFile(suffix=".csv.gz", delete=False) as tf:
        with gzip.open(tf.name, "wb") as fh:
            fh.write((_HEADER + "\n").encode("utf-8"))
            for line in raw_rows:
                fh.write((line + "\n").encode("utf-8"))
        raw = read_static_csv(tf.name)
    return aggregate_session_minute(
        raw, rated_v, session_id=sid, station_id=station, site="jpl",
        garage="Arroyo_Garage_01",
    )


def _iso19(minutes: int, sec: int = 0, day: int = 6) -> str:
    base = pd.Timestamp(f"2019-03-0{day} 23:00:00", tz="UTC")
    return (base + pd.Timedelta(minutes=minutes, seconds=sec)).isoformat()


def test_current_only_full_pool_sensitivity_keep_reproduces_and_collapse_local(
    tmp_path: Path,
) -> None:
    """审查结论12 P0：完整冻结母体 keep-vs-collapse，仅替换含 exact-dup 的母体成员会话。

    合成 3 个 jpl 会话（同日同池，n_active>=2 形成候选窗口）：A 受影响（含 0.0 identical
    dup）、B/C 不受影响。Keep 臂原样跑 E3 管线复现合成冻结基线（传 frozen_baseline=Keep 输出）；
    Collapse 臂仅替换 A 的会话分钟，B/C 逐字节不变。验证 5 项验收逻辑全部成立。
    """
    rated = {"jpl": 192.7, "caltech": 240.0, "office001": 240.0}
    sm = {"raw_to_canonical": {"jpl": "jpl"}}
    rm = {"jpl_current_only_window": ["2019-03"]}
    e3_stop = {"caltech_a2_daily_ci_lower_rate": 0.01, "daily_energy_share_each_pool": 0.005}

    # 会话 A：受影响（min0 含 3 行 0.0 identical dup + 1 行 6.0 distinct），03-06
    raw_a = [
        f"{_iso19(0)},0.0", f"{_iso19(0)},0.0", f"{_iso19(0)},0.0", f"{_iso19(0)},6.0",
        *[f"{_iso19(m)},6.0" for m in range(1, 30)],
    ]
    # 会话 B：不受影响，03-06
    raw_b = [f"{_iso19(m, day=6)},6.0" for m in range(0, 30)]
    # 会话 C：不受影响，03-07（跨 2 天供 bootstrap CI）
    raw_c = [f"{_iso19(m, day=7)},6.0" for m in range(0, 30)]

    min_a = _build_jpl_session_minute(raw_a, "sessA", "1-1-1")
    min_b = _build_jpl_session_minute(raw_b, "sessB", "1-1-2")
    min_c = _build_jpl_session_minute(raw_c, "sessC", "1-1-3")
    keep_table = pd.concat([min_a, min_b, min_c], ignore_index=True)

    minute_path = tmp_path / "lite_session_minute.parquet"
    keep_table.to_parquet(minute_path, index=False)

    # sample registry：static_file 用反斜杠（与 resolve_static 一致）
    reg = pd.DataFrame([
        {"site": "jpl", "garage": "Arroyo_Garage_01", "stationID": "1-1-1",
         "static_file": "jpl\\Arroyo_Garage_01\\sessA.csv.gz", "sessionID": "sessA",
         "sample_role": "E3_pool", "month": "2019-03"},
        {"site": "jpl", "garage": "Arroyo_Garage_01", "stationID": "1-1-2",
         "static_file": "jpl\\Arroyo_Garage_01\\sessB.csv.gz", "sessionID": "sessB",
         "sample_role": "E3_pool", "month": "2019-03"},
        {"site": "jpl", "garage": "Arroyo_Garage_01", "stationID": "1-1-3",
         "static_file": "jpl\\Arroyo_Garage_01\\sessC.csv.gz", "sessionID": "sessC",
         "sample_role": "E3_pool", "month": "2019-03"},
    ])
    reg_path = tmp_path / "k1_sample_registry.csv"
    reg.to_csv(reg_path, index=False)

    # classification CSV：仅 A 标记 identical_dup_rows>0
    clf = pd.DataFrame([
        {"logical_path": "jpl/Arroyo_Garage_01/sessA.csv.gz", "site_raw": "jpl",
         "site_canonical": "jpl", "garage": "Arroyo_Garage_01", "station": "1-1-1",
         "month": "2019-03", "role": "jpl_current_only_window",
         "has_current": True, "has_pilot": False, "has_voltage": False, "has_power": False,
         "n_dup_ts": 1, "identical_dup_rows": 2,
         "identical_zero_idle_rows": 2, "identical_nonzero_rows": 0,
         "same_timestamp_distinct_rows": 1},
    ])
    clf_path = tmp_path / "e0_full_dup_ts_classification.csv"
    clf.to_csv(clf_path, index=False)

    # 写受影响会话 A 的 raw static 文件（供 collapse 重建读取）
    _write_static(
        tmp_path, "jpl/Arroyo_Garage_01/sessA.csv.gz", raw_a,
    )

    # 先跑一次 Keep 拿到合成冻结基线值，作为 frozen_baseline 传入
    from patent_preexperiment.e0_full.input_audit import (
        current_only_full_pool_sensitivity as _run_keep,
    )
    keep_probe = _run_keep(
        minute_table_path=minute_path, sample_registry_path=reg_path,
        classification_csv_path=clf_path, static_root=tmp_path,
        site_mapping=sm, role_months=rm, rated_voltage=rated, e3_stop=e3_stop,
        frozen_baseline={"n_cycles": -1, "a2_cycle_weighted_rate": -1.0,
                         "a2_day_rate": -1.0, "a2_day_rate_ci95": [-1.0, -1.0],
                         "daily_energy_share_median": -1.0, "gate": "PASS"},
    )
    assert keep_probe["keep_reproduces_frozen_baseline"] is False  # 占位基线不匹配
    ke = keep_probe["keep"]
    synth_frozen = {
        "n_cycles": ke["n_cycles"],
        "a2_cycle_weighted_rate": ke["a2_cycle_weighted_rate"],
        "a2_day_rate": ke["a2_day_rate"],
        "a2_day_rate_ci95": ke["a2_day_rate_ci95"],
        "daily_energy_share_median": ke["daily_energy_share_median"],
        "gate": "PASS" if ke["a2_day_rate_ci_lower"] and ke["a2_day_rate_ci_lower"] >= 0.01
        and ke["daily_energy_share_median"] and ke["daily_energy_share_median"] >= 0.005
        else "FAIL",
    }

    res = current_only_full_pool_sensitivity(
        minute_table_path=minute_path, sample_registry_path=reg_path,
        classification_csv_path=clf_path, static_root=tmp_path,
        site_mapping=sm, role_months=rm, rated_voltage=rated, e3_stop=e3_stop,
        frozen_baseline=synth_frozen,
    )

    # Keep 必须复现合成冻结基线
    assert res["keep_reproduces_frozen_baseline"] is True
    # 母体 membership：3 个冻结会话，1 个受影响在母体内，2 个未受影响
    pop = res["population"]
    assert pop["n_frozen_sessions"] == 3
    assert pop["n_affected_sessions_found_in_frozen_population"] == 1
    assert pop["n_affected_sessions_not_in_population"] == 0
    assert pop["n_population_sessions_untouched"] == 2
    # 硬一致性：母体不变、未受影响 session 逐字节一致、无额外分钟、site/garage 不变
    cons = res["consistency"]
    assert cons["population_identity_preserved"] is True
    assert cons["nonaffected_sessions_unchanged"] is True
    assert cons["no_extra_or_missing_minutes"] is True
    assert cons["site_garage_unchanged"] is True
    assert cons["nonaffected_actual_power_zero_diff"] is True
    # 输入未修改
    assert res["input_untouched"] is True
    # 结构完整性：collapse/gate/acceptance 齐全
    assert res["collapse"] is not None
    assert res["gate"] is not None
    acc = res["acceptance"]
    assert "keep_reproduces_frozen_baseline" in acc
    assert "population_identity_preserved" in acc
    assert "nonaffected_sessions_unchanged" in acc
    assert "keep_gate" in acc
    assert "collapse_gate" in acc
    assert "gate_flipped" in acc
    # 审查结论13 P1：flip 对齐唯一 cycle，诊断字段齐全
    fl = res["flips"]
    assert fl["candidate_key_unique_keep"] is True
    assert fl["candidate_key_unique_collapse"] is True
    assert fl["n_unique_candidate_cycles_keep"] > 0
    assert fl["n_unique_candidate_cycles_collapse"] > 0


def test_current_only_full_pool_sensitivity_stop_when_keep_not_reproduced(
    tmp_path: Path,
) -> None:
    """Keep 不能复现冻结基线（传不匹配的 frozen_baseline）→ 立即 STOP，不生成 collapse。"""
    rated = {"jpl": 192.7}
    sm = {"raw_to_canonical": {"jpl": "jpl"}}
    rm = {"jpl_current_only_window": ["2019-03"]}
    raw_b = [f"{_iso19(m)},6.0" for m in range(0, 30)]
    min_b = _build_jpl_session_minute(raw_b, "sessB", "1-1-2")
    minute_path = tmp_path / "lite.parquet"
    min_b.to_parquet(minute_path, index=False)
    reg = pd.DataFrame([{"site": "jpl", "garage": "Arroyo_Garage_01", "stationID": "1-1-2",
                         "static_file": "jpl\\Arroyo_Garage_01\\sessB.csv.gz",
                         "sessionID": "sessB", "sample_role": "E3_pool", "month": "2019-03"}])
    reg_path = tmp_path / "reg.csv"
    reg.to_csv(reg_path, index=False)
    clf = pd.DataFrame(columns=[
        "logical_path", "site_raw", "site_canonical", "garage", "station", "month",
        "role", "has_current", "has_pilot", "has_voltage", "has_power",
        "n_dup_ts", "identical_dup_rows", "identical_zero_idle_rows",
        "identical_nonzero_rows", "same_timestamp_distinct_rows",
    ])
    clf_path = tmp_path / "clf.csv"
    clf.to_csv(clf_path, index=False)

    res = current_only_full_pool_sensitivity(
        minute_table_path=minute_path, sample_registry_path=reg_path,
        classification_csv_path=clf_path, static_root=tmp_path,
        site_mapping=sm, role_months=rm, rated_voltage=rated,
        frozen_baseline={"n_cycles": 999999, "a2_cycle_weighted_rate": 0.999,
                         "a2_day_rate": 0.999, "a2_day_rate_ci95": [0.999, 0.999],
                         "daily_energy_share_median": 0.999, "gate": "PASS"},
    )
    assert res["keep_reproduces_frozen_baseline"] is False
    assert res["collapse"] is None
    assert res["stop"] is not None
    assert "KEEP_NOT_REPRODUCED" in res["stop"]


# ---- 审查结论13 P0-3：STOP 失败路径单测（collapse_gate / gate_flipped 必须 STOP）----


def test_sensitivity_stop_reason_collapse_gate_not_pass() -> None:
    """collapse 臂 E3 门不 PASS → 一定 STOP（COLLAPSE_GATE_NOT_PASS）。"""
    stop = _sensitivity_stop_reason(
        keep_reproduces=True,
        population_identity_preserved=True,
        rebuild_failed=[],
        nonaffected_unchanged=True,
        no_extra_minutes=True,
        site_garage_unchanged=True,
        nonaffected_apk_zero_diff=True,
        keep_gate=True,
        collapse_gate=False,
        gate_flipped=True,
    )
    assert stop == "COLLAPSE_GATE_NOT_PASS"


def test_sensitivity_stop_reason_gate_flipped() -> None:
    """gate_flipped=True（两臂判定不一致）→ 一定 STOP（GATE_FLIPPED）。"""
    stop = _sensitivity_stop_reason(
        keep_reproduces=True,
        population_identity_preserved=True,
        rebuild_failed=[],
        nonaffected_unchanged=True,
        no_extra_minutes=True,
        site_garage_unchanged=True,
        nonaffected_apk_zero_diff=True,
        keep_gate=True,
        collapse_gate=True,
        gate_flipped=True,
    )
    assert stop == "GATE_FLIPPED"


def test_sensitivity_stop_reason_consistency_checks_block_signing() -> None:
    """审查结论13 P0-2：rebuild 失败与硬一致性检查全部进 STOP，异常不得静默通过。"""

    def _call(
        *,
        keep: bool = True,
        identity: bool = True,
        rebuild: list[str] | None = None,
        unchanged: bool = True,
        extra: bool = True,
        site: bool = True,
        apk: bool = True,
        keep_gate: bool = True,
        collapse_gate: bool = True,
        flipped: bool = False,
    ) -> str | None:
        return _sensitivity_stop_reason(
            keep,
            identity,
            rebuild or [],
            unchanged,
            extra,
            site,
            apk,
            keep_gate,
            collapse_gate,
            flipped,
        )

    assert _call(rebuild=["s1"]) == "REBUILD_FAILED_SESSIONS"
    assert _call(extra=False) == "EXTRA_OR_MISSING_MINUTES"
    assert _call(site=False) == "SITE_GARAGE_CHANGED"
    assert _call(apk=False) == "NONAFFECTED_ACTUAL_POWER_CHANGED"
    assert _call(unchanged=False) == "NONAFFECTED_SESSIONS_CHANGED"
    assert _call(identity=False) == "POPULATION_IDENTITY_BROKEN"
    assert _call(keep_gate=False) == "KEEP_GATE_NOT_PASS"
    assert _call() is None


def test_current_only_full_pool_sensitivity_stop_when_collapse_gate_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真实管线路径：collapse 臂 CI 下界与日能量占比跌破停止线 → stop=COLLAPSE_GATE_NOT_PASS。

    通过 monkeypatch _run_jpl_current_only_e3 控制两臂 E3 输出（Keep 复现冻结基线、
    Collapse 门不 PASS），验证 STOP 判定真正接入完整池敏感性函数。
    """
    import patent_preexperiment.e0_full.input_audit as mod

    raw_b = [f"{_iso19(m)},6.0" for m in range(0, 30)]
    min_b = _build_jpl_session_minute(raw_b, "sessB", "1-1-2")
    minute_path = tmp_path / "lite.parquet"
    min_b.to_parquet(minute_path, index=False)
    reg = pd.DataFrame([{"site": "jpl", "garage": "Arroyo_Garage_01", "stationID": "1-1-2",
                         "static_file": "jpl\\Arroyo_Garage_01\\sessB.csv.gz",
                         "sessionID": "sessB", "sample_role": "E3_pool", "month": "2019-03"}])
    reg_path = tmp_path / "reg.csv"
    reg.to_csv(reg_path, index=False)
    clf = pd.DataFrame(columns=[
        "logical_path", "site_raw", "site_canonical", "garage", "station", "month",
        "role", "has_current", "has_pilot", "has_voltage", "has_power",
        "n_dup_ts", "identical_dup_rows", "identical_zero_idle_rows",
        "identical_nonzero_rows", "same_timestamp_distinct_rows",
    ])
    clf_path = tmp_path / "clf.csv"
    clf.to_csv(clf_path, index=False)

    main = "A2_prev_actual"
    empty_cand = pd.DataFrame(columns=[
        "site", "garage", "cycle", "day", "month", "month_conn",
        f"candidate_{main}", f"candidate_energy_{main}_kwh",
    ])
    empty_cyc = pd.DataFrame(columns=["site", "garage", "session_id", "cycle", "active"])
    keep_e3 = {
        "n_cycles": 100, "n_days": 10, "n_pool_months": 1,
        "a2_cycle_weighted_rate": 0.4, "a2_day_rate": 0.36,
        "a2_day_rate_ci95": [0.34, 0.38], "a2_day_rate_ci_lower": 0.34,
        "daily_energy_share_median": 0.039, "daily_energy_share_mean": 0.04,
        "candidate_energy_total_kwh": 100.0,
        "_cand": empty_cand.copy(), "_cyc": empty_cyc.copy(),
    }
    coll_e3 = {
        "n_cycles": 100, "n_days": 10, "n_pool_months": 1,
        "a2_cycle_weighted_rate": 0.3, "a2_day_rate": 0.2,
        "a2_day_rate_ci95": [0.005, 0.4], "a2_day_rate_ci_lower": 0.005,
        "daily_energy_share_median": 0.003, "daily_energy_share_mean": 0.004,
        "candidate_energy_total_kwh": 50.0,
        "_cand": empty_cand.copy(), "_cyc": empty_cyc.copy(),
    }
    calls: list[str] = []

    def _fake_e3(
        minute_df: pd.DataFrame, frozen_months: set[str], seed: int, n_boot: int
    ) -> dict[str, object]:
        calls.append("coll" if len(calls) else "keep")
        return coll_e3 if calls[-1] == "coll" else keep_e3

    monkeypatch.setattr(mod, "_run_jpl_current_only_e3", _fake_e3)

    res = current_only_full_pool_sensitivity(
        minute_table_path=minute_path, sample_registry_path=reg_path,
        classification_csv_path=clf_path, static_root=tmp_path,
        site_mapping={"raw_to_canonical": {"jpl": "jpl"}},
        role_months={"jpl_current_only_window": ["2019-03"]},
        rated_voltage={"jpl": 192.7},
        e3_stop={"caltech_a2_daily_ci_lower_rate": 0.01, "daily_energy_share_each_pool": 0.005},
        frozen_baseline={"n_cycles": 100, "a2_cycle_weighted_rate": 0.4,
                         "a2_day_rate": 0.36, "a2_day_rate_ci95": [0.34, 0.38],
                         "daily_energy_share_median": 0.039, "gate": "PASS"},
    )
    assert calls == ["keep", "coll"]
    assert res["keep_reproduces_frozen_baseline"] is True
    assert res["gate"]["keep_gate"] is True
    assert res["gate"]["collapse_gate"] is False
    assert res["gate"]["gate_flipped"] is True
    assert res["stop"] == "COLLAPSE_GATE_NOT_PASS"
