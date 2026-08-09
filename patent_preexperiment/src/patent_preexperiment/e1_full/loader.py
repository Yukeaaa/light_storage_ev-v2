"""E1-Full 加载器（R1 / E0F-06 硬切分复现）：主证据体系分钟表。

主证据体系（main evidence universe，V2.1 §10.3 / split.py 口径）=
    sample_layer == L1_strict_matched ∧ role == main ∧ split ∈ {train, validation, test}。

加载方式：直接读 session_response_1min 分区（每行已带 E0F-02 治理列
site/split/role/field_mode/match_status），用 pyarrow 谓词下推过滤后
再与 split registry 交叉验证会话集合（missing=0 / extra=0）。
派生列：minutes_from_end = (disconnect_time - timestamp_utc)/60（离线标签，仅排除尾段）；
cycle_month = timestamp_utc 所在月份（分钟/控制周期所在月份）。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

MAIN_LAYER = "L1_strict_matched"
MAIN_ROLE = "main"
MAIN_SPLITS = ("train", "validation", "test")


def main_evidence_universe(registry: pd.DataFrame) -> pd.DataFrame:
    """从 split registry 提取主证据体系会话（L1 ∧ role==main ∧ split∈train/val/test）。"""
    univ = registry[
        (registry["sample_layer"] == MAIN_LAYER)
        & (registry["role"] == MAIN_ROLE)
        & (registry["split"].isin(MAIN_SPLITS))
    ].copy()
    if not univ["session_id"].is_unique:
        raise ValueError("主证据体系 registry 子集 session_id 必须唯一")
    return univ


def load_main_evidence_minutes(
    minute_root: Path,
    registry: pd.DataFrame,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """读主证据体系分钟表（谓词下推 + registry 交叉验证）。

    Args:
        minute_root: session_response_1min 分区根目录。
        registry: e0_full_split_registry 表（含 sample_layer/role/split）。
        columns: 需要读取的列（默认全部）。

    Returns:
        主证据体系分钟表，含派生 minutes_from_end / cycle_month。
    """
    universe = main_evidence_universe(registry)
    universe_ids = set(universe["session_id"])

    dataset = ds.dataset(str(minute_root))
    predicate = (
        (ds.field("sample_layer") == MAIN_LAYER)
        & (ds.field("role") == MAIN_ROLE)
        & ds.field("split").isin(list(MAIN_SPLITS))
    )
    table = dataset.to_table(filter=predicate, columns=columns)
    df = table.to_pandas()

    df_ids = set(df["session_id"])
    missing = universe_ids - df_ids
    extra = df_ids - universe_ids
    if missing or extra:
        raise ValueError(
            "主证据体系分钟表与 registry 会话集合不一致："
            f"missing={len(missing)} extra={len(extra)}"
        )

    df["minutes_from_end"] = (
        (df["disconnect_time"] - df["timestamp_utc"]).dt.total_seconds() / 60.0
    )
    df["cycle_month"] = df["timestamp_utc"].astype(str).str[:7]
    return df


def split_df(df: pd.DataFrame, split: str) -> pd.DataFrame:
    """按 split 隔离分钟表（整条会话不跨 split）。"""
    sub = df[df["split"] == split]
    if sub.empty:
        raise ValueError(f"split={split} 无分钟数据")
    return sub
