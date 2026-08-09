"""E3-Full loader 测试（R1 / 审查结论28）：双轨人口、field_mode 过滤、交叉验证。

覆盖：
- population_sessions：E3-M（main）/ E3-X（current_only_fallback ∧ current_only）过滤；
  特别验证同 role 内 measured_pilot 不被误纳入 current-only 池（205 个须排除）；
- load_evidence_minutes：合成分区 + 谓词下推 + registry 交叉验证（missing/extra 拒绝）；
- minutes_from_end / cycle_month 派生；
- split_minutes 会话级隔离；
- 真实 registry（若存在）：E3-M=13,477（9426/3896/155）、E3-X=23,471（13908/5026/1991）。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from patent_preexperiment.e3_full.loader import (
    FALLBACK_FIELD_MODE,
    FALLBACK_ROLE,
    MAIN_LAYER,
    MAIN_ROLE,
    MAIN_SPLITS,
    load_caltech_main,
    load_jpl_current_only,
    population_sessions,
    split_minutes,
)

PP = Path(__file__).resolve().parents[1]


def _minute_row(
    sid: str, site: str, garage: str, split: str, role: str, field_mode: str,
    ts: pd.Timestamp, disconnect: pd.Timestamp | None,
) -> dict:
    return {
        "session_id": sid, "station_id": f"st_{sid}", "site": site, "garage": garage,
        "split": split, "role": role, "sample_layer": MAIN_LAYER,
        "field_mode": field_mode, "match_status": "matched",
        "timestamp_utc": ts, "disconnect_time": disconnect,
        "actual_power_kw": 3.0, "pilot_power_kw": 6.0,
    }


def _base_registry() -> pd.DataFrame:
    t = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    rows = []
    for split in MAIN_SPLITS:
        rows.append({
            "session_id": f"cal_{split}_s1", "site": "caltech",
            "garage": "California_Garage_01", "sample_layer": MAIN_LAYER,
            "role": MAIN_ROLE, "split": split, "connection_time": t,
            "match_status": "matched", "field_mode": "measured_pilot",
        })
    for split in MAIN_SPLITS:
        rows.append({
            "session_id": f"jpl_co_{split}_s1", "site": "jpl",
            "garage": "Arroyo_Garage_01", "sample_layer": MAIN_LAYER,
            "role": FALLBACK_ROLE, "split": split, "connection_time": t,
            "match_status": "matched", "field_mode": FALLBACK_FIELD_MODE,
        })
    # 同 role 内的 measured_pilot 会话（必须被 current-only 过滤排除）
    rows.append({
        "session_id": "jpl_pilot_s1", "site": "jpl",
        "garage": "Arroyo_Garage_01", "sample_layer": MAIN_LAYER,
        "role": FALLBACK_ROLE, "split": "train", "connection_time": t,
        "match_status": "matched", "field_mode": "measured_pilot",
    })
    # stress split（必须被 MAIN_SPLITS 排除）
    rows.append({
        "session_id": "jpl_co_stress", "site": "jpl",
        "garage": "Arroyo_Garage_01", "sample_layer": MAIN_LAYER,
        "role": FALLBACK_ROLE, "split": "stress", "connection_time": t,
        "match_status": "matched", "field_mode": FALLBACK_FIELD_MODE,
    })
    return pd.DataFrame(rows)


def _universe_minutes() -> pd.DataFrame:
    t = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    disc = pd.Timestamp("2018-11-01 09:00:00", tz="UTC")
    rows = []
    for split in MAIN_SPLITS:
        rows.append(_minute_row(f"cal_{split}_s1", "caltech", "California_Garage_01",
                                split, MAIN_ROLE, "measured_pilot", t, disc))
        rows.append(_minute_row(f"jpl_co_{split}_s1", "jpl", "Arroyo_Garage_01",
                                split, FALLBACK_ROLE, FALLBACK_FIELD_MODE, t, disc))
    return pd.DataFrame(rows)


def _write_flat_parquet(tmp_path: Path, df: pd.DataFrame) -> Path:
    root = tmp_path / "session_response_1min"
    root.mkdir(parents=True, exist_ok=True)
    df.to_parquet(root / "synth.parquet", index=False)
    return root


def test_population_caltech_main() -> None:
    reg = _base_registry()
    univ = population_sessions(reg, role=MAIN_ROLE)
    assert set(univ["session_id"]) == {"cal_train_s1", "cal_validation_s1", "cal_test_s1"}
    assert (univ["role"] == MAIN_ROLE).all()


def test_population_jpl_current_only_excludes_measured_pilot() -> None:
    """同 role 内 205 个 measured_pilot 不得进 current-only 池（审查结论28 关键约束）。"""
    reg = _base_registry()
    univ = population_sessions(reg, role=FALLBACK_ROLE, field_mode=FALLBACK_FIELD_MODE)
    assert set(univ["session_id"]) == {"jpl_co_train_s1", "jpl_co_validation_s1", "jpl_co_test_s1"}
    assert "jpl_pilot_s1" not in set(univ["session_id"])
    assert (univ["field_mode"] == FALLBACK_FIELD_MODE).all()


def test_population_excludes_stress_split() -> None:
    reg = _base_registry()
    univ = population_sessions(reg, role=FALLBACK_ROLE, field_mode=FALLBACK_FIELD_MODE)
    assert "stress" not in set(univ["split"])


def test_population_duplicate_raises() -> None:
    reg = _base_registry()
    dup = pd.concat([reg, reg.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="唯一"):
        population_sessions(dup, role=MAIN_ROLE)


def test_load_caltech_main_derives_end_and_month(tmp_path: Path) -> None:
    df = _universe_minutes()
    root = _write_flat_parquet(tmp_path, df)
    out = load_caltech_main(root, _base_registry())
    assert set(out["session_id"]) == {"cal_train_s1", "cal_validation_s1", "cal_test_s1"}
    assert out["minutes_from_end"].iloc[0] == pytest.approx(60.0)
    assert (out["cycle_month"] == "2018-11").all()


def test_load_jpl_current_only_only_current_only_sessions(tmp_path: Path) -> None:
    df = _universe_minutes()
    root = _write_flat_parquet(tmp_path, df)
    # registry 含 jpl_pilot_s1（同 role measured_pilot），分钟表不含它 → extra 检查只针对人口子集
    out = load_jpl_current_only(root, _base_registry())
    assert set(out["session_id"]) == {"jpl_co_train_s1", "jpl_co_validation_s1", "jpl_co_test_s1"}
    assert (out["field_mode"] == FALLBACK_FIELD_MODE).all()


def test_load_rejects_missing_session(tmp_path: Path) -> None:
    df = _universe_minutes()
    root = _write_flat_parquet(tmp_path, df)
    reg = _base_registry()
    reg = pd.concat([reg, pd.DataFrame([{
        "session_id": "cal_train_ghost", "site": "caltech",
        "garage": "California_Garage_01", "sample_layer": MAIN_LAYER,
        "role": MAIN_ROLE, "split": "train",
        "connection_time": pd.Timestamp("2018-11-01", tz="UTC"),
        "match_status": "matched", "field_mode": "measured_pilot",
    }])], ignore_index=True)
    with pytest.raises(ValueError, match="missing=1"):
        load_caltech_main(root, reg)


def test_load_rejects_extra_session(tmp_path: Path) -> None:
    t = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    extra = pd.DataFrame([_minute_row("cal_train_extra", "caltech", "California_Garage_01",
                                      "train", MAIN_ROLE, "measured_pilot", t, None)])
    df = pd.concat([_universe_minutes(), extra], ignore_index=True)
    root = _write_flat_parquet(tmp_path, df)
    with pytest.raises(ValueError, match="extra=1"):
        load_caltech_main(root, _base_registry())


def test_split_minutes_session_level_isolation() -> None:
    t = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    df = pd.DataFrame([
        _minute_row("cal_train_s1", "caltech", "CG1", "train",
                    MAIN_ROLE, "measured_pilot", t, None),
        _minute_row("cal_test_s1", "caltech", "CG1", "test",
                    MAIN_ROLE, "measured_pilot", t, None),
    ])
    tr = split_minutes(df, "train")
    assert set(tr["session_id"]) == {"cal_train_s1"}


def test_split_minutes_empty_raises() -> None:
    t = pd.Timestamp("2018-11-01 08:00:00", tz="UTC")
    df = pd.DataFrame([_minute_row("cal_train_s1", "caltech", "CG1", "train",
                                   MAIN_ROLE, "measured_pilot", t, None)])
    with pytest.raises(ValueError, match="无分钟数据"):
        split_minutes(df, "test")


# ---- 真实 registry 人口审计 ----


def _real_registry() -> pd.DataFrame | None:
    p = PP / "data_registry" / "e0_full_split_registry.parquet"
    return pd.read_parquet(p) if p.exists() else None


def test_real_registry_caltech_main_population() -> None:
    reg = _real_registry()
    if reg is None:
        pytest.skip("data_registry/e0_full_split_registry.parquet 不存在")
    univ = population_sessions(reg, role=MAIN_ROLE)
    assert len(univ) == 13_477
    counts = univ.groupby("split")["session_id"].size().to_dict()
    assert counts == {"train": 9_426, "validation": 3_896, "test": 155}


def test_real_registry_jpl_current_only_population() -> None:
    reg = _real_registry()
    if reg is None:
        pytest.skip("data_registry/e0_full_split_registry.parquet 不存在")
    univ = population_sessions(reg, role=FALLBACK_ROLE, field_mode=FALLBACK_FIELD_MODE)
    assert len(univ) == 20_925  # 主切分（排除 stress 2,546）
    counts = univ.groupby("split")["session_id"].size().to_dict()
    assert counts == {"train": 13_908, "validation": 5_026, "test": 1_991}


def test_real_registry_jpl_role_has_measured_pilot_subset() -> None:
    """审查结论28：current_only_fallback role 含 163 个 measured_pilot（全在 test），
    须靠 field_mode==current_only 排除（另 42 个在 stress，不进主切分）。"""
    reg = _real_registry()
    if reg is None:
        pytest.skip("data_registry/e0_full_split_registry.parquet 不存在")
    role_all = population_sessions(reg, role=FALLBACK_ROLE, field_mode=None)
    assert (role_all["field_mode"] == "measured_pilot").sum() == 163
    co_only = population_sessions(reg, role=FALLBACK_ROLE, field_mode=FALLBACK_FIELD_MODE)
    assert (co_only["field_mode"] == "measured_pilot").sum() == 0
