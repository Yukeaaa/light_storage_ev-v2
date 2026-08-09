"""E3-Full（R1 / E0F-06 E3 部分）双轨人口加载器。

R1-E3 双轨人口（审查结论28 定稿，E0F-02 冻结角色）：
- E3-M（Caltech 主门）：main_evidence_universe =
  L1_strict_matched ∧ role==main ∧ split∈{train,validation,test}（13,477 会话，全部
  caltech.California_Garage_01）。
- E3-X（JPL current-only 跨池佐证门）：
  L1_strict_matched ∧ role==current_only_fallback ∧ field_mode==current_only ∧
  split∈{train,validation,test}（20,925 会话，全部 jpl.Arroyo_Garage_01）。
  必须同时要求 field_mode==current_only：同一 role 内含 163 个 measured_pilot 会话
  （全在 test split；另 42 个在 stress，不进主切分），不能把整个 role 当作 current-only 池。

两轨都使用 E0F-02 已冻结的站点内 60/20/20 时间切分；都做 registry 会话集合 ==
分钟分区会话集合的交叉验证（missing/extra 一律 hard STOP）。

本模块刻意不复用 e1_full.loader（E1 已永久冻结，禁止改动其人口定义）。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

MAIN_LAYER = "L1_strict_matched"
MAIN_SPLITS = ("train", "validation", "test")

# 预注册证据池标签（与 k1_preregister.yaml evidence_pools 语义一致）
CALTECH_MAIN = "caltech.California_Garage_01"
JPL_CURRENT_ONLY = "jpl.Arroyo_Garage_01.current_only"

MAIN_ROLE = "main"
FALLBACK_ROLE = "current_only_fallback"
FALLBACK_FIELD_MODE = "current_only"


def population_sessions(
    registry: pd.DataFrame,
    role: str,
    field_mode: str | None = None,
    splits: tuple[str, ...] = MAIN_SPLITS,
) -> pd.DataFrame:
    """从 split registry 提取某人口（E3-M / E3-X 各自定义），session_id 必须唯一。"""
    mask = (
        (registry["sample_layer"] == MAIN_LAYER)
        & (registry["role"] == role)
        & (registry["split"].isin(splits))
    )
    if field_mode is not None:
        mask = mask & (registry["field_mode"] == field_mode)
    univ = registry[mask].copy()
    if not univ["session_id"].is_unique:
        raise ValueError(f"人口 registry 子集 session_id 必须唯一（role={role}）")
    return univ


def load_evidence_minutes(
    minute_root: Path,
    registry: pd.DataFrame,
    role: str,
    field_mode: str | None = None,
    splits: tuple[str, ...] = MAIN_SPLITS,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """读某人口分钟表（谓词下推 + registry 交叉验证，missing/extra → hard STOP）。"""
    universe = population_sessions(registry, role=role, field_mode=field_mode, splits=splits)
    universe_ids = set(universe["session_id"])

    predicate = (
        (ds.field("sample_layer") == MAIN_LAYER)
        & (ds.field("role") == role)
        & ds.field("split").isin(list(splits))
    )
    if field_mode is not None:
        predicate = predicate & (ds.field("field_mode") == field_mode)

    df: pd.DataFrame = ds.dataset(str(minute_root)).to_table(
        filter=predicate, columns=columns
    ).to_pandas()

    df_ids = set(df["session_id"])
    missing = universe_ids - df_ids
    extra = df_ids - universe_ids
    if missing or extra:
        raise ValueError(
            f"E3-Full 人口分钟表与 registry 会话集合不一致（role={role}"
            f" field_mode={field_mode} splits={splits}）："
            f"missing={len(missing)} extra={len(extra)}"
        )

    df["minutes_from_end"] = (
        (df["disconnect_time"] - df["timestamp_utc"]).dt.total_seconds() / 60.0
    )
    df["cycle_month"] = df["timestamp_utc"].astype(str).str[:7]
    return df


def load_caltech_main(
    minute_root: Path,
    registry: pd.DataFrame,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """E3-M：Caltech 主门人口（L1 ∧ main）。"""
    return load_evidence_minutes(
        minute_root, registry, role=MAIN_ROLE, columns=columns
    )


def load_jpl_current_only(
    minute_root: Path,
    registry: pd.DataFrame,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """E3-X：JPL current-only 跨池佐证人口（L1 ∧ current_only_fallback ∧ current_only）。"""
    return load_evidence_minutes(
        minute_root,
        registry,
        role=FALLBACK_ROLE,
        field_mode=FALLBACK_FIELD_MODE,
        columns=columns,
    )


def split_minutes(df: pd.DataFrame, split: str) -> pd.DataFrame:
    """按 split 隔离分钟表（整条会话不跨 split）。"""
    sub = df[df["split"] == split]
    if sub.empty:
        raise ValueError(f"split={split} 无分钟数据")
    return sub
