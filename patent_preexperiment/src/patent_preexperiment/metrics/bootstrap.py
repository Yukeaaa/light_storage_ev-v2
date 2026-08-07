"""K1.2.1-P0-1：会话 cluster bootstrap（事件标记率差值与比例）。

设计约束：点估计与 bootstrap CI 必须使用**同一母体**（同一会话集合）。
E1 点估计 = 事件会话数 / core_denom（有核心运行窗口的会话）；因此 bootstrap
也必须只在该 core_sessions 上构造布尔标记并重采样，不得混入无核心窗口的会话。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.response.done import PHASE_CORE


def bootstrap_session_diff_ci(
    real_has: np.ndarray,
    perm_has: np.ndarray,
    seed: int,
    n_boot: int,
) -> tuple[float, float]:
    """真实事件标记 - 置换事件标记 的会话 cluster bootstrap 95%CI。

    Args:
        real_has: (n_sessions,) 布尔，真实事件会话标记。
        perm_has: (n_seeds, n_sessions) 布尔，各置换种子的事件会话标记。
        seed: bootstrap 重采样种子。
        n_boot: 重采样次数。

    Returns:
        (lo, hi) 95% 分位。real_has 与 perm_has 必须定义在同一会话母体上，
        调用方负责把两者限制到 core_sessions（与点估计分母一致）。
    """
    n = len(real_has)
    if n == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    diffs: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        real_b = float(real_has[idx].mean())
        perm_b = float(perm_has[:, idx].mean(axis=1).mean())
        diffs.append(real_b - perm_b)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return (float(lo), float(hi))


def core_run_session_ids(labeled: pd.DataFrame) -> np.ndarray:
    """有核心运行窗口的会话集合（core_denom 等价定义）。

    与点估计分母严格一致：phase==core_run_segment 且充电中且 pilot 可用。
    """
    return (
        labeled.loc[
            (labeled["phase"] == PHASE_CORE)
            & labeled["charging_active"]
            & labeled["pilot_available"],
            "session_id",
        ]
        .drop_duplicates()
        .to_numpy()
    )


def bootstrap_proportion_ci(
    numerator: np.ndarray, denominator: np.ndarray, seed: int, n_boot: int,
) -> tuple[float, float]:
    """配对比例（消除率等）的日 cluster bootstrap 95%CI。"""
    rng = np.random.default_rng(seed)
    n = len(numerator)
    if n == 0:
        return (0.0, 0.0)
    ratios: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        r = float(numerator[idx].sum() / max(float(denominator[idx].sum()), 1e-9))
        ratios.append(r)
    lo, hi = np.percentile(ratios, [2.5, 97.5])
    return (float(lo), float(hi))
