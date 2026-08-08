"""E0F-02 会话级时间切分与样本层/角色注册（V2.1 §10.3；审查结论14/15；E0F-02 口径）。

职责：
1. canonical session universe：全部 85,877 个有静态时序的会话（matched 40,644 +
   static_only 45,233）。api_only 无静态响应时序，不进入本 registry。
2. canonical connection_time（审查结论9 强制）：
   - matched + API connectionTime 可解析且不矛盾 → api_metadata；
   - matched + 缺失/无法解析 → first_observation_fallback（允许自动回退）；
   - matched + 可解析但与首条观测明显矛盾 → 仅登记 anomaly，禁止自动替换
     （connection_time 保持 API 值，source 仍记 api_metadata，另设 anomaly_flag/reason）；
   - static_only → first_observation_fallback（首条有效观测，来自 manifest.time_min）。
3. 时间切分（split 只表示时间位置，不授予训练资格）：站点内按
   [connection_time_canonical, session_id] mergesort 稳定排序，前 60% train /
   中 20% validation / 后 20% test；external（office001）→ external；异常月份 → stress。
   与 tests/test_e0_split.py 金标准 assign_split 逐会话对齐。
4. sample_layer 分离证据层级：matched → L1_strict_matched；static_only → L0_static_extension。
   main_evidence_universe（主证据体系资格，与模型权限无关）=
       sample_layer == L1_strict_matched ∧ role == main ∧ split ∈ {train, validation, test}。
   模型权限必须单独冻结，禁止把 train/validation/test 混为一谈：
       fit_eligible:             split == train
       model_selection_eligible: split == validation
       final_test_eligible:      split == test
   test 只允许一次正式评估：不得据此选择特征/阈值/模型/支持域规则，不得根据 test 图形回调参数。
   JPL boundary/current_only_fallback 即使 split==train 也不得获得主模型调参资格。
5. role 独立于时间 split：caltech → main；jpl.Arroyo_Garage_01（2020-06/07）→ boundary；
   其余 jpl → current_only_fallback；office001 → external_only。
6. field_mode 五类（measured_pilot/measured_no_pilot/computed_pilot/computed_no_pilot/
   current_only）与时间 split 分开注册。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.io.paths import acn_project_dir

_TRAIN_RATIO = 0.6
_VAL_RATIO = 0.2

_FIELD_MODE_CATEGORIES = {
    "measured_pilot",
    "measured_no_pilot",
    "computed_pilot",
    "computed_no_pilot",
    "current_only",
}

_REGISTRY_COLUMNS = [
    "session_id",
    "site_raw",
    "site",
    "site_canonical",
    "garage",
    "station",
    "connection_time",
    "connection_time_canonical",
    "connection_time_source",
    "disconnect_time",
    "field_mode",
    "match_status",
    "sample_layer",
    "role",
    "split",
    "split_rule_version",
    "stress",
    "external",
    "source_file",
    "anomaly_flag",
    "anomaly_reason",
]

_MATCHED = "matched"
_STATIC_ONLY = "static_only"
_L1 = "L1_strict_matched"
_L0 = "L0_static_extension"


def assign_split(
    sessions: pd.DataFrame,
    train_ratio: float = _TRAIN_RATIO,
    val_ratio: float = _VAL_RATIO,
) -> pd.DataFrame:
    """生产切分实现，与 tests/test_e0_split.py 金标准 assign_split 逐会话对齐。

    输入列：session_id, site, connection_time, is_external, is_stress。
    输出：与输入同序的 DataFrame，追加 `split` 列（train/validation/test/external/stress）。
    """
    out = sessions.copy()
    out["split"] = ""
    if len(out) == 0:
        return out
    if not out["session_id"].is_unique:
        raise ValueError("切分输入必须是会话级：session_id 不得重复（禁止按分钟切分）")

    ext = out["is_external"].astype(bool)
    stress = out["is_stress"].astype(bool)
    out.loc[ext, "split"] = "external"
    out.loc[stress & ~ext, "split"] = "stress"

    eligible = out[~(ext | stress)].copy()
    for _site, g in eligible.groupby("site", sort=False):
        g = g.sort_values(["connection_time", "session_id"], kind="mergesort")
        n = len(g)
        n_train = int(round(n * train_ratio))
        n_val = int(round(n * val_ratio))
        n_test = n - n_train - n_val
        labels = ["train"] * n_train + ["validation"] * n_val + ["test"] * n_test
        out.loc[g.index, "split"] = labels
    return out


def classify_field_mode(
    has_power: bool,
    has_voltage: bool,
    has_current: bool,
    has_pilot: bool,
) -> str:
    """逐文件 field_mode 五类（e0_full.yaml field_modes.per_file_rule）。"""
    if has_power and has_pilot:
        return "measured_pilot"
    if has_power:
        return "measured_no_pilot"
    if has_voltage and has_current and has_pilot:
        return "computed_pilot"
    if has_voltage and has_current:
        return "computed_no_pilot"
    return "current_only"


def resolve_role(
    site_canonical: str,
    garage: str,
    month: str,
    k1_role_months: dict[str, Any],
) -> str:
    """数据角色（独立于时间 split；审查结论15 锁定的 role 语义）。"""
    if site_canonical == "office001":
        return "external_only"
    if site_canonical == "caltech":
        return "main"
    if (
        garage == "Arroyo_Garage_01"
        and month in set(k1_role_months.get("jpl_boundary_window", []))
    ):
        return "boundary"
    return "current_only_fallback"


def _parse_utc(value: Any) -> pd.Timestamp | None:
    """把 API/静态 manifest 的 ISO 时刻解析为 UTC Timestamp；缺失返回 None。"""
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    s = str(value)
    if not s or s == "nan":
        return None
    try:
        ts = pd.Timestamp(s)
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def build_split_registry(
    mapping: pd.DataFrame,
    audit: pd.DataFrame,
    api_meta: pd.DataFrame,
    manifest: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """组装 85,877 会话的 split registry（matched + static_only，api_only 排除）。

    输入列要求：
    - mapping：static_api_mapping.csv（match_status/sessionID/site_static/garage/stationID/
      connection_time/static_file）
    - audit：e0_full_connection_time_audit.parquet（matched 会话的 connectionTime 审计）
    - api_meta：api_metadata_index.csv（sessionID/disconnectTime）
    - manifest：e0_full_source_manifest.parquet（logical_path/time_min/has_* 逐文件覆盖）
    """
    raw_to_canonical: dict[str, str] = cfg["site_mapping"]["raw_to_canonical"]
    external_only = set(cfg["split"]["external_only"])
    anomaly_months = set(cfg["anomaly_months"])
    anomaly_year_2021 = bool(cfg.get("anomaly_year_2021"))
    k1_role_months = cfg.get("k1_role_months", {})
    split_rule_version = cfg["split"]["rule_version"]

    mb = mapping[mapping["match_status"].isin([_MATCHED, _STATIC_ONLY])].copy()
    mb["static_file_norm"] = mb["static_file"].str.replace("\\", "/", regex=False)

    _assert_key_unique(audit, "session_id", "connection_time_audit")
    _assert_key_unique(manifest, "logical_path", "source_manifest")
    audit_idx = audit.set_index("session_id") if not audit.empty else pd.DataFrame()

    if "disconnectTime" in api_meta.columns:
        api_disc_src = api_meta[["sessionID", "disconnectTime"]].dropna(subset=["sessionID"])
        _assert_key_unique(api_disc_src, "sessionID", "api_metadata_index")
        api_disc = api_disc_src.set_index("sessionID")["disconnectTime"]
    else:
        api_disc = pd.Series(dtype=str)

    mf = manifest.set_index("logical_path")

    rows: list[dict[str, Any]] = []
    missing_manifest: list[str] = []
    for _, r in mb.iterrows():
        status = str(r["match_status"])
        site_raw = str(r["site_static"])
        site_canonical = raw_to_canonical.get(site_raw, site_raw)
        garage = str(r["garage"]) if pd.notna(r["garage"]) else ""
        station = str(r["stationID"]) if pd.notna(r["stationID"]) else ""
        sf = str(r["static_file"]).replace("\\", "/")
        m = mf.loc[sf] if sf in mf.index else None
        if m is None:
            missing_manifest.append(sf)
            continue

        anomaly = False
        reason: str | None = None
        disconnect: Any = None
        if status == _MATCHED:
            session = str(r["sessionID"])
            a: pd.Series | None = None
            if not audit_idx.empty and session in audit_idx.index:
                a = audit_idx.loc[[session]].iloc[0]
            if a is None:
                src: Any = "first_observation_fallback"
                a_first: Any = None
                a_ts: Any = None
                a_reason: Any = None
            else:
                src = str(a["connection_time_source"])
                a_first = a["first_observation_utc"]
                a_ts = a["api_connection_time_utc"]
                a_reason = a["anomaly_reason"]
            if src == "first_observation_fallback":
                raw_ct = (
                    a_first
                    if a_first is not None and pd.notna(a_first)
                    else m["time_min"]
                )
                ct = _parse_utc(raw_ct)
                source = "first_observation_fallback"
            else:
                ct = _parse_utc(a_ts)
                source = "api_metadata"
                anomaly = src == "anomaly"
                if anomaly and pd.notna(a_reason):
                    reason = str(a_reason)
            if session in api_disc.index:
                disconnect = api_disc.loc[session]
            sample_layer = _L1
        else:
            session = (
                station.replace("-", "_")
                + "_"
                + str(r["connection_time"]).replace("T", " ")
            )
            ct = _parse_utc(m["time_min"])
            source = "first_observation_fallback"
            sample_layer = _L0

        field_mode = classify_field_mode(
            has_power=bool(m["has_power"]),
            has_voltage=bool(m["has_voltage"]),
            has_current=bool(m["has_current"]),
            has_pilot=bool(m["has_pilot"]),
        )

        month: str | None = None
        stress = False
        if ct is not None:
            month = ct.strftime("%Y-%m")
            stress = month in anomaly_months or (
                anomaly_year_2021 and ct.year == 2021
            )

        external = site_canonical in external_only
        role = resolve_role(site_canonical, garage, month or "", k1_role_months)

        rows.append(
            {
                "session_id": session,
                "site_raw": site_raw,
                "site": site_canonical,
                "site_canonical": site_canonical,
                "garage": garage,
                "station": station,
                "connection_time": ct,
                "connection_time_canonical": ct,
                "connection_time_source": source,
                "disconnect_time": _parse_utc(disconnect),
                "field_mode": field_mode,
                "match_status": status,
                "sample_layer": sample_layer,
                "role": role,
                "split": "",
                "split_rule_version": split_rule_version,
                "stress": bool(stress),
                "external": bool(external),
                "source_file": sf,
                "anomaly_flag": bool(anomaly),
                "anomaly_reason": reason,
            }
        )

    if missing_manifest:
        raise ValueError(
            f"E0F-02 停止：{len(missing_manifest)} 个静态会话不在 manifest 中，"
            f"无法确定首条观测/field_mode；首个：{missing_manifest[0]}"
        )

    reg = pd.DataFrame(rows)
    if reg.empty:
        reg = pd.DataFrame({c: pd.Series(dtype="object") for c in _REGISTRY_COLUMNS})
    else:
        reg["connection_time"] = pd.to_datetime(reg["connection_time"], utc=True)
        reg["connection_time_canonical"] = reg["connection_time"]
        reg["disconnect_time"] = pd.to_datetime(reg["disconnect_time"], utc=True)

    sessions = pd.DataFrame(
        {
            "session_id": reg["session_id"],
            "site": reg["site_canonical"],
            "connection_time": reg["connection_time_canonical"],
            "is_external": reg["external"],
            "is_stress": reg["stress"],
        }
    )
    split_out = assign_split(sessions)
    reg["split"] = split_out["split"].values

    reg = reg.sort_values(["site_raw", "session_id"]).reset_index(drop=True)
    reg = reg[_REGISTRY_COLUMNS]
    _assert_registry_invariants(reg, cfg)
    return reg


def _assert_key_unique(df: pd.DataFrame, key: str, label: str) -> None:
    """可追溯性关键索引唯一性 fail-fast（审查结论16 P0-3）：原始重复禁止静默丢弃。"""
    col = df[key]
    dup = col[col.duplicated()]
    if not dup.empty:
        raise ValueError(
            f"E0F-02 停止：{label} 键必须唯一，发现 {len(dup)} 个重复"
            "（原始异常禁止静默 drop_duplicates，须显式登记消歧）；"
            f"首例重复键：{dup.iloc[0]}"
        )


def _assert_registry_invariants(reg: pd.DataFrame, cfg: dict[str, Any]) -> None:
    """E0F-02 验收不变量（审查结论15/16 冻结）。

    结构不变量 + 人口冻结 machine STOP（审查结论16 P0-2）：population 数字不再只是
    报告检查，任何偏离 cfg 冻结值（85877/40644/45233）直接 raise。
    """
    if len(reg) == 0:
        raise ValueError("E0F-02 验收失败：registry 为空（冻结 population 不为零）")
    if not reg["session_id"].is_unique:
        raise ValueError("E0F-02 验收失败：session_id 必须唯一（每会话恰好一行）")
    if reg["session_id"].isna().any():
        raise ValueError("E0F-02 验收失败：session_id 不得为空")
    if not reg["split"].isin(["train", "validation", "test", "external", "stress"]).all():
        raise ValueError("E0F-02 验收失败：split 必须是冻结五值")
    if reg.groupby("session_id")["split"].nunique().ne(1).any():
        raise ValueError("E0F-02 验收失败：同一会话只能有一个 split")
    if not (
        reg["sample_layer"].isin([_L1, _L0])
        & (
            ((reg["sample_layer"] == _L1) & (reg["match_status"] == _MATCHED))
            | ((reg["sample_layer"] == _L0) & (reg["match_status"] == _STATIC_ONLY))
        )
    ).all():
        raise ValueError("E0F-02 验收失败：sample_layer 必须与 match_status 一致")
    if reg["connection_time"].isna().any():
        raise ValueError("E0F-02 验收失败：canonical connection_time 不得为空")
    if not reg["connection_time_source"].isin(["api_metadata", "first_observation_fallback"]).all():
        raise ValueError("E0F-02 验收失败：connection_time_source 必须是冻结二值")
    if not reg["role"].isin(
        ["main", "boundary", "current_only_fallback", "external_only"]
    ).all():
        raise ValueError("E0F-02 验收失败：role 必须是冻结四值")
    if not reg["field_mode"].isin(_FIELD_MODE_CATEGORIES).all():
        raise ValueError("E0F-02 验收失败：field_mode 必须是冻结五类")

    frozen = cfg["inputs"]["manifests"]
    expected_rows = int(frozen["static_file_index_rows"])
    expected_matched = int(frozen["match_status"]["matched"])
    expected_static = int(frozen["match_status"]["static_only"])
    if len(reg) != expected_rows:
        raise ValueError(
            f"E0F-02 人口冻结 STOP：registry 行数 {len(reg)} != 冻结 {expected_rows}"
            "（上游 mapping 变化必须显式评审，禁止静默接受新 population）"
        )
    if int((reg["match_status"] == _MATCHED).sum()) != expected_matched:
        raise ValueError(
            f"E0F-02 人口冻结 STOP：matched {(reg['match_status'] == _MATCHED).sum()} "
            f"!= 冻结 {expected_matched}"
        )
    if int((reg["match_status"] == _STATIC_ONLY).sum()) != expected_static:
        raise ValueError(
            f"E0F-02 人口冻结 STOP：static_only {(reg['match_status'] == _STATIC_ONLY).sum()} "
            f"!= 冻结 {expected_static}"
        )
    if bool((reg["match_status"] == "api_only").any()):
        raise ValueError("E0F-02 人口冻结 STOP：registry 不得含 api_only 会话")


def _assert_cross_registry_consistency(reg: pd.DataFrame, fm: pd.DataFrame) -> None:
    """split registry 与 field_mode registry 会话集合完全一致（审查结论16 P0-2）。"""
    only_fm = sorted(set(fm["session_id"]) - set(reg["session_id"]))
    only_reg = sorted(set(reg["session_id"]) - set(fm["session_id"]))
    if only_fm or only_reg:
        raise ValueError(
            "E0F-02 验收失败：split registry 与 field_mode registry 会话集合必须完全一致"
            f"；仅 field_mode 有 {len(only_fm)} 个、仅 split 有 {len(only_reg)} 个"
        )


def build_field_mode_registry(
    mapping: pd.DataFrame,
    manifest: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """逐会话 field_mode 注册（与时间 split 分开；冻结五类 + 底层覆盖标志）。"""
    raw_to_canonical: dict[str, str] = cfg["site_mapping"]["raw_to_canonical"]
    mb = mapping[mapping["match_status"].isin([_MATCHED, _STATIC_ONLY])].copy()
    mb["static_file_norm"] = mb["static_file"].str.replace("\\", "/", regex=False)
    mb["_sid"] = np.where(
        mb["match_status"] == _MATCHED,
        mb["sessionID"],
        mb["stationID"].str.replace("-", "_", regex=False)
        + "_"
        + mb["connection_time"].str.replace("T", " ", regex=False),
    )
    mf = manifest.set_index("logical_path")
    _assert_key_unique(manifest, "logical_path", "source_manifest")

    rows: list[dict[str, Any]] = []
    for _, r in mb.iterrows():
        sf = str(r["static_file"]).replace("\\", "/")
        m = mf.loc[sf] if sf in mf.index else None
        if m is None:
            continue
        site_raw = str(r["site_static"])
        site_canonical = raw_to_canonical.get(site_raw, site_raw)
        status = str(r["match_status"])
        rows.append(
            {
                "session_id": r["_sid"],
                "site_raw": site_raw,
                "site": site_canonical,
                "garage": str(r["garage"]) if pd.notna(r["garage"]) else "",
                "station": str(r["stationID"]) if pd.notna(r["stationID"]) else "",
                "field_mode": classify_field_mode(
                    has_power=bool(m["has_power"]),
                    has_voltage=bool(m["has_voltage"]),
                    has_current=bool(m["has_current"]),
                    has_pilot=bool(m["has_pilot"]),
                ),
                "has_power": bool(m["has_power"]),
                "has_voltage": bool(m["has_voltage"]),
                "has_current": bool(m["has_current"]),
                "has_pilot": bool(m["has_pilot"]),
                "match_status": status,
                "sample_layer": _L1 if status == _MATCHED else _L0,
                "source_file": sf,
            }
        )
    fm = pd.DataFrame(rows).sort_values(["site_raw", "session_id"]).reset_index(drop=True)
    return fm


def run_e0f02(
    cfg_path: str | Path | None = None,
    require_clean_baseline: bool = True,
) -> dict[str, Any]:
    """E0F-02 全量执行：split registry → field_mode registry → 审计报告 → baseline 更新。

    产物：
    - data_registry/e0_full_split_registry.parquet
    - data_registry/e0_full_field_mode_registry.parquet
    - reports/E0_Full_split_audit.md
    - data_registry/e0_full_baseline.json（追加 split_registry 哈希）
    """
    cfg = load_yaml(cfg_path or (Path(__file__).resolve().parents[3] / "configs" / "e0_full.yaml"))
    acn = acn_project_dir()
    impl_root = Path(__file__).resolve().parents[3]

    mapping = pd.read_csv(acn / "manifests" / "static_api_mapping.csv", dtype=str)
    api_meta = pd.read_csv(acn / "manifests" / "api_metadata_index.csv", dtype=str)
    audit = pd.read_parquet(impl_root / "data_registry" / "e0_full_connection_time_audit.parquet")
    manifest = pd.read_parquet(impl_root / "data_registry" / "e0_full_source_manifest.parquet")

    reg = build_split_registry(mapping, audit, api_meta, manifest, cfg)
    split_out = impl_root / "data_registry" / "e0_full_split_registry.parquet"
    split_out.parent.mkdir(parents=True, exist_ok=True)
    reg.to_parquet(split_out, index=False)

    fm = build_field_mode_registry(mapping, manifest, cfg)
    _assert_cross_registry_consistency(reg, fm)
    fm_out = impl_root / "data_registry" / "e0_full_field_mode_registry.parquet"
    fm_out.parent.mkdir(parents=True, exist_ok=True)
    fm.to_parquet(fm_out, index=False)

    report = _build_split_audit_report(reg, fm, cfg)
    report_out = impl_root / "reports" / "E0_Full_split_audit.md"
    report_out.write_text(report, encoding="utf-8")

    # source manifest 哈希沿用 E0F-01 冻结值（manifest 本轮未重建），避免改动机密值
    prev_baseline: dict[str, Any] = {}
    baseline_out = impl_root / "data_registry" / "e0_full_baseline.json"
    if baseline_out.exists():
        prev_baseline = json.loads(baseline_out.read_text(encoding="utf-8"))
    manifest_hash_hex = prev_baseline.get("source_manifest_sha256")

    from patent_preexperiment.e0_full.baseline import build_e0_full_baseline
    from patent_preexperiment.e0_full.input_audit import manifest_hash

    split_registry_meta = {
        "split_registry": {
            "sha256": _sha256_file(split_out),
            "rows": int(len(reg)),
            "matched": int((reg["match_status"] == _MATCHED).sum()),
            "static_only": int((reg["match_status"] == _STATIC_ONLY).sum()),
            "api_only": 0,
            "anomaly": int(reg["anomaly_flag"].sum()),
        },
        "field_mode_registry": {
            "sha256": _sha256_file(fm_out),
            "rows": int(len(fm)),
        },
    }
    build_e0_full_baseline(
        out=baseline_out,
        manifest_hash_hex=str(manifest_hash_hex) if manifest_hash_hex else manifest_hash(manifest),
        config=cfg,
        require_clean=require_clean_baseline,
        split_registry=split_registry_meta,
    )

    return {
        "split_registry": str(split_out),
        "field_mode_registry": str(fm_out),
        "report": str(report_out),
        "baseline": str(baseline_out),
    }


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_split_audit_report(
    reg: pd.DataFrame,
    fm: pd.DataFrame,
    cfg: dict[str, Any],
) -> str:
    frozen = cfg["inputs"]["manifests"]
    n_all = int(frozen["static_file_index_rows"])
    n_matched = int(frozen["match_status"]["matched"])
    n_static = int(frozen["match_status"]["static_only"])
    lines: list[str] = [
        "# E0-Full 时间切分审计（E0F-02）",
        "",
        "## 口径声明",
        "",
        "split registry 表示**时间位置**，不表示**训练资格**。",
        f"全部 {n_all:,} 个有静态时序的会话进入统一 registry；{n_matched:,} matched 属 L1 严格集，",
        f"{n_static:,} static_only 属 L0 扩展集；api_only 无静态响应时序，不进入本 registry。",
        "main_evidence_universe（主证据体系资格，与模型权限无关）="
        " `sample_layer==L1_strict_matched` ∧ `role==main` ∧ "
        "`split in {train,validation,test}`。",
        "模型权限必须单独冻结：fit_eligible=`split==train`；"
        "model_selection_eligible=`split==validation`；final_test_eligible=`split==test`。",
        "test 只允许一次正式评估：不得据此选择特征/阈值/模型/支持域规则，"
        "不得根据 test 图形回调参数。",
        "JPL boundary/current_only_fallback 即使 `split==train` 也不得获得主模型调参资格。",
        "",
        "## 验收不变量",
        "",
    ]
    counts = {
        "registry 行数": int(len(reg)),
        "matched": int((reg["match_status"] == _MATCHED).sum()),
        "static_only": int((reg["match_status"] == _STATIC_ONLY).sum()),
        "api_only": 0,
        "session_id 唯一": bool(reg["session_id"].is_unique),
        "每会话单一 split": bool(reg.groupby("session_id")["split"].nunique().eq(1).all()),
        "sample_layer↔match_status 一致": bool(
            (
                ((reg["sample_layer"] == _L1) & (reg["match_status"] == _MATCHED))
                | ((reg["sample_layer"] == _L0) & (reg["match_status"] == _STATIC_ONLY))
            ).all()
        ),
        "external 不进主切分": bool(
            (~reg["external"] | (reg["split"] == "external")).all()
        ),
        "stress 不进主切分": bool(
            (~reg["stress"] | reg["split"].isin(["stress", "external"])).all()
        ),
    }
    for k, v in counts.items():
        lines.append(f"- {k}：{v}")
    lines.append("")

    lines += ["## connection_time_source 分布", ""]
    ct_tab = reg.groupby(["match_status", "connection_time_source"]).size().unstack(fill_value=0)
    lines.append(ct_tab.to_string())
    anomaly = reg[reg["anomaly_flag"]]
    lines.append("")
    lines.append(f"- anomaly 会话：{len(anomaly)}（仅登记，禁止自动替换）")
    if len(anomaly):
        for _, r in anomaly.iterrows():
            lines.append(f"  - {r['session_id']}：{r['anomaly_reason']}")
    lines.append("")

    lines += ["## field_mode 分布（field_mode_registry 同源）", ""]
    lines.append(fm["field_mode"].value_counts().to_string())
    lines.append("")

    lines += ["## role 分布（独立于时间 split）", ""]
    lines.append(reg["role"].value_counts().to_string())
    lines.append("")

    lines += ["## role×field_mode 交叉审计（role ≠ 字段模式；审查结论16 P1）", ""]
    rf = reg.pivot_table(
        index="role", columns="field_mode", values="session_id", aggfunc="count", fill_value=0
    )
    lines.append(rf.to_string())
    lines.append("")
    lines.append(
        "注意：`role==current_only_fallback` 只是粗粒度证据角色（jpl 非 boundary 会话），"
        "**不意味着**该会话是 `field_mode==current_only`。K1 current-only 证据池必须显式"
        "同时满足 `role==current_only_fallback` ∧ `field_mode==current_only` ∧ 冻结月份资格 "
        "∧ K1 原有其他 eligibility（最终以 R1 冻结协议为准），禁止以 role 单独冒充 "
        "current-only 池。"
    )
    lines.append("")

    lines += ["## role×sample_layer 交叉审计（审查结论16 P1）", ""]
    rs = reg.pivot_table(
        index="role", columns="sample_layer", values="session_id", aggfunc="count", fill_value=0
    )
    lines.append(rs.to_string())
    lines.append("")

    lines += ["## stress 分布", ""]
    stress_tab = (
        reg.assign(_m=reg["connection_time"].dt.strftime("%Y-%m"))
        .loc[reg["stress"]]
        .groupby("_m")
        .size()
    )
    if len(stress_tab):
        lines.append(stress_tab.to_string())
    else:
        lines.append("（无 stress 会话）")
    stress_ext = int((reg["stress"] & reg["external"]).sum())
    lines.append("")
    lines.append(
        "注：stress 标记（=True 含外部站点）总数 "
        f"{int(reg['stress'].sum())}，其中 office001 外部站点在异常月 {stress_ext} 个会话"
        " 因 external 优先被归为 `split==external`（不进 stress/test 主集合）。"
    )
    lines.append("")

    lines += ["## 主切分（train/validation/test）按站点", ""]
    for site, g in reg[reg["split"].isin(["train", "validation", "test"])].groupby("site"):
        vc = g["split"].value_counts()
        n = len(g)
        shares = "  ".join(
            f"{k}={vc.get(k, 0)} ({vc.get(k, 0) / n:.1%})"
            for k in ("train", "validation", "test")
        )
        lines.append(f"- {site}（n={n}）：{shares}")
    lines.append("")

    lines += [
        "## role×split 交叉审计（验证 role 作为正交治理字段保存，role 不参与 assign_split 决策）",
        "",
    ]
    cross = reg.pivot_table(
        index="role", columns="split", values="session_id", aggfunc="count", fill_value=0
    )
    lines.append(cross.to_string())
    lines.append("")

    lines += [
        "## 规则依据",
        "",
        f"- split.rule：`{cfg['split']['rule']}`",
        f"- split.rule_version：`{cfg['split']['rule_version']}`",
        f"- split.external_only：`{cfg['split']['external_only']}`",
        f"- anomaly_months：`{cfg['anomaly_months']}`，"
        f"anomaly_year_2021：`{cfg['anomaly_year_2021']}`",
        f"- connection_time 审计规则：`{cfg['session_join']['connection_time']['audit']['rule']}`",
        f"- field_mode 类别：`{sorted(cfg['field_modes']['categories'])}`",
        f"- role：main=`{cfg['roles']['main']}`，boundary=`{cfg['roles']['boundary']}`，",
        f"  current_only_fallback=`{cfg['roles']['current_only_fallback']}`，"
        f"external_only=`{cfg['roles']['external_only']}`",
        "",
        "金标准对齐：split 由 `assign_split` 按 [connection_time, session_id] mergesort 稳定排序",
        "逐会话生成，与 `tests/test_e0_split.py` 参考实现逐会话对齐（无随机性）。",
    ]
    return "\n".join(lines) + "\n"
