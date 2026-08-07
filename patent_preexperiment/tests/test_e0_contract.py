"""E0-Full 数据契约冻结测试（审查结论7 §4.3/§4.4/§6.2/§7）。

校验：e0_full.yaml 预注册配置的结构与冻结值、两个 JSON schema 的必要字段、
claim_evidence_registry.csv 的证据台账规范、在线字段不得命中禁止特征。
本测试不依赖全量数据，属 S0 阶段启动冻结的测试框架。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

PP = Path(__file__).resolve().parents[1]          # patent_preexperiment/
REPO = Path(__file__).resolve().parents[2]         # 仓库根
CONFIGS = PP / "configs"
DATA_REGISTRY = PP / "data_registry"

# 审查结论7 §7.1 在线安全字段（E0-Full 在线 schema 允许集，冻结）
ONLINE_FIELDS = [
    "site", "garage", "station", "session_id", "timestamp_utc",
    "charging_current", "actual_power_kw", "pilot", "charging_state",
    "connected_elapsed_min", "rolling_stats_history_only", "power_source",
    "field_mode", "gap_flag",
]

EXPECTED_FIELD_MODES = {
    "measured_pilot", "measured_no_pilot",
    "computed_pilot", "computed_no_pilot", "current_only",
}

EXPECTED_MANIFESTS = {
    "static_file_index_rows": 85877,
    "api_metadata_index_rows": 51234,
    "static_api_mapping_rows": 96467,
}
EXPECTED_MATCH_STATUS = {"matched": 40644, "static_only": 45233, "api_only": 10590}


def _load_config() -> dict:
    with open(CONFIGS / "e0_full.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_k1_config() -> dict:
    with open(CONFIGS / "k1_preregister.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_e0_config_required_sections() -> None:
    cfg = _load_config()
    for key in (
        "experiment_id", "protocol_version", "landing_version", "rule_version",
        "inputs", "power", "time", "session_join", "duplicates", "gaps",
        "short_files", "anomaly_months", "field_modes", "split", "roles",
        "site_mapping", "k1_role_months",
        "acceptance", "k1_replication_stop_lines", "seeds", "evaluable",
        "outputs", "stop_lines", "forbidden_in_code",
    ):
        assert key in cfg, f"e0_full.yaml 缺少必需节 {key}"
    assert cfg["experiment_id"] == "E0_full_preregister_v1"


def test_e0_split_rule_frozen() -> None:
    cfg = _load_config()
    split = cfg["split"]
    assert split["unit"] == "session"
    assert split["rule_version"] == "e0_full_split_v1"
    assert "60%" in split["rule"] and "20%" in split["rule"]
    for forbidden in ("minutes_level_split", "event_month_selection", "event_rate_boundary_adjust"):
        assert forbidden in split["forbidden"]
    assert split["external_only"] == ["office001"]
    assert "anomaly_months" in split["stress_roles"]
    assert split["field_mode_separate"] is True


def test_e0_connection_time_source_frozen() -> None:
    # 审查结论8 P1-4：时间切分唯一依据必须冻结为 canonical connection_time
    cfg = _load_config()
    ct = cfg["session_join"]["connection_time"]
    assert ct["canonical"]
    assert "API" in ct["canonical"] and "connectionTime" in ct["canonical"]
    assert "first_observation_fallback" in ct["matched_fallback"]
    assert "first_observation_fallback" in ct["static_only"]
    assert ct["source_values"] == ["api_metadata", "first_observation_fallback"]
    schema = json.loads(
        (DATA_REGISTRY / "e0_full_split_registry.schema.json").read_text(encoding="utf-8")
    )
    assert "connection_time_source" in schema["columns"]
    assert schema["column_definitions"]["connection_time_source"]["dtype"] == "string"


def test_e0_connection_time_audit_rule_frozen() -> None:
    # 审查结论9 强制：矛盾样本禁止自动替换，只登记 anomaly
    audit = _load_config()["session_join"]["connection_time"]["audit"]
    assert "矛盾" in audit["rule"] and "anomaly" in audit["rule"]
    assert audit["contradiction_tolerance_ahead_min"] == 5
    assert audit["contradiction_tolerance_behind_h"] == 24


def test_e0_anomaly_months_match_k1() -> None:
    cfg, k1 = _load_config(), _load_k1_config()
    assert cfg["anomaly_months"] == k1["sample"]["exclude_months"]
    assert cfg["anomaly_year_2021"] is True


def test_e0_site_mapping_frozen() -> None:
    # 审查结论10 P1：office_01(raw) → office001(canonical)，external_only 必须用 canonical
    cfg = _load_config()
    sm = cfg["site_mapping"]
    assert sm["raw_to_canonical"] == {"caltech": "caltech", "jpl": "jpl", "office_01": "office001"}
    assert sm["canonical_to_role"]["office001"] == "external_only"
    assert cfg["split"]["external_only"] == ["office001"]
    assert "office_01" not in cfg["split"]["external_only"]
    assert "site_raw" in sm["rule"] and "site_canonical" in sm["rule"]


def test_e0_k1_role_months_match_k1() -> None:
    # 审查结论10 P0-2：重复分类的 K1 role×month 必须与 k1_preregister.yaml 冻结样本一致
    cfg, k1 = _load_config(), _load_k1_config()
    rm = cfg["k1_role_months"]
    assert rm["caltech_main_window"] == k1["sample_roles"]["main_set"]["months"]
    assert rm["jpl_boundary_window"] == k1["sample_roles"]["k1x_boundary"]["months"]
    assert rm["jpl_current_only_window"] == k1["sample_roles"]["current_only_fallback"]["months"]


def test_e0_power_priority_and_rated_voltage() -> None:
    cfg = _load_config()
    assert cfg["power"]["priority"] == ["measured", "computed", "estimated"]
    rated = cfg["power"]["rated_voltage"]
    assert rated == {"jpl": 192.7, "caltech": 240.0, "office001": 240.0}


def test_e0_field_modes_frozen() -> None:
    cfg = _load_config()
    assert set(cfg["field_modes"]["categories"]) == EXPECTED_FIELD_MODES
    assert cfg["field_modes"]["per_file_rule"]


def test_e0_manifest_frozen() -> None:
    cfg = _load_config()
    m = cfg["inputs"]["manifests"]
    assert {k: m[k] for k in EXPECTED_MANIFESTS} == EXPECTED_MANIFESTS
    assert m["match_status"] == EXPECTED_MATCH_STATUS
    assert m["gold_benchmark_stations"] == 115
    assert cfg["inputs"]["read_only"] is True


def test_e0_acceptance_and_stop_lines_present() -> None:
    cfg = _load_config()
    for key in (
        "input_traceability", "output_traceability", "uniqueness", "completeness",
        "energy_consistency", "gold_consistency", "split_safety", "leak_safety",
        "determinism", "evaluable_aggregation",
    ):
        assert key in cfg["acceptance"], f"D0 验收项缺失 {key}"
    assert len(cfg["stop_lines"]["conditions"]) >= 5
    assert "e1" in cfg["k1_replication_stop_lines"] and "e3" in cfg["k1_replication_stop_lines"]


def test_e0_evaluable_aggregation_rule_frozen() -> None:
    cfg = _load_config()
    ev = cfg["evaluable"]
    assert ev["exclude_not_evaluable_from_mean"] is True
    assert ev["zero_not_real_zero"] is True
    assert "insufficient_core_sessions" in ev["reasons"]
    assert ev["report_non_evaluable_separately"] is True


def test_split_schema_required_fields() -> None:
    schema = json.loads(
        (DATA_REGISTRY / "e0_full_split_registry.schema.json").read_text(encoding="utf-8")
    )
    assert schema["$table"] == "e0_full_split_registry"
    assert schema["rule_version"] == "e0_full_split_v1"
    required_cols = {"session_id", "site", "garage", "station", "connection_time",
                     "connection_time_source", "disconnect_time", "split",
                     "split_rule_version", "field_mode", "stress", "external",
                     "source_file"}
    assert required_cols.issubset(schema["columns"])
    assert schema["constraints"]["split_values"] == [
        "train", "validation", "test", "external", "stress"
    ]
    assert schema["constraints"]["session_single_split"] is True
    assert schema["constraints"]["external_not_in_train"] is True
    assert schema["constraints"]["stress_not_in_main"] is True


def test_baseline_schema_required_fields() -> None:
    schema = json.loads(
        (DATA_REGISTRY / "e0_full_baseline.schema.json").read_text(encoding="utf-8")
    )
    for key in (
        "code_sha", "git_status", "e0_full_yaml_sha256", "manifest_hashes", "runtime_versions",
        "input_logical_id", "data_roots_resolved", "split_rule_version",
        "output_manifest", "parent_baseline", "source_manifest_sha256",
    ):
        assert key in schema["required"], f"baseline schema 缺少 required 字段 {key}"
    for key in ("python", "pandas", "pyarrow"):
        assert key in schema["properties"]["runtime_versions"]["required"]


def test_claim_registry_columns_levels_and_uniqueness() -> None:
    df = pd.read_csv(DATA_REGISTRY / "claim_evidence_registry.csv", dtype=str)
    assert list(df.columns) == [
        "claim_id", "claim", "evidence_level", "source", "source_ref",
        "scope", "limitation", "allowed_wording", "forbidden_wording", "next_gate",
    ]
    assert df["claim_id"].is_unique
    assert (df["claim"].str.len() > 0).all()
    assert set(df["evidence_level"].unique()) <= {"A", "B", "C", "D"}
    for level in ("C", "D"):
        sub = df[df["evidence_level"] == level]
        assert (sub["allowed_wording"].str.len() > 0).all(), (
            f"{level} 级必须给出 allowed_wording"
        )
        assert (sub["forbidden_wording"].str.len() > 0).all(), (
            f"{level} 级必须给出 forbidden_wording"
        )
    assert (df[df["evidence_level"] == "D"]["next_gate"].str.len() > 0).all()


def test_claim_source_refs_traceable() -> None:
    # 审查结论8 P1-5：source_ref 必须可回查（空以——占位；非占位值必须在 sources.md 登记）
    df = pd.read_csv(DATA_REGISTRY / "claim_evidence_registry.csv", dtype=str)
    doc = (REPO / "docs" / "evidence" / "sources.md").read_text(encoding="utf-8")
    refs: set[str] = set()
    for val in df["source_ref"].fillna(""):
        refs.update(token for token in val.split(",") if token.strip() and token.strip() != "—")
    assert refs, "至少一个 claim 应登记可回查 source_ref"
    for ref in sorted(refs):
        assert ref in doc, f"sources.md 未登记 {ref}"
        assert not any(tok in ref for tok in ("http", "D:\\", " ")), (
            f"source_ref 必须用 S-xxx 编号，而非内联描述：{ref}"
        )


def test_claim_c004_next_gate_includes_e1_full() -> None:
    # 审查结论8 §七：可吸收能力必须同时由 E1-Full 阶跃验证 + E2 区间有效性解锁
    df = pd.read_csv(DATA_REGISTRY / "claim_evidence_registry.csv", dtype=str)
    row = df[df["claim_id"] == "C-004"].iloc[0]
    assert "E1-Full" in row["next_gate"] and "E2" in row["next_gate"]


def test_claim_evidence_doc_matches_csv() -> None:
    doc = (REPO / "docs" / "evidence" / "背景与问题证据台账.md").read_text(encoding="utf-8")
    for cid in ("C-001", "C-003", "C-004", "C-005", "C-006"):
        assert cid in doc, f"证据台账文档未引用 {cid}"


def test_online_fields_avoid_forbidden_features() -> None:
    with open(CONFIGS / "forbidden_features.yaml", encoding="utf-8") as fh:
        forbidden = set(yaml.safe_load(fh)["forbidden_features"])
    hit = sorted(set(ONLINE_FIELDS) & forbidden)
    assert not hit, f"在线 schema 命中禁止特征：{hit}"


def test_online_fields_cover_contract() -> None:
    # 审查结论7 §7.1 在线安全字段必须全部出现在在线 schema 允许集中
    for field in ("session_id", "timestamp_utc", "actual_power_kw", "pilot",
                  "connected_elapsed_min", "power_source", "field_mode", "gap_flag"):
        assert field in ONLINE_FIELDS, f"在线字段契约缺失 {field}"


def test_no_absolute_paths_in_e0_config() -> None:
    text = (CONFIGS / "e0_full.yaml").read_text(encoding="utf-8")
    assert "D:\\" not in text and "D:/" not in text, "e0_full.yaml 不得出现绝对路径"
