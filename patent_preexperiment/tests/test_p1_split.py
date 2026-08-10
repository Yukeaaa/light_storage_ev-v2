"""P1 office001 切分冻结测试（Phase 3 v1.0.2 §1.4）。

覆盖：只取 office001 ∧ L1_strict_matched；站点内 60/20/20 与金标准 assign_split 逐会话
一致；stress 会话不进主切分；static_only/其他站点排除；registry 不含任何 E1 字段。
"""

from __future__ import annotations

import pandas as pd
import pytest

from patent_preexperiment.p1.split import (
    _REGISTRY_COLUMNS,
    assign_split,
    build_p1_split_registry,
)


def _synth_e0_registry(n_matched: int = 100, n_static: int = 5, n_stress: int = 8) -> pd.DataFrame:
    """合成 E0F-02 风格 registry：office001 matched + stress + static_only + caltech。"""
    start = pd.Timestamp("2019-03-01 08:00:00", tz="UTC")
    rows: list[dict] = []
    for i in range(n_matched):
        rows.append({
            "session_id": f"off_m{i:04d}",
            "site_canonical": "office001",
            "garage": "Parking_Lot_01",
            "station": f"PL-{i % 3}",
            "connection_time": start + pd.Timedelta(minutes=10 * i),
            "connection_time_source": "api_metadata",
            "field_mode": "measured_pilot",
            "match_status": "matched",
            "sample_layer": "L1_strict_matched",
            "role": "external_only",
            "split": "external",
            "split_rule_version": "e0_full_split_v1",
            "stress": i >= n_matched - n_stress,
            "source_file": f"f{i}.csv",
            "anomaly_flag": False,
            "anomaly_reason": None,
        })
    for i in range(n_static):
        rows.append({
            "session_id": f"off_s{i:04d}",
            "site_canonical": "office001",
            "garage": "Parking_Lot_01",
            "station": f"PL-{i}",
            "connection_time": start + pd.Timedelta(minutes=10 * (i + 5000)),
            "connection_time_source": "first_observation_fallback",
            "field_mode": "measured_no_pilot",
            "match_status": "static_only",
            "sample_layer": "L0_static_extension",
            "role": "external_only",
            "split": "external",
            "split_rule_version": "e0_full_split_v1",
            "stress": False,
            "source_file": f"s{i}.csv",
            "anomaly_flag": False,
            "anomaly_reason": None,
        })
    for i in range(3):
        rows.append({
            "session_id": f"cal{i:04d}",
            "site_canonical": "caltech",
            "garage": "California_Garage_01",
            "station": f"CG-{i}",
            "connection_time": start + pd.Timedelta(minutes=10 * (i + 9000)),
            "connection_time_source": "api_metadata",
            "field_mode": "measured_pilot",
            "match_status": "matched",
            "sample_layer": "L1_strict_matched",
            "role": "main",
            "split": "train",
            "split_rule_version": "e0_full_split_v1",
            "stress": False,
            "source_file": f"c{i}.csv",
            "anomaly_flag": False,
            "anomaly_reason": None,
        })
    return pd.DataFrame(rows)


def _p1_cfg() -> dict:
    return {
        "site": "office001",
        "rule_version": "p1_office001_split_v1",
        "split": {
            "population": "office001 ∧ sample_layer==L1_strict_matched",
            "rule": "60/20/20",
        },
    }


def test_only_office001_matched():
    reg = _synth_e0_registry()
    out = build_p1_split_registry(reg, _p1_cfg())
    assert set(out["site_canonical"]) == {"office001"}
    assert set(out["sample_layer"]) == {"L1_strict_matched"}
    assert set(out["match_status"]) == {"matched"}


def test_static_only_and_other_sites_excluded():
    reg = _synth_e0_registry()
    out = build_p1_split_registry(reg, _p1_cfg())
    assert not (out["session_id"].str.startswith("off_s")).any()
    assert not (out["session_id"].str.startswith("cal")).any()


def test_split_ratios_and_golden_alignment():
    reg = _synth_e0_registry(n_matched=100, n_stress=8)
    out = build_p1_split_registry(reg, _p1_cfg())
    elig = out[out["split"] != "stress"].copy()
    golden = assign_split(
        elig[["session_id", "connection_time"]].assign(
            site="office001", is_external=False, is_stress=False
        )
    )
    got = elig.set_index("session_id")["split"]
    assert (got == golden.set_index("session_id")["split"]).all()
    assert int((out["split"] == "train").sum()) == int(round(92 * 0.6))
    assert int((out["split"] == "validation").sum()) == int(round(92 * 0.2))
    assert int((out["split"] == "test").sum()) == 92 - int(round(92 * 0.6)) - int(round(92 * 0.2))


def test_stress_sessions_marked_stress_not_in_main():
    reg = _synth_e0_registry(n_matched=100, n_stress=8)
    out = build_p1_split_registry(reg, _p1_cfg())
    stress_ids = reg.loc[reg["stress"], "session_id"]
    assert set(out.loc[out["split"] == "stress", "session_id"]) == set(stress_ids)
    assert not (out["stress"] & out["split"].isin(["train", "validation", "test"])).any()


def test_registry_columns_no_e1_fields():
    out = build_p1_split_registry(_synth_e0_registry(), _p1_cfg())
    assert list(out.columns) == _REGISTRY_COLUMNS
    for bad in ("e1_event", "event_phase", "recent_var", "rate_ratio"):
        assert bad not in out.columns


def test_empty_matched_raises():
    reg = _synth_e0_registry(n_matched=0)
    with pytest.raises(ValueError):
        build_p1_split_registry(reg, _p1_cfg())


def test_duplicate_session_raises():
    reg = _synth_e0_registry(n_matched=10)
    reg = pd.concat([reg, reg.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError):
        build_p1_split_registry(reg, _p1_cfg())
