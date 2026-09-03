"""E1-Full loader 测试（R1 / E0F-06）：主证据体系人口、split 隔离、派生列。

覆盖：
- main_evidence_universe：L1_strict_matched ∧ role==main ∧ split∈{train,validation,test}
  （合成 registry，测试过滤逻辑与 session_id 唯一性）；
- load_main_evidence_minutes：合成分区 + 谓词下推 + registry 交叉验证（missing/extra 拒绝）；
- minutes_from_end 派生（disconnect_time - timestamp_utc）/60 与 cycle_month；
- split_df 会话级隔离（不允许分钟级切分）；
- 真实 registry（若存在）：人口=13,477、train/validation/test=9426/3896/155、
  test 无 K1 冻结月份会话（R1 人口变化的关键事实）。
本测试的合成部分不依赖全量数据与 paths.yaml。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from patent_preexperiment.e1_full.loader import (
    MAIN_LAYER,
    MAIN_ROLE,
    MAIN_SPLITS,
    load_main_evidence_minutes,
    main_evidence_universe,
    split_df,
)

PP = Path(__file__).resolve().parents[1]


def _registry(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _minute_row(
    sid: str, split: str, ts: pd.Timestamp, disconnect: pd.Timestamp | None,
) -> dict:
    return {
        "session_id": sid,
        "station_id": f"st_{sid}",
        "site": "caltech",
        "garage": "CG1",
        "split": split,
        "role": MAIN_ROLE,
        "sample_layer": MAIN_LAYER,
        "field_mode": "measured_pilot",
        "match_status": "matched",
        "timestamp_utc": ts,
        "disconnect_time": disconnect,
        "done_charging_time": pd.Timestamp("2018-11-01 12:00:00", tz="UTC"),
        "connected_elapsed_min": 30.0,
        "current_a": 20.0,
        "actual_power_kw": 2.0,
        "pilot_power_kw": 4.0,
        "pilot_a": 16.0,
        "pilot_available": True,
        "power_source": "measured",
        "gap_flag": False,
        "minutes_from_end": 60.0,
    }


def _base_registry() -> pd.DataFrame:
    t = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    rows = []
    for split in MAIN_SPLITS:
        rows.append(_registry([{
            "session_id": f"{split}_s1", "site": "caltech", "garage": "CG1",
            "sample_layer": MAIN_LAYER, "role": MAIN_ROLE, "split": split,
            "connection_time": t, "match_status": "matched", "field_mode": "measured_pilot",
        }]))
    rows.append(_registry([{
        "session_id": "l0_static", "site": "caltech", "garage": "CG1",
        "sample_layer": "L0_static_extension", "role": "main", "split": "train",
        "connection_time": t, "match_status": "static_only", "field_mode": "measured_pilot",
    }]))
    rows.append(_registry([{
        "session_id": "stress_s", "site": "caltech", "garage": "CG1",
        "sample_layer": MAIN_LAYER, "role": "main", "split": "stress",
        "connection_time": t, "match_status": "matched", "field_mode": "measured_pilot",
    }]))
    rows.append(_registry([{
        "session_id": "boundary_jpl", "site": "jpl", "garage": "Arroyo_Garage_01",
        "sample_layer": MAIN_LAYER, "role": "boundary", "split": "train",
        "connection_time": t, "match_status": "matched", "field_mode": "current_only",
    }]))
    return pd.concat(rows, ignore_index=True)


def _universe_minutes() -> pd.DataFrame:
    """三个主集会话（train/validation/test 各一）的分钟数据。"""
    t = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    disc = pd.Timestamp("2018-11-01 09:30:00", tz="UTC")
    return pd.DataFrame([
        _minute_row("train_s1", "train", t, disc),
        _minute_row("validation_s1", "validation", t, disc),
        _minute_row("test_s1", "test", t, disc),
    ])


def _write_synth_minutes(tmp_path: Path, df: pd.DataFrame) -> Path:
    root = tmp_path / "session_response_1min"
    for split in df["split"].unique():
        sub = df[df["split"] == split]
        p = root / f"site=caltech/year=2018/month=11/split={split}/data.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        sub.to_parquet(p, index=False)
    return root


def test_main_evidence_universe_filter() -> None:
    reg = _base_registry()
    univ = main_evidence_universe(reg)
    assert set(univ["session_id"]) == {"train_s1", "validation_s1", "test_s1"}
    assert (univ["split"].isin(MAIN_SPLITS)).all()


def test_main_evidence_universe_duplicate_raises() -> None:
    reg = _base_registry()
    dup = pd.concat([reg, reg.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="唯一"):
        main_evidence_universe(dup)


def test_load_minutes_derives_end_and_month(tmp_path: Path) -> None:
    df = _universe_minutes()
    root = _write_synth_minutes(tmp_path, df)
    reg = _base_registry()

    out = load_main_evidence_minutes(root, reg)
    assert set(out["session_id"]) == {"train_s1", "validation_s1", "test_s1"}
    assert out["minutes_from_end"].iloc[0] == pytest.approx(90.0)
    assert (out["cycle_month"] == "2018-11").all()
    assert out["disconnect_time"].notna().all()


def test_load_minutes_rejects_session_mismatch(tmp_path: Path) -> None:
    df = _universe_minutes()
    root = _write_synth_minutes(tmp_path, df)
    reg = _base_registry()
    t = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    reg = pd.concat([reg, pd.DataFrame([{
        "session_id": "train_s9", "site": "caltech", "garage": "CG1",
        "sample_layer": MAIN_LAYER, "role": MAIN_ROLE, "split": "train",
        "connection_time": t, "match_status": "matched", "field_mode": "measured_pilot",
    }])], ignore_index=True)
    with pytest.raises(ValueError, match="missing=1"):
        load_main_evidence_minutes(root, reg)


def test_load_minutes_extra_session_rejected(tmp_path: Path) -> None:
    df = _universe_minutes()
    t = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    extra = pd.DataFrame([_minute_row("extra_s", "train", t, None)])
    df = pd.concat([df, extra], ignore_index=True)
    root = _write_synth_minutes(tmp_path, df)
    with pytest.raises(ValueError, match="extra=1"):
        load_main_evidence_minutes(root, _base_registry())


def test_split_df_session_level_isolation() -> None:
    t = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    df = pd.DataFrame([
        _minute_row("train_s1", "train", t, None),
        _minute_row("validation_s1", "validation", t, None),
    ])
    tr = split_df(df, "train")
    assert set(tr["session_id"]) == {"train_s1"}
    assert (tr["split"] == "train").all()


def test_split_df_empty_raises() -> None:
    t = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    df = pd.DataFrame([_minute_row("train_s1", "train", t, None)])
    with pytest.raises(ValueError, match="无分钟数据"):
        split_df(df, "test")


# ---- 真实 registry 人口审计（仓库内产物，非全量数据；缺失则跳过） ----


def _real_registry() -> pd.DataFrame | None:
    p = PP / "data_registry" / "e0_full_split_registry.parquet"
    return pd.read_parquet(p) if p.exists() else None


def test_real_registry_main_evidence_universe_population() -> None:
    reg = _real_registry()
    if reg is None:
        pytest.skip("data_registry/e0_full_split_registry.parquet 不存在")
    univ = main_evidence_universe(reg)
    assert len(univ) == 13_477
    counts = univ.groupby("split")["session_id"].size().to_dict()
    assert counts == {"train": 9_426, "validation": 3_896, "test": 155}


def test_real_registry_test_split_has_no_k1_frozen_months() -> None:
    """R1 人口变化关键事实：test 只有 2020 下半年，无 K1 冻结月份会话。"""
    reg = _real_registry()
    if reg is None:
        pytest.skip("data_registry/e0_full_split_registry.parquet 不存在")
    univ = main_evidence_universe(reg)
    test = univ[univ["split"] == "test"]
    months = test["connection_time"].astype(str).str[:7]
    assert set(months) == {"2020-05", "2020-06", "2020-07", "2020-08", "2020-11"}
    assert not set(months) & {"2018-11", "2019-03", "2019-04", "2019-05", "2019-08", "2019-10"}


def test_real_registry_test_field_modes() -> None:
    reg = _real_registry()
    if reg is None:
        pytest.skip("data_registry/e0_full_split_registry.parquet 不存在")
    univ = main_evidence_universe(reg)
    test = univ[univ["split"] == "test"]
    fm = test["field_mode"].value_counts().to_dict()
    assert fm.get("measured_pilot", 0) == 154
    assert fm.get("current_only", 0) == 1
