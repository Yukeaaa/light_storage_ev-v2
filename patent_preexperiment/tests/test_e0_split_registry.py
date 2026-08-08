"""E0F-02 时间切分 / 样本层 / 角色 / field_mode 注册测试（审查结论14/15；V2.1 §10.3）。

覆盖：
- 生产 assign_split 与 tests/test_e0_split.py 金标准逐会话对齐；
- canonical connection_time 解析：matched→api_metadata / 缺失→fallback /
  矛盾→仅登记 anomaly 禁止自动替换（审查结论9 强制） / static_only→first_observation_fallback；
- session_id 派生（static_only 与 matched 格式一致）与 api_only 排除；
- field_mode 五类、role 四值、stress/external 标记；
- 验收不变量：session_id 唯一、单 split、sample_layer↔match_status 一致、五值枚举。
本测试只使用合成小样本，不依赖全量数据与 paths.yaml。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from patent_preexperiment.e0_full.split import (
    _FIELD_MODE_CATEGORIES,
    assign_split,
    build_field_mode_registry,
    build_split_registry,
    classify_field_mode,
    resolve_role,
)

PP = Path(__file__).resolve().parents[1]


def _load_golden():
    p = PP / "tests" / "test_e0_split.py"
    spec = importlib.util.spec_from_file_location("golden_e0_split", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.assign_split


def _cfg() -> dict:
    return {
        "inputs": {
            "manifests": {
                "static_file_index_rows": 4,
                "match_status": {"matched": 2, "static_only": 2, "api_only": 1},
            },
        },
        "site_mapping": {
            "raw_to_canonical": {"caltech": "caltech", "jpl": "jpl", "office_01": "office001"},
        },
        "split": {"external_only": ["office001"], "rule_version": "e0_full_split_v1"},
        "anomaly_months": ["2019-12", "2020-02", "2020-04", "2020-12"],
        "anomaly_year_2021": True,
        "k1_role_months": {"jpl_boundary_window": ["2020-06", "2020-07"]},
    }


def _synth_sessions(n: int, site: str = "caltech", n_sites: int = 1) -> pd.DataFrame:
    start = pd.Timestamp("2018-11-01 08:00:00")
    times = [start + pd.Timedelta(minutes=10 * i) for i in range(n)]
    sites = [f"site_{i % n_sites}" for i in range(n)]
    return pd.DataFrame(
        {
            "session_id": [f"s{i:04d}" for i in range(n)],
            "site": sites,
            "connection_time": times,
            "is_external": False,
            "is_stress": False,
        }
    )


def _manifest_df(
    files: list[tuple[str, str, bool, bool, bool, bool]],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "logical_path": [f[0] for f in files],
            "time_min": [f[1] for f in files],
            "has_power": [f[2] for f in files],
            "has_voltage": [f[3] for f in files],
            "has_current": [f[4] for f in files],
            "has_pilot": [f[5] for f in files],
        }
    )


def _mapping_df(rows: list[dict]) -> pd.DataFrame:
    cols = [
        "sessionID", "site_static", "garage", "stationID", "connection_time",
        "static_file", "match_status",
    ]
    return pd.DataFrame(rows, columns=cols)


def _audit_df(rows: list[dict]) -> pd.DataFrame:
    cols = [
        "session_id", "first_observation_utc", "api_connection_time_raw",
        "api_connection_time_utc", "connection_time_source", "anomaly_reason",
    ]
    return pd.DataFrame(rows, columns=cols)


# ---- 金标准对齐 ----


@pytest.mark.parametrize("n_sites", [1, 2, 3])
@pytest.mark.parametrize("n", [1, 50, 3000])
def test_production_assign_split_matches_golden(n: int, n_sites: int) -> None:
    golden = _load_golden()
    df = _synth_sessions(n, n_sites=n_sites)
    if n > 2:
        df.loc[[0, 1], "is_external"] = True
        df.loc[[2, 3], "is_stress"] = True
    a = assign_split(df)
    b = golden(df)
    pd.testing.assert_series_equal(a["split"], b["split"])


def test_production_assign_split_ties_match_golden() -> None:
    golden = _load_golden()
    t = pd.Timestamp("2019-03-01 10:00:00")
    df = pd.DataFrame(
        {
            "session_id": [f"s{i:04d}" for i in range(80)],
            "site": ["caltech"] * 80,
            "connection_time": [t] * 80,
            "is_external": False,
            "is_stress": False,
        }
    )
    for seed in (3, 11, 19):
        shuffled = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
        a = assign_split(shuffled).set_index("session_id")["split"]
        b = golden(shuffled).set_index("session_id")["split"]
        pd.testing.assert_series_equal(a.sort_index(), b.sort_index())


def test_production_assign_split_rejects_minute_level() -> None:
    df = _synth_sessions(50)
    dup = pd.concat([df, df], ignore_index=True)
    with pytest.raises(ValueError, match="会话级"):
        assign_split(dup)


def test_production_assign_split_deterministic() -> None:
    df = _synth_sessions(1000, n_sites=2)
    pd.testing.assert_series_equal(assign_split(df)["split"], assign_split(df)["split"])


# ---- field_mode 五类 ----


def test_classify_field_mode_five_categories() -> None:
    assert classify_field_mode(True, True, True, True) == "measured_pilot"
    assert classify_field_mode(True, True, True, False) == "measured_no_pilot"
    assert classify_field_mode(False, True, True, True) == "computed_pilot"
    assert classify_field_mode(False, True, True, False) == "computed_no_pilot"
    assert classify_field_mode(False, False, True, False) == "current_only"
    assert len(_FIELD_MODE_CATEGORIES) == 5


# ---- role 四值 ----


def test_resolve_role_four_values() -> None:
    rm = {"jpl_boundary_window": ["2020-06", "2020-07"]}
    assert resolve_role("caltech", "California_Garage_01", "2019-03", rm) == "main"
    assert resolve_role("office001", "Parking_Lot_01", "2019-03", rm) == "external_only"
    assert resolve_role("jpl", "Arroyo_Garage_01", "2020-06", rm) == "boundary"
    assert resolve_role("jpl", "Arroyo_Garage_01", "2020-07", rm) == "boundary"
    assert resolve_role("jpl", "Arroyo_Garage_01", "2020-08", rm) == "current_only_fallback"
    assert resolve_role("jpl", "LIGO_01", "2020-06", rm) == "current_only_fallback"


# ---- registry 组装（合成小样本） ----


def _synthetic_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mapping = _mapping_df(
        [
            {
                "sessionID": "2_39_123_23_2018-11-01 04:23:16.156007",
                "site_static": "caltech",
                "garage": "California_Garage_01",
                "stationID": "2-39-123-23",
                "connection_time": "2018-11-01T04:23:16.156007",
                "static_file": (
                    "caltech/California_Garage_01/"
                    "2-39-123-23-2018-11-01T04-23-16-156007.csv.gz"
                ),
                "match_status": "matched",
            },
            {
                "sessionID": None,
                "site_static": "jpl",
                "garage": "Arroyo_Garage_01",
                "stationID": "3-52-101-5",
                "connection_time": "2020-06-05T10:00:00.000000",
                "static_file": "jpl/Arroyo_Garage_01/3-52-101-5-2020-06-05T10-00-00-000000.csv.gz",
                "match_status": "static_only",
            },
            {
                "sessionID": "9_1_1_2019-12-01 00:00:00.000000",
                "site_static": "office_01",
                "garage": "Parking_Lot_01",
                "stationID": "9-1-1",
                "connection_time": "2019-12-01T00:00:00.000000",
                "static_file": "office_01/Parking_Lot_01/9-1-1-2019-12-01T00-00-00-000000.csv.gz",
                "match_status": "matched",
            },
            {
                "sessionID": None,
                "site_static": "caltech",
                "garage": "California_Garage_01",
                "stationID": "2-39-123-24",
                "connection_time": "2019-12-15T08:00:00.000000",
                "static_file": (
                    "caltech/California_Garage_01/"
                    "2-39-123-24-2019-12-15T08-00-00-000000.csv.gz"
                ),
                "match_status": "static_only",
            },
            {
                "sessionID": "api_only_s1",
                "site_static": None,
                "garage": None,
                "stationID": None,
                "connection_time": None,
                "static_file": None,
                "match_status": "api_only",
            },
        ]
    )
    audit = _audit_df(
        [
            {
                "session_id": "2_39_123_23_2018-11-01 04:23:16.156007",
                "first_observation_utc": "2018-11-01T04:23:16+00:00",
                "api_connection_time_raw": "2018-11-01T04:23:16+00:00",
                "api_connection_time_utc": "2018-11-01T04:23:16+00:00",
                "connection_time_source": "api_metadata",
                "anomaly_reason": None,
            },
            {
                "session_id": "9_1_1_2019-12-01 00:00:00.000000",
                "first_observation_utc": "2019-12-01T00:00:00+00:00",
                "api_connection_time_raw": "2019-12-01T00:00:00+00:00",
                "api_connection_time_utc": "2019-12-01T00:00:00+00:00",
                "connection_time_source": "api_metadata",
                "anomaly_reason": None,
            },
        ]
    )
    api_meta = pd.DataFrame(
        {
            "sessionID": [
                "2_39_123_23_2018-11-01 04:23:16.156007",
                "9_1_1_2019-12-01 00:00:00.000000",
            ],
            "disconnectTime": [
                "2018-11-01T08:23:00+00:00",
                "2019-12-01T04:00:00+00:00",
            ],
        }
    )
    manifest = _manifest_df(
        [
            (
                "caltech/California_Garage_01/2-39-123-23-2018-11-01T04-23-16-156007.csv.gz",
                "2018-11-01T04:23:16+00:00",
                True,
                True,
                True,
                True,
            ),
            (
                "jpl/Arroyo_Garage_01/3-52-101-5-2020-06-05T10-00-00-000000.csv.gz",
                "2020-06-05T10:00:02+00:00",
                False,
                False,
                True,
                False,
            ),
            (
                "office_01/Parking_Lot_01/9-1-1-2019-12-01T00-00-00-000000.csv.gz",
                "2019-12-01T00:00:01+00:00",
                True,
                True,
                True,
                False,
            ),
            (
                "caltech/California_Garage_01/2-39-123-24-2019-12-15T08-00-00-000000.csv.gz",
                "2019-12-15T08:00:03+00:00",
                True,
                True,
                True,
                True,
            ),
        ]
    )
    return mapping, audit, api_meta, manifest


def test_registry_matched_api_metadata() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    reg = build_split_registry(mapping, audit, api_meta, manifest, _cfg())
    row = reg[reg["match_status"] == "matched"].iloc[0]
    assert row["connection_time_source"] == "api_metadata"
    assert row["connection_time"] == pd.Timestamp("2018-11-01T04:23:16+00:00")
    assert row["disconnect_time"] == pd.Timestamp("2018-11-01T08:23:00+00:00")
    assert row["sample_layer"] == "L1_strict_matched"
    assert row["role"] == "main"
    assert row["field_mode"] == "measured_pilot"
    assert not row["anomaly_flag"]
    assert row["session_id"] == "2_39_123_23_2018-11-01 04:23:16.156007"


def test_registry_static_only_fallback() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    reg = build_split_registry(mapping, audit, api_meta, manifest, _cfg())
    row = reg[reg["session_id"] == "3_52_101_5_2020-06-05 10:00:00.000000"].iloc[0]
    assert row["connection_time_source"] == "first_observation_fallback"
    assert row["connection_time"] == pd.Timestamp("2020-06-05T10:00:02+00:00")
    assert pd.isna(row["disconnect_time"])
    assert row["sample_layer"] == "L0_static_extension"
    assert row["role"] == "boundary"
    assert row["field_mode"] == "current_only"
    assert row["session_id"] == "3_52_101_5_2020-06-05 10:00:00.000000"


def test_registry_office_external_and_stress() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    reg = build_split_registry(mapping, audit, api_meta, manifest, _cfg())
    by_sid = reg.set_index("session_id")
    office = by_sid.loc["9_1_1_2019-12-01 00:00:00.000000"]
    assert office["external"]
    assert office["split"] == "external"
    assert office["role"] == "external_only"
    # office 会话（2019-12 异常月）不因 stress 被降级为训练
    assert office["stress"]
    cal = by_sid.loc["2_39_123_24_2019-12-15 08:00:00.000000"]
    assert cal["stress"]
    assert cal["split"] == "stress"
    assert cal["role"] == "main"


def test_registry_excludes_api_only() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    reg = build_split_registry(mapping, audit, api_meta, manifest, _cfg())
    assert len(reg) == 4
    assert "api_only_s1" not in set(reg["session_id"])
    assert (reg["match_status"].isin(["matched", "static_only"])).all()


def test_registry_session_id_unique_and_single_split() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    reg = build_split_registry(mapping, audit, api_meta, manifest, _cfg())
    assert reg["session_id"].is_unique
    assert reg.groupby("session_id")["split"].nunique().eq(1).all()
    assert set(reg["split"]) <= {"train", "validation", "test", "external", "stress"}
    assert reg.groupby("session_id").size().eq(1).all()


def test_registry_sample_layer_consistent_with_match_status() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    reg = build_split_registry(mapping, audit, api_meta, manifest, _cfg())
    assert (
        ((reg["sample_layer"] == "L1_strict_matched") & (reg["match_status"] == "matched"))
        | ((reg["sample_layer"] == "L0_static_extension") & (reg["match_status"] == "static_only"))
    ).all()


def test_registry_anomaly_registered_no_auto_replace() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    sid = "2_39_123_23_2018-11-01 04:23:16.156007"
    audit.loc[audit["session_id"] == sid, "connection_time_source"] = "anomaly"
    audit.loc[audit["session_id"] == sid, "anomaly_reason"] = "api_ct-first_obs=+60.0min 超容差"
    reg = build_split_registry(mapping, audit, api_meta, manifest, _cfg())
    row = reg[reg["session_id"] == sid].iloc[0]
    # 禁止自动替换：connection_time 保持 API 值，source 仍为 api_metadata
    assert row["connection_time"] == pd.Timestamp("2018-11-01T04:23:16+00:00")
    assert row["connection_time_source"] == "api_metadata"
    assert row["anomaly_flag"]
    assert row["anomaly_reason"] == "api_ct-first_obs=+60.0min 超容差"


def test_registry_matched_missing_api_falls_back() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    sid = "2_39_123_23_2018-11-01 04:23:16.156007"
    audit.loc[audit["session_id"] == sid, "connection_time_source"] = "first_observation_fallback"
    audit.loc[audit["session_id"] == sid, "api_connection_time_utc"] = None
    reg = build_split_registry(mapping, audit, api_meta, manifest, _cfg())
    row = reg[reg["session_id"] == sid].iloc[0]
    assert row["connection_time_source"] == "first_observation_fallback"
    assert row["connection_time"] == pd.Timestamp("2018-11-01T04:23:16+00:00")
    assert not row["anomaly_flag"]


def test_registry_invariant_duplicate_session_raises() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    dup = _mapping_df(
        [
            {
                "sessionID": "2_39_123_23_2018-11-01 04:23:16.156007",
                "site_static": "caltech",
                "garage": "California_Garage_01",
                "stationID": "2-39-123-23",
                "connection_time": "2018-11-01T04:23:16.156007",
                "static_file": (
                    "caltech/California_Garage_01/"
                    "2-39-123-23-2018-11-01T04-23-16-156007.csv.gz"
                ),
                "match_status": "matched",
            }
        ]
    )
    mapping2 = pd.concat([mapping, dup], ignore_index=True)
    with pytest.raises(ValueError, match="session_id 不得重复"):
        build_split_registry(mapping2, audit, api_meta, manifest, _cfg())


def test_registry_missing_manifest_raises() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    manifest = manifest.iloc[:-1].copy()
    with pytest.raises(ValueError, match="不在 manifest"):
        build_split_registry(mapping, audit, api_meta, manifest, _cfg())


# ---- E0F-02.1 治理收尾（审查结论16） ----


def test_population_freeze_stop_on_row_count() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    cfg = _cfg()
    cfg["inputs"]["manifests"]["static_file_index_rows"] = 5
    with pytest.raises(ValueError, match="人口冻结"):
        build_split_registry(mapping, audit, api_meta, manifest, cfg)


def test_population_freeze_stop_on_matched_count() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    cfg = _cfg()
    cfg["inputs"]["manifests"]["match_status"]["matched"] = 3
    with pytest.raises(ValueError, match="人口冻结"):
        build_split_registry(mapping, audit, api_meta, manifest, cfg)


def test_population_freeze_stop_on_static_only_count() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    cfg = _cfg()
    cfg["inputs"]["manifests"]["match_status"]["static_only"] = 1
    with pytest.raises(ValueError, match="人口冻结"):
        build_split_registry(mapping, audit, api_meta, manifest, cfg)


def test_audit_duplicate_session_id_fails_fast() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    audit2 = pd.concat([audit, audit.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="connection_time_audit.*唯一"):
        build_split_registry(mapping, audit2, api_meta, manifest, _cfg())


def test_api_meta_duplicate_session_id_fails_fast() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    api2 = pd.concat([api_meta, api_meta.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="api_metadata_index.*唯一"):
        build_split_registry(mapping, audit, api2, manifest, _cfg())


def test_manifest_duplicate_logical_path_fails_fast() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    manifest2 = pd.concat([manifest, manifest.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="source_manifest.*唯一"):
        build_split_registry(mapping, audit, api_meta, manifest2, _cfg())


def test_field_mode_registry_manifest_duplicate_fails_fast() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    manifest2 = pd.concat([manifest, manifest.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="source_manifest.*唯一"):
        build_field_mode_registry(mapping, manifest2, _cfg())


def test_cross_registry_session_set_mismatch_raises() -> None:
    from patent_preexperiment.e0_full.split import _assert_cross_registry_consistency

    mapping, audit, api_meta, manifest = _synthetic_inputs()
    reg = build_split_registry(mapping, audit, api_meta, manifest, _cfg())
    fm = build_field_mode_registry(mapping, manifest, _cfg())
    extra = fm.iloc[[0]].copy()
    extra["session_id"] = "extra_session_x"
    fm2 = pd.concat([fm, extra], ignore_index=True)
    with pytest.raises(ValueError, match="会话集合必须完全一致"):
        _assert_cross_registry_consistency(reg, fm2)


def test_cross_registry_session_set_consistent_ok() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    reg = build_split_registry(mapping, audit, api_meta, manifest, _cfg())
    fm = build_field_mode_registry(mapping, manifest, _cfg())
    assert set(fm["session_id"]) == set(reg["session_id"])


def test_field_mode_registry_matches_split_registry() -> None:
    mapping, audit, api_meta, manifest = _synthetic_inputs()
    reg = build_split_registry(mapping, audit, api_meta, manifest, _cfg())
    fm = build_field_mode_registry(mapping, manifest, _cfg())
    assert set(fm["session_id"]) == set(reg["session_id"])
    assert fm["session_id"].is_unique
    merged = fm.merge(
        reg[["session_id", "field_mode", "sample_layer"]],
        on="session_id", suffixes=("_fm", "_reg"),
    )
    assert (merged["field_mode_fm"] == merged["field_mode_reg"]).all()
    assert (merged["sample_layer_fm"] == merged["sample_layer_reg"]).all()
    for col in ("has_power", "has_voltage", "has_current", "has_pilot"):
        assert col in fm.columns
