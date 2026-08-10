"""P1 — office001 站点内时间切分（Phase 3 v1.0.2 §1.4：先确定并哈希，test 不可先读）。

与 E0F-02 的关系：
- P1 只取 office001 ∧ L1_strict_matched 会话（严格会话验证口径；static_only 不进入）。
- E0F-02 中 office001 全部是 split=external（仅外部验证、不参与阈值选择）；P1 需要
  office001 站点内 60/20/20，故在此为 office001 单独冻结主切分。
- 排序键沿用 E0F-02：[connection_time_canonical, session_id] mergesort 稳定排序，
  session_id 作确定性 tie-break，无随机性。
- 异常月份会话（stress=True）标记 split=stress，不进主切分，仅敏感性（协议 §1.4）。
- split registry 含 test session_id/role/split（SHA 冻结需要），但**不写入任何
  E1 label / outcome 字段**；test 的 E1 事件在 Step 0 及之前一律不可读取。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml

_TRAIN_RATIO = 0.6
_VAL_RATIO = 0.2

_REGISTRY_COLUMNS = [
    "session_id",
    "site_canonical",
    "garage",
    "station",
    "connection_time",
    "connection_time_source",
    "field_mode",
    "match_status",
    "sample_layer",
    "role",
    "split",
    "split_rule_version",
    "stress",
    "source_file",
    "anomaly_flag",
    "anomaly_reason",
]


def assign_split(
    sessions: pd.DataFrame,
    train_ratio: float = _TRAIN_RATIO,
    val_ratio: float = _VAL_RATIO,
) -> pd.DataFrame:
    """office001 站点内切分；与 E0F-02 assign_split 同规则（金标准对齐）。"""
    out = sessions.copy()
    out["split"] = ""
    if len(out) == 0:
        return out
    if not out["session_id"].is_unique:
        raise ValueError("P1 切分输入必须是会话级：session_id 不得重复")
    g = out.sort_values(["connection_time", "session_id"], kind="mergesort")
    n = len(g)
    n_train = int(round(n * train_ratio))
    n_val = int(round(n * val_ratio))
    n_test = n - n_train - n_val
    out.loc[g.index, "split"] = (
        ["train"] * n_train + ["validation"] * n_val + ["test"] * n_test
    )
    return out


def build_p1_split_registry(
    e0_registry: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """从 E0F-02 split registry 冻结 office001 P1 主切分。"""
    site = cfg["site"]
    if site != "office001":
        raise ValueError(f"P1 冻结站点必须是 office001，当前 {site!r}（取配置误用）")

    sub = e0_registry[
        (e0_registry["site_canonical"] == "office001")
        & (e0_registry["sample_layer"] == "L1_strict_matched")
        & (e0_registry["match_status"] == "matched")
    ].copy()
    if sub.empty:
        raise ValueError("P1 冻结失败：office001 matched 会话为空")

    sub["split"] = np.where(sub["stress"], "stress", "")
    eligible = sub[sub["split"] != "stress"].copy()
    split_out = assign_split(eligible)
    sub.loc[eligible.index, "split"] = split_out["split"].values

    sub = sub.sort_values(["connection_time", "session_id"], kind="mergesort")
    sub = sub[_REGISTRY_COLUMNS].reset_index(drop=True)
    _assert_registry_invariants(sub)
    return sub


def _assert_registry_invariants(reg: pd.DataFrame) -> None:
    if reg.empty:
        raise ValueError("P1 验收失败：registry 为空")
    if not reg["session_id"].is_unique:
        raise ValueError("P1 验收失败：session_id 必须唯一")
    if reg["session_id"].isna().any():
        raise ValueError("P1 验收失败：session_id 不得为空")
    if not reg["split"].isin(["train", "validation", "test", "stress"]).all():
        raise ValueError("P1 验收失败：split 必须是冻结四值（无 external，无空值）")
    if reg.groupby("session_id")["split"].nunique().ne(1).any():
        raise ValueError("P1 验收失败：同一会话只能有一个 split")
    if not (reg["sample_layer"] == "L1_strict_matched").all():
        raise ValueError("P1 验收失败：必须全为 L1_strict_matched")
    if not (reg["match_status"] == "matched").all():
        raise ValueError("P1 验收失败：必须全为 matched")
    if not (reg["site_canonical"] == "office001").all():
        raise ValueError("P1 验收失败：必须全为 office001")
    if not (
        reg["connection_time"].isna().eq(False).all()
        and (reg["connection_time"].dt.tz is not None)
    ):
        raise ValueError("P1 验收失败：connection_time 必须全部可解析且为 UTC-aware")
    if (reg["stress"] & reg["split"].isin(["train", "validation", "test"])).any():
        raise ValueError("P1 验收失败：stress 会话不得进入主切分")
    if not (reg["split"] == "stress").eq(reg["stress"]).all():
        raise ValueError("P1 验收失败：split=stress 必须与 stress 标志一致")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_p1_split_freeze(
    impl_root: Path,
    cfg_path: str | Path | None = None,
) -> dict[str, Any]:
    """P1 split freeze：office001 60/20/20 registry + SHA256 + 元数据（不含任何 E1 字段）。"""
    cfg = load_yaml(cfg_path or (impl_root / "configs" / "p1.yaml"))
    e0_registry = pd.read_parquet(impl_root / "data_registry" / "e0_full_split_registry.parquet")
    reg = build_p1_split_registry(e0_registry, cfg)

    out_path = impl_root / "data_registry" / "p1_office001_split_registry.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    reg.to_parquet(out_path, index=False)

    sha = sha256_file(out_path)
    meta = {
        "experiment_id": cfg["experiment_id"],
        "protocol_version": cfg["protocol_version"],
        "rule_version": cfg["rule_version"],
        "site": "office001",
        "population": cfg["split"]["population"],
        "split_rule": cfg["split"]["rule"],
        "ratios": cfg["split"]["ratios"],
        "registry_path": str(out_path.relative_to(impl_root)),
        "sha256": sha,
        "rows": int(len(reg)),
        "matched": int((reg["match_status"] == "matched").sum()),
        "static_only": 0,
        "split_counts": reg["split"].value_counts().to_dict(),
        "n_stations": int(reg["station"].nunique()),
        "months": sorted(
            reg.loc[reg["split"].isin(["train", "validation", "test"]), "connection_time"]
            .dt.strftime("%Y-%m").unique().tolist()
        ),
        "stress_sessions": int((reg["split"] == "stress").sum()),
        "contains_e1_fields": False,
        "note": "split registry 只含 session_id/role/split 元数据；不含任何 E1 label/outcome 字段；"
                "test 的 E1 事件在正式 test 前禁止读取。",
    }
    meta_path = impl_root / "data_registry" / "p1_office001_split_sha256.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
