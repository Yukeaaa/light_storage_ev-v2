"""P2 回放管线：E0 分钟表加载（Arrow 层隔离）+ per-cycle 计算 + replay 变换。

- 加载纪律（Review 56 同源）：session membership 直接进 Arrow query predicate，
  加载后 fail-closed：loaded ids ⊆ 允许集；test 行在任何计算前被隔离。
- replay 变换（mode-mechanism，协议明示非真实站点分布统计）：
  - natural          caltech measured_pilot 原样（M2/M4 分支）；
  - mask_pilot       pilot 置不可用 → M3/M4（current-only 分支）；
  - truncate_history 每 run 历史截断到 <min_history_samples → M4 conservative fallback；
  - inject_capability 注入固定标量 injection_value_kw → M1 capability-rich 分支。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from patent_preexperiment.phase3_p2.actions import build_action_frame, seed_map_for
from patent_preexperiment.phase3_p2.boundary import build_boundary_frame
from patent_preexperiment.phase3_p2.d1 import assert_exhaustive, build_info_mode_table
from patent_preexperiment.phase3_p2.schema import M1, M3, SchemaConfig
from patent_preexperiment.phase3_p2.state_machine import build_state_frame

_MINUTE_COLUMNS = [
    "session_id",
    "station_id",
    "site",
    "field_mode",
    "match_status",
    "sample_layer",
    "split",
    "timestamp_utc",
    "actual_power_kw",
    "pilot_available",
    "pilot_power_kw",
    "severe_gap_before",
    "gap_before_min",
    "connected_elapsed_min",
]

_CYCLE_KEEP = [
    "session_id",
    "station_id",
    "timestamp_utc",
    "actual_power_kw",
    "pilot_available",
    "pilot_power_kw",
    "severe_gap_before",
    "gap_before_min",
    "connected_elapsed_min",
]


@dataclass(frozen=True)
class ReplayTransform:
    name: str
    mask_pilot: bool = False
    inject_capability: bool = False
    history_limit_per_run: int | None = None


def load_pool_minutes(
    minute_root: Path,
    registry: pd.DataFrame,
    *,
    site: str,
    field_mode: str,
    split: str,
) -> pd.DataFrame:
    """按 registry 会话面加载分钟表；test 隔离在 Arrow predicate 层（Review 56 纪律）。"""
    allowed = set(
        registry[
            (registry["site_canonical"] == site)
            & (registry["match_status"] == "matched")
            & (registry["field_mode"] == field_mode)
            & (registry["split"] == split)
        ]["session_id"]
    )
    if not allowed:
        raise ValueError(f"P2 加载失败：{site}/{field_mode}/{split} 会话集为空")
    pred = (
        (ds.field("site") == site)
        & (ds.field("match_status") == "matched")
        & (ds.field("field_mode") == field_mode)
        & ds.field("session_id").isin(sorted(allowed))
    )
    table = ds.dataset(str(minute_root)).to_table(filter=pred, columns=_MINUTE_COLUMNS)
    df = cast(pd.DataFrame, table.to_pandas())
    loaded = set(df["session_id"])
    if not (loaded <= allowed):
        raise RuntimeError(
            f"P2 fail-closed：{site}/{field_mode}/{split} 加载会话超出允许面："
            f"n={len(loaded - allowed)}"
        )
    if df.empty:
        raise ValueError(f"P2 加载失败：{site}/{field_mode}/{split} 分钟表为空")
    return df


def build_cycle_frame(
    pool: pd.DataFrame,
    scfg: SchemaConfig,
    seed_map: dict[str, int],
    transform: ReplayTransform,
) -> pd.DataFrame:
    """池级 cycle 计算：D1 查表 → 边界 → 状态机 → 动作约束输出。

    输入 `pool` 必须来自 `load_pool_minutes`（含所需列）。向量化，无逐行 Python 循环。
    """
    assert_exhaustive(scfg)
    out = build_boundary_frame(
        pool,
        scfg,
        history_limit_per_run=transform.history_limit_per_run,
    )

    info_pilot = out["pilot_available"].fillna(False) & out["pilot_power_kw"].notna()
    if transform.mask_pilot:
        info_pilot = pd.Series(False, index=out.index)
    info_actual = out["actual_power_kw"].notna()
    info_history = out["history_sufficient"]
    capability = bool(transform.inject_capability)

    _, mode_arr, reason_arr = build_info_mode_table(scfg)
    codes = (
        np.where(capability, 8, 0)
        + np.where(info_pilot.to_numpy(), 4, 0)
        + np.where(info_actual.to_numpy(), 2, 0)
        + np.where(info_history.to_numpy(), 1, 0)
    ).astype(np.int64)
    out["info_mode"] = np.asarray(mode_arr, dtype=object)[codes]
    out["reason_code"] = np.asarray(reason_arr, dtype=object)[codes]
    out["boundary_mode"] = [scfg.layer2_boundary_modes[m] for m in out["info_mode"]]

    bv = pd.Series(np.nan, index=out.index, dtype="float64")
    bv[out["info_mode"] == M1] = scfg.injection_value_kw
    bv[out["info_mode"] == M3] = out["protective_bound"]
    out["boundary_value"] = bv

    out = build_state_frame(out, scfg)
    out = build_action_frame(out, scfg, seed_map)
    extra = [
        "run_id",
        "run_start",
        "cycle_index",
        "history_count",
        "history_sufficient",
        "protective_bound",
        "boundary_value",
        "info_mode",
        "reason_code",
        "boundary_mode",
        "application_state",
        "recovery_event",
        "seed_byte",
        "budget",
        "requested_delta",
        "L",
        "U",
        "final_delta",
        "disposition",
        "_clip_check",
        "_has_bound",
        "final_cf_locked",
        "final_cf_protective",
        "final_cf_normal",
        "probe_seed",
        "budget_seed",
    ]
    return out[_CYCLE_KEEP + [c for c in extra if c not in _CYCLE_KEEP]]


def seeds_for_pool(pool: pd.DataFrame) -> dict[str, int]:
    return seed_map_for(pool["session_id"].unique().tolist())


def process_pool(
    pool: pd.DataFrame,
    scfg: SchemaConfig,
    seed_map: dict[str, int],
    transform: ReplayTransform,
    *,
    chunk_sessions: int = 800,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """分块处理一个池，返回 (池级指标 dict, 全部 trace 记录 df)。

    按 session 整块处理（trace 的 after-condition 不跨块），累积式内存友好。
    """
    from patent_preexperiment.phase3_p2.metrics import PoolAgg
    from patent_preexperiment.phase3_p2.recovery import trace_records

    session_ids = sorted(pool["session_id"].unique().tolist())
    agg = PoolAgg()
    traces: list[pd.DataFrame] = []
    for i in range(0, len(session_ids), chunk_sessions):
        chunk_ids = session_ids[i : i + chunk_sessions]
        chunk = pool[pool["session_id"].isin(chunk_ids)]
        cycle = build_cycle_frame(chunk, scfg, seed_map, transform)
        agg.add(cycle)
        tr = trace_records(cycle, scfg)
        if not tr.empty:
            agg.add_traces(tr)
            traces.append(tr)
    summary = agg.finalize()
    if traces:
        trace_df = pd.concat(traces, ignore_index=True)
    else:
        trace_df = pd.DataFrame()
    return summary, trace_df

