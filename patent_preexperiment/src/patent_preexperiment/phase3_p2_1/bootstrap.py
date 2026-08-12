"""P2.1A cluster bootstrap（v1.3 §4.4）——session 级重采样 + functional Δ。

- resample unit：session_id（cluster）；N=2000；alpha=0.05 → percentile [2.5%, 97.5%]。
- 每 replicate：重采样 sessions → 在触发表上按权重重算 gain(m) →
  Δ(B1)=gain(B0)−gain(B1)、Δ(B3)=gain(B0)−gain(B3)、
  Δ(B2)=gain(B0)−max[gain(B2a),gain(B2b)]（**functional：max 在 replicate 内取**）。
- B3 trigger map 固定：只按 session 权重查表，不重新随机（C2）。
- 种子冻结：FROZEN.bootstrap_seed（"20260813_B"），字符串稳定映射为 int。
- 确定性回放：同输入 + 同种子 → 同一分布参数。
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.phase3_p2_1.frozen import FROZEN
from patent_preexperiment.phase3_p2_1.triggers import B0, B1, B2A, B2B, B3


def seed_from_string(seed: str) -> int:
    """稳定字符串种子 → int（md5 前 8 位 hex；禁 Python built-in hash）。"""
    return int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:8], 16)


def _gain_from_groups(
    groups: pd.DataFrame,
    weights: pd.Series,
    method: str,
) -> float:
    """在给定 session 权重（multinomial 抽取次数）下计算 gain(m)。

    gain(m) = Σ_c w_c·Σ_{s∈c} y / Σ_c w_c·n_c（session 被抽 w_c 次 → 其 segment 计入 w_c 次）。
    """
    sub = groups[groups["method"] == method]
    if sub.empty:
        return float("nan")
    w = sub["session_id"].map(weights).fillna(0.0).to_numpy(dtype=float)
    sy = sub["y_sum"].to_numpy(dtype=float)
    n = sub["n_rows"].to_numpy(dtype=float)
    denom = float(np.dot(w, n))
    if denom <= 0.0:
        return float("nan")
    return float(np.dot(w, sy) / denom)


def _agg_per_session_method(trigger_table: pd.DataFrame) -> pd.DataFrame:
    """(session_id, method) → n_rows / y_sum（一次性聚合，bootstrap 只查 weights）。"""
    g = (
        trigger_table.groupby(["session_id", "method"], as_index=False)
        .agg(n_rows=("y", "size"), y_sum=("y", "sum"))
    )
    return g


def bootstrap_delta_distributions(
    trigger_table: pd.DataFrame,
    eligible_sessions: np.ndarray,
    seed: int | None = None,
    n_boot: int | None = None,
) -> dict[str, Any]:
    """session cluster bootstrap，返回三个 Δ 的分布（array）与元数据。

    Args:
        trigger_table: metrics.build_trigger_table 输出（含 y）。
        eligible_sessions: **全部 eligible-risk-set session IDs**（np.ndarray）。
            重采样 universe 必须是全 eligible session 集合，不是"至少有一个 baseline
            trigger 的 session"——后者会条件化掉零-trigger session，改变 cluster 方差。
        seed: 重采样种子（默认 FROZEN.bootstrap_seed 稳定映射）。
        n_boot: 重采样次数（默认 FROZEN.bootstrap_n）。

    Returns:
        {
          "delta_b1": ndarray(n_boot,),   # 含 NaN（该 replicate 某方法 0 trigger）
          "delta_b3": ndarray(n_boot,),
          "delta_b2": ndarray(n_boot,),
          "n_boot": n_boot,
          "n_invalid_delta_b1": int,      # Δ 未定义 replicate 数（方法 0 trigger）
          "n_invalid_delta_b3": int,
          "n_invalid_delta_b2": int,
          "n_sessions": int,              # universe 大小（= eligible_sessions）
          "seed": int,
        }
    """
    if seed is None:
        seed = seed_from_string(FROZEN.bootstrap_seed)
    if n_boot is None:
        n_boot = FROZEN.bootstrap_n

    groups = _agg_per_session_method(trigger_table)
    sessions = np.asarray(eligible_sessions)
    if sessions.size == 0:
        raise ValueError("P2.1A bootstrap：eligible session universe 为空")

    rng = np.random.default_rng(seed)
    delta_b1 = np.full(n_boot, np.nan)
    delta_b3 = np.full(n_boot, np.nan)
    delta_b2 = np.full(n_boot, np.nan)
    n_invalid = {B1: 0, B3: 0, "B2": 0}

    for i in range(n_boot):
        drawn = rng.choice(sessions, size=sessions.size, replace=True)
        counts = pd.Series(drawn).value_counts()
        g0 = _gain_from_groups(groups, counts, B0)
        if not np.isfinite(g0):
            # B0 无 trigger：整个 replicate 全部 Δ 未定义（fail-closed 计入各 Δ）
            for k in (B1, B3, "B2"):
                n_invalid[k] += 1
            continue
        g1 = _gain_from_groups(groups, counts, B1)
        g3 = _gain_from_groups(groups, counts, B3)
        g2a = _gain_from_groups(groups, counts, B2A)
        g2b = _gain_from_groups(groups, counts, B2B)
        if np.isfinite(g1):
            delta_b1[i] = g0 - g1
        else:
            n_invalid[B1] += 1
        if np.isfinite(g3):
            delta_b3[i] = g0 - g3
        else:
            n_invalid[B3] += 1
        # Δ(B2) functional：B2a/B2b **都** finite 才取 max；任一 NaN → Δ 未定义
        if np.isfinite(g2a) and np.isfinite(g2b):
            delta_b2[i] = g0 - max(g2a, g2b)
        else:
            n_invalid["B2"] += 1

    return {
        "delta_b1": delta_b1,
        "delta_b3": delta_b3,
        "delta_b2": delta_b2,
        "n_boot": n_boot,
        "n_invalid_delta_b1": int(n_invalid[B1]),
        "n_invalid_delta_b3": int(n_invalid[B3]),
        "n_invalid_delta_b2": int(n_invalid["B2"]),
        "n_sessions": int(sessions.size),
        "seed": seed,
    }


def percentile_ci(
    values: np.ndarray,
    ci_low_pct: float | None = None,
    ci_high_pct: float | None = None,
) -> tuple[float, float]:
    """percentile CI [ci_low_pct, ci_high_pct]；NaN 剔除；全 NaN → (nan, nan)。"""
    if ci_low_pct is None:
        ci_low_pct = FROZEN.bootstrap_ci_low_pct
    if ci_high_pct is None:
        ci_high_pct = FROZEN.bootstrap_ci_high_pct
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return (float("nan"), float("nan"))
    lo, hi = np.percentile(finite, [ci_low_pct, ci_high_pct])
    return (float(lo), float(hi))
