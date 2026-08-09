"""E0F-05 D0 数据链验收审计单元测试（审查结论 14）。

覆盖：_partition_scan（重复/孤儿/路径/治理检测）、audit_uniqueness、
audit_energy_layered（分层 + caltech/office001 门线 + jpl 不做门 + test/K1 关注）、
audit_split_safety、audit_evaluable_aggregation（不发明数值门限）、
audit_pilot_zero_guard、audit_5min_cycle、audit_gold_layered（月度集中度）、
报告生成。不依赖全量数据。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.e0_full import d0_audit as d0

_PP = Path(__file__).resolve().parents[1]
_CONFIG = _PP / "configs" / "e0_full.yaml"

_GOV_COLS = ["session_id", "site", "split", "role", "sample_layer",
             "field_mode", "match_status", "external", "stress"]


def _synth_registry(n_main: int = 6, n_ext: int = 1, n_stress: int = 1) -> pd.DataFrame:
    """单站点 caltech 会话：主切分 60/20/20 + external + stress。"""
    rows: list[dict] = []
    n_tr = int(round(n_main * 0.6))
    n_va = int(round(n_main * 0.2))
    labels = (
        ["train"] * n_tr + ["validation"] * n_va + ["test"] * (n_main - n_tr - n_va)
    )
    for i, lbl in enumerate(labels):
        rows.append({
            "session_id": f"s{i}",
            "site": "caltech",
            "split": lbl,
            "role": "main",
            "sample_layer": "L1_strict_matched",
            "field_mode": "measured_pilot",
            "match_status": "matched",
            "external": False,
            "stress": False,
            "connection_time": f"2018-11-{i + 1:02d} 08:00:00",
        })
    for j in range(n_ext):
        rows.append({
            "session_id": f"ext{j}",
            "site": "caltech",
            "split": "external",
            "role": "external_only",
            "sample_layer": "L1_strict_matched",
            "field_mode": "measured_pilot",
            "match_status": "matched",
            "external": True,
            "stress": False,
            "connection_time": "2018-11-01 08:00:00",
        })
    for k in range(n_stress):
        rows.append({
            "session_id": f"stress{k}",
            "site": "caltech",
            "split": "stress",
            "role": "main",
            "sample_layer": "L1_strict_matched",
            "field_mode": "measured_pilot",
            "match_status": "matched",
            "external": False,
            "stress": True,
            "connection_time": "2018-11-01 08:00:00",
        })
    return pd.DataFrame(rows)


def _write_partition(
    tmp: Path,
    registry: pd.DataFrame,
    rows: list[dict],
    site: str = "caltech",
    year: int = 2018,
    month: int = 11,
) -> Path:
    part_dir = tmp / f"site={site}" / f"year={year}" / f"month={month:02d}"
    part_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=[
        "session_id", "timestamp_utc", "site", "split", "role", "sample_layer",
        "field_mode", "match_status", "external", "stress", "actual_power_kw",
        "energy_cum_kwh", "kwh_delivered", "energy_source",
    ])
    df["external"] = df["external"].astype(bool)
    df["stress"] = df["stress"].astype(bool)
    df.to_parquet(part_dir / "data.parquet", index=False)
    return part_dir / "data.parquet"


def _minute_rows(registry: pd.DataFrame, mins_per_session: int = 3) -> list[dict]:
    rows = []
    for _, r in registry.iterrows():
        start = pd.Timestamp("2018-11-10 08:00:00")
        for k in range(mins_per_session):
            rows.append({
                "session_id": r["session_id"],
                "timestamp_utc": start + pd.Timedelta(minutes=k),
                "site": r["site"],
                "split": r["split"],
                "role": r["role"],
                "sample_layer": r["sample_layer"],
                "field_mode": r["field_mode"],
                "match_status": r["match_status"],
                "external": r["external"],
                "stress": r["stress"],
                "actual_power_kw": 3.0,
                "energy_cum_kwh": 0.05 * (k + 1),
                "kwh_delivered": 0.15,
                "energy_source": "raw",
            })
    return rows


# --- _partition_scan ---

def test_scan_pass_on_clean_partitions(tmp_path: Path) -> None:
    reg = _synth_registry()
    _write_partition(tmp_path, reg, _minute_rows(reg))
    scan = d0._partition_scan(tmp_path, reg, None)
    assert scan["n_files"] == 1
    assert scan["duplicate_key_rows"] == 0
    assert scan["orphan_sessions"] == []
    assert scan["missing_sessions"] == []
    assert scan["path_failures"] == []
    assert scan["governance_failures"] == []
    assert scan["n_sessions_covered"] == len(reg)


def test_scan_detects_duplicate_key(tmp_path: Path) -> None:
    reg = _synth_registry(1)
    rows = _minute_rows(reg)
    rows.append(dict(rows[0]))  # 同一 [session_id, timestamp_utc] 重复
    _write_partition(tmp_path, reg, rows)
    scan = d0._partition_scan(tmp_path, reg, None)
    assert scan["duplicate_key_rows"] == 1


def test_scan_detects_orphan_session(tmp_path: Path) -> None:
    reg = _synth_registry(2)
    rows = _minute_rows(reg)
    rows.append({
        "session_id": "orphan1",
        "timestamp_utc": pd.Timestamp("2018-11-10 09:00:00"),
        "site": "caltech", "split": "train", "role": "main",
        "sample_layer": "L1_strict_matched", "field_mode": "measured_pilot",
        "match_status": "matched", "external": False, "stress": False,
        "actual_power_kw": 3.0, "energy_cum_kwh": 0.1,
        "kwh_delivered": 0.1, "energy_source": "raw",
    })
    _write_partition(tmp_path, reg, rows)
    scan = d0._partition_scan(tmp_path, reg, None)
    assert "orphan1" in scan["orphan_sessions"]


def test_scan_detects_missing_session(tmp_path: Path) -> None:
    reg = _synth_registry(3)
    _write_partition(tmp_path, reg, _minute_rows(reg.iloc[:2]))  # 缺 s2
    scan = d0._partition_scan(tmp_path, reg, None)
    assert "s2" in scan["missing_sessions"]


def test_scan_detects_path_inconsistency(tmp_path: Path) -> None:
    reg = _synth_registry(1)
    rows = _minute_rows(reg)
    rows[0]["timestamp_utc"] = pd.Timestamp("2019-03-10 08:00:00")  # 月份与路径不符
    _write_partition(tmp_path, reg, rows)
    scan = d0._partition_scan(tmp_path, reg, None)
    assert len(scan["path_failures"]) == 1


def test_scan_detects_governance_mismatch(tmp_path: Path) -> None:
    reg = _synth_registry(1)
    rows = _minute_rows(reg)
    rows[0]["split"] = "test"  # 与 registry 的 train 不一致
    _write_partition(tmp_path, reg, rows)
    scan = d0._partition_scan(tmp_path, reg, None)
    assert len(scan["governance_failures"]) == 1


def test_scan_sha_matches_frozen(tmp_path: Path) -> None:
    reg = _synth_registry(1)
    _write_partition(tmp_path, reg, _minute_rows(reg))
    frozen = {"partitions": [
        {"site": "caltech", "year": 2018, "month": 11, "rows": 3, "sha256": "x"}
    ]}
    scan = d0._partition_scan(tmp_path, reg, frozen)
    assert not scan["per_partition"][0]["sha_matches_frozen"]


# --- audit_uniqueness ---

def test_uniqueness_pass(tmp_path: Path) -> None:
    reg = _synth_registry()
    _write_partition(tmp_path, reg, _minute_rows(reg))
    frozen = {"partitions": [
        {"site": "caltech", "year": 2018, "month": 11, "sha256":
         d0._sha256_file(tmp_path / "site=caltech/year=2018/month=11/data.parquet")}
    ]}
    scan = d0._partition_scan(tmp_path, reg, frozen)
    assert d0.audit_uniqueness(scan, frozen)["pass"]


def test_uniqueness_fail_on_dup(tmp_path: Path) -> None:
    reg = _synth_registry(1)
    rows = _minute_rows(reg)
    rows.append(dict(rows[0]))
    _write_partition(tmp_path, reg, rows)
    scan = d0._partition_scan(tmp_path, reg, None)
    assert not d0.audit_uniqueness(scan, {"partitions": []})["pass"]


# --- audit_energy_layered ---

def _scan_audits(values: dict[str, float]) -> list[dict]:
    out = []
    for site, dev in values.items():
        out.append({
            "session_id": f"s_{site}",
            "site": site,
            "match_status": "matched",
            "has_energy": True,
            "n_minutes": 60,
            "integral_kwh": 1.0,
            "energy_first": 0.0,
            "energy_last": 1.0 / (1.0 + dev),
            "ref_api_kwh": 1.0,
        })
    return out


def _energy_registry(audits: list[dict], split: str = "train") -> pd.DataFrame:
    rows = []
    for a in audits:
        rows.append({
            "session_id": a["session_id"],
            "site": a["site"],
            "split": split,
            "role": "main",
            "sample_layer": "L1_strict_matched",
            "field_mode": "measured_pilot",
            "match_status": "matched",
            "external": False,
            "stress": False,
            "connection_time": "2018-11-01 08:00:00",
        })
    return pd.DataFrame(rows)


def _energy_cfg(k1_months: dict[str, list[str]] | None = None) -> dict:
    return {
        "session_response": {"energy_consistency": {"tolerance_median_dev": 0.01}},
        "k1_role_months": k1_months or {},
    }


def test_energy_gate_fails_on_high_caltech_median() -> None:
    audits = _scan_audits({"caltech": 0.05, "jpl": 0.50, "office001": 0.001})
    reg = _energy_registry(audits)
    res = d0.audit_energy_layered({"session_energy_audits": audits}, reg, _energy_cfg())
    assert not res["pass"]


def test_energy_gate_jpl_excluded_from_stop() -> None:
    # jpl 中位 |dev| 巨大也不触发 STOP（聚合可用、会话级离群另报）
    audits = _scan_audits({"caltech": 0.001, "jpl": 0.90, "office001": 0.001})
    reg = _energy_registry(audits)
    res = d0.audit_energy_layered({"session_energy_audits": audits}, reg, _energy_cfg())
    assert res["pass"]


def test_energy_layered_reports_test_and_k1_worst() -> None:
    low = {"session_id": "s_caltech", "site": "caltech", "match_status": "matched",
           "has_energy": True, "n_minutes": 60, "integral_kwh": 1.0,
           "energy_first": 0.0, "energy_last": 0.999, "ref_api_kwh": 1.0}
    high_test = {"session_id": "s_jpl", "site": "jpl", "match_status": "matched",
                 "has_energy": True, "n_minutes": 60, "integral_kwh": 1.0,
                 "energy_first": 0.0, "energy_last": 0.7, "ref_api_kwh": 1.0}
    audits = [low, high_test]
    reg = pd.concat([
        _energy_registry([low]),
        _energy_registry([high_test], split="test"),
    ], ignore_index=True)
    reg.loc[1, "site"] = "jpl"
    reg.loc[1, "connection_time"] = "2019-03-01 08:00:00"
    cfg = _energy_cfg({"jpl_boundary_window": ["2019-03"]})
    res = d0.audit_energy_layered({"session_energy_audits": audits}, reg, cfg)
    assert res["pass"]
    ev = res["evidence"]
    assert ev["worst_test"]["split"] == "test"
    assert ev["worst_k1_months"]["month"] == "2019-03"
    assert ev["bucket_counts"]["gt_20pct"] == 1
    assert "2019-03" in ev["k1_months_frozen"]


# --- audit_split_safety ---

def test_split_safety_pass() -> None:
    reg = _synth_registry(30)
    assert d0.audit_split_safety(reg, {})["pass"]


def test_split_safety_fails_on_external_in_train() -> None:
    reg = _synth_registry(6)
    reg.loc[0, "split"] = "train"
    reg.loc[0, "external"] = True
    assert not d0.audit_split_safety(reg, {})["pass"]


def test_split_safety_fails_on_bad_value() -> None:
    reg = _synth_registry(6)
    reg.loc[0, "split"] = "mystery"
    assert not d0.audit_split_safety(reg, {})["pass"]


# --- audit_evaluable_aggregation ---

def test_evaluable_mechanism_not_invented_gate() -> None:
    cfg = load_yaml(_CONFIG)
    assert d0.audit_evaluable_aggregation(cfg)["pass"]


def test_evaluable_fails_on_invented_threshold() -> None:
    cfg = load_yaml(_CONFIG)
    cfg["evaluable"]["min_core_sessions"] = 5
    assert not d0.audit_evaluable_aggregation(cfg)["pass"]


def test_evaluable_fails_on_unknown_reason() -> None:
    cfg = load_yaml(_CONFIG)
    cfg["evaluable"]["reasons"] = ["no_core_sessions"]
    assert not d0.audit_evaluable_aggregation(cfg)["pass"]


# --- 语义护栏 ---

def test_pilot_zero_guard_consistent() -> None:
    pool = pd.DataFrame({
        "pool_id": ["caltech__California_Garage_01"] * 3,
        "timestamp_utc": pd.date_range("2018-11-01", periods=3, freq="5min"),
        "pilot_coverage": [0.0, 0.0, 1.0],
        "pilot_upper_kw_total": [0.0, 0.0, 12.0],
    })
    res = d0.audit_pilot_zero_guard(pool)
    assert res["pass"]
    assert res["evidence"]["n_pilot_coverage_zero_rows"] == 2


def test_pilot_zero_guard_fails_on_nonzero_upper() -> None:
    pool = pd.DataFrame({
        "pool_id": ["caltech__California_Garage_01"] * 2,
        "timestamp_utc": pd.date_range("2018-11-01", periods=2, freq="5min"),
        "pilot_coverage": [0.0, 0.0],
        "pilot_upper_kw_total": [0.0, 5.0],
    })
    assert not d0.audit_pilot_zero_guard(pool)["pass"]


def test_5min_cycle_audit() -> None:
    pool1 = pd.DataFrame({
        "pool_id": ["p1"] * 5,
        "timestamp_utc": pd.date_range("2018-11-01 00:00:00", periods=5, freq="1min"),
    })
    pool5 = pd.DataFrame({
        "pool_id": ["p1"],
        "timestamp_utc": [pd.Timestamp("2018-11-01 00:00:00")],
    })
    res = d0.audit_5min_cycle(pool1, pool5)
    assert res["evidence"]["n_complete_5min"] == 1
    assert res["evidence"]["n_incomplete"] == 0


def test_5min_cycle_reports_incomplete() -> None:
    pool1 = pd.DataFrame({
        "pool_id": ["p1"] * 3,
        "timestamp_utc": pd.date_range("2018-11-01 00:00:00", periods=3, freq="1min"),
    })
    pool5 = pd.DataFrame({
        "pool_id": ["p1"],
        "timestamp_utc": [pd.Timestamp("2018-11-01 00:00:00")],
    })
    res = d0.audit_5min_cycle(pool1, pool5)
    assert res["evidence"]["n_incomplete"] == 1
    assert res["evidence"]["minutes_distribution"] == {3: 1}


# --- audit_gold_layered ---

def test_gold_layered_monthly_aggregation(tmp_path: Path) -> None:
    gold_dir = tmp_path / "gold"
    (gold_dir / "benchmark_5min").mkdir(parents=True)
    buckets = pd.date_range("2018-11-01", periods=6, freq="5min", tz="UTC")
    gold = pd.DataFrame({
        "timestamp": buckets,
        "energy_kwh": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    })
    gold.to_csv(gold_dir / "benchmark_5min" / "st1.csv", index=False)
    pool_registry = pd.DataFrame({
        "pool_id": ["caltech__California_Garage_01"],
        "station": ["st1"],
    })
    pool5 = pd.DataFrame({
        "pool_id": ["caltech__California_Garage_01"] * 3,
        "timestamp_utc": buckets[:3],
        "measured_kwh": [0.99, 0.99, 0.99],
        "estimated_kwh": [0.0, 0.0, 0.0],
    })
    cfg = {
        "pool": {
            "gold": {
                "pools": [{"site": "caltech", "garage": "California_Garage_01"}],
                "tolerance_median_rel_dev": 0.02,
            }
        }
    }
    res = d0.audit_gold_layered(pool_registry, pool5, cfg, gold_dir=gold_dir)
    assert res["pass"]
    per_pool = res["evidence"]["monthly_per_pool"]["caltech__California_Garage_01"]
    assert per_pool["worst_month"] == "2018-11"
    assert per_pool["worst_abs_rel_dev"] == pytest.approx(0.505, abs=1e-3)
    assert per_pool["total_gold_kwh"] == pytest.approx(6.0, abs=1e-6)


# --- 报告与契约 ---

def test_gate_names_match_acceptance_config() -> None:
    cfg = load_yaml(_CONFIG)
    assert set(d0.GATE_NAMES) == set(cfg["acceptance"].keys())


def test_report_contains_all_gates() -> None:
    gates = {name: {"pass": True, "evidence": {"k": "v"}} for name in d0.GATE_NAMES}
    semantic = {
        "cycle": {"evidence": {"n_complete_5min": 1, "n_incomplete": 0,
                               "share_incomplete": 0.0, "minutes_distribution": {5: 1}}},
        "pilot_zero": {"evidence": {"n_pilot_coverage_zero_rows": 0,
                                    "rows_pilot_zero_but_upper_nonzero": 0}},
    }
    report = d0._build_report(gates, semantic, {
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "code_sha": "0" * 40,
        "session_response": {"n_partitions": 81, "n_rows": 1, "n_sessions": 1},
    })
    assert report.startswith("# E0F-05")
    for name in d0.GATE_NAMES:
        assert f"| {name} |" in report


def test_d0_outputs_registered_in_config() -> None:
    cfg = load_yaml(_CONFIG)
    assert cfg["outputs"]["d0_report"] == "reports/E0_Full_D0_acceptance_audit.md"
    assert cfg["outputs"]["d0_registry"] == "data_registry/e0_full_d0_registry.json"


def test_baseline_schema_has_d0() -> None:
    schema = json.loads(
        (_PP / "data_registry" / "e0_full_baseline.schema.json").read_text(encoding="utf-8")
    )
    assert "d0" in schema["required"]
    assert set(schema["properties"]["d0"]["required"]) == {
        "d0_pass", "gates", "baseline_code_sha", "report"
    }
