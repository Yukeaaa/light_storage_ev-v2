"""P2.1A 点估计指标（v1.3 §4.4）——gain / Δ / coverage / latency。

在 eligible risk set + 各 baseline 的 trigger（每 segment 第一个）上计算：
  gain(m)   = P(Y=1 | trigger=m)
  Δ(B1)     = gain(B0) − gain(B1)
  Δ(B3)     = gain(B0) − gain(B3)
  Δ(B2)     = gain(B0) − max[gain(B2a), gain(B2b)]     ← functional，bootstrap 内重算
  coverage(m)= n_trigger(m) / n_eligible_segments
  latency(m) = median(trigger cycle index within segment)

cluster bootstrap（percentile / N=2000 / resample unit=session）在 bootstrap.py，
Δ 的 CI 在 gate.py 判定。本模块只做确定性的点估计 + 触发表。

**Step-0 隔离**：`build_trigger_counts` 不读 Y（只给 session/segment/method 计数），
Step-0 data sufficiency 只能走它；`build_trigger_table` 才合并 Y（formal exposure）。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.phase3_p2_1.b3_map import _b3_selected_cycle_rows
from patent_preexperiment.phase3_p2_1.risk_set import first_trigger_per_segment
from patent_preexperiment.phase3_p2_1.triggers import (
    ALL_BASELINES,
    B0,
    B1,
    B2A,
    B2B,
    B3,
)

_TRIGGER_TABLE_COLS = ["session_id", "segment_id", "method", "cycle_index"]


def build_trigger_counts(
    eligible: pd.DataFrame,
    masks: dict[str, pd.Series],
    b3_map: pd.DataFrame,
) -> pd.DataFrame:
    """Step-0 安全：每 baseline 每 segment 的第一个 trigger（不含 Y）。

    列：session_id, segment_id, method, cycle_index。每 (segment_id, method) 至多一行。
    """
    if eligible.empty:
        return pd.DataFrame(columns=_TRIGGER_TABLE_COLS + ["timestamp_utc"])

    frames: list[pd.DataFrame] = []
    for method in ALL_BASELINES:
        if method in masks:
            trig = first_trigger_per_segment(eligible, masks[method])
        elif method == B3:
            trig = _b3_selected_cycle_rows(eligible, b3_map)
        else:
            raise ValueError(f"未知 baseline: {method!r}")
        if trig.empty:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "session_id": trig["session_id"].to_numpy(),
                    "segment_id": trig["segment_id"].to_numpy(),
                    "method": method,
                    "cycle_index": trig["cycle_index"].to_numpy(),
                    "timestamp_utc": trig["timestamp_utc"].to_numpy(),
                }
            )
        )
    if not frames:
        return pd.DataFrame(columns=_TRIGGER_TABLE_COLS + ["timestamp_utc"])
    return pd.concat(frames, ignore_index=True)


def build_trigger_table(
    trigger_counts: pd.DataFrame,
    eligible: pd.DataFrame,
    y: pd.Series,
) -> pd.DataFrame:
    """把 Y 合并进 trigger 表（formal exposure 专用；Step-0 禁止调用）。

    Y 按 (segment_id, timestamp_utc) 映射——trigger 行是 eligible 的特定 cycle，
    Y 是该 cycle 的 outcome；映射不到或含 NaN → fail-closed。返回 bool 列 y。
    """
    if trigger_counts.empty:
        return pd.DataFrame(columns=_TRIGGER_TABLE_COLS + ["y"])
    ymap = pd.DataFrame(
        {
            "segment_id": eligible["segment_id"].to_numpy(),
            "timestamp_utc": eligible["timestamp_utc"].to_numpy(),
            "y": y.to_numpy(dtype=float),  # 保留 NaN 用于检测
        }
    )
    merged = trigger_counts.merge(ymap, on=["segment_id", "timestamp_utc"], how="left")
    if merged["y"].isna().any():
        raise RuntimeError(
            "P2.1A fail-closed：部分 trigger 行映射不到 Y（eligible/Y 对齐损坏或 Y 未定义）"
        )
    merged["y"] = merged["y"].astype(bool)
    return merged[["session_id", "segment_id", "method", "cycle_index", "y"]]


def point_metrics(
    trigger_table: pd.DataFrame,
    n_eligible_segments: int,
) -> dict[str, Any]:
    """计算全样本点估计：gain / Δ / coverage / latency。n_eligible_segments = 段总数。"""
    gains: dict[str, float] = {}
    coverage: dict[str, float] = {}
    latency: dict[str, float] = {}
    n_triggers: dict[str, int] = {}
    for method in ALL_BASELINES:
        sub = trigger_table[trigger_table["method"] == method]
        n = len(sub)
        n_triggers[method] = n
        gains[method] = float(sub["y"].mean()) if n > 0 else float("nan")
        coverage[method] = (
            n / n_eligible_segments if n_eligible_segments > 0 else float("nan")
        )
        latency[method] = (
            float(sub["cycle_index"].median()) if n > 0 else float("nan")
        )

    g = gains
    delta_b1 = _safe_delta(g[B0], g[B1])
    delta_b3 = _safe_delta(g[B0], g[B3])
    best_rolling = _nanmax(g[B2A], g[B2B])
    delta_b2 = _safe_delta(g[B0], best_rolling)

    return {
        "gains": gains,
        "delta_b1": delta_b1,
        "delta_b3": delta_b3,
        "delta_b2": delta_b2,
        "best_rolling": best_rolling,
        "coverage": coverage,
        "latency": latency,
        "n_triggers": n_triggers,
        "n_eligible_segments": n_eligible_segments,
    }


def _safe_delta(a: float, b: float) -> float:
    return float(a - b) if np.isfinite(a) and np.isfinite(b) else float("nan")


def _nanmax(a: float, b: float) -> float:
    return float(max(a, b)) if np.isfinite(a) and np.isfinite(b) else float("nan")
