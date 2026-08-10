"""P1 rate_diff 的 day-cluster bootstrap 95%CI（Phase 3 v1.0.2 §0 / §1.5 step 4）。

cluster 单位 = day（cycle 的日期），与协议"会话/日级 cluster bootstrap"一致；
不把 cycle 点当独立样本。rate_diff = rate_S2 - rate_S1，按 day 重采样，
每次聚合 S1/S2 的 (e1 事件, cycle) 计数再算率差。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_DAY_FMT = "%Y-%m-%d"


def _cycle_day(cycle: pd.Timestamp) -> str:
    return cycle.strftime(_DAY_FMT)


def cluster_bootstrap_rate_diff_ci(
    obs_states: pd.DataFrame,
    e1_cycles: set[tuple[str, pd.Timestamp]],
    seed: int,
    n_boot: int = 2000,
) -> tuple[float, float]:
    """按 day cluster 重采样 rate_diff 的 95%CI。

    obs_states 必须含 site/cycle/state 列。每次重采样以 day 为整体取回，
    rate_S1 = e1_cycles∩S1 / n_S1、rate_S2 = e1_cycles∩S2 / n_S2。
    若某次重采样 n_S1 或 n_S2 为 0，该样本 diff 记 NaN 并跳过（fail-closed
    不参与分位）；全部样本失效则 RuntimeError。
    """
    df = obs_states[["site", "cycle", "state"]].copy()
    df["_day"] = df["cycle"].map(_cycle_day).astype("string")
    s1 = df[df["state"] == "S1"]
    s2 = df[df["state"] == "S2"]
    # 预计算每个 day 的 e1 命中/cycle 数（S1/S2 各自）
    day_e1_s1: dict[str, int] = {}
    day_n_s1: dict[str, int] = {}
    day_e1_s2: dict[str, int] = {}
    day_n_s2: dict[str, int] = {}
    for d, g in s1.groupby("_day"):
        day = str(d)
        day_n_s1[day] = int(len(g))
        day_e1_s1[day] = int(
            sum(1 for k in zip(g["site"], g["cycle"], strict=False) if k in e1_cycles)
        )
    for d, g in s2.groupby("_day"):
        day = str(d)
        day_n_s2[day] = int(len(g))
        day_e1_s2[day] = int(
            sum(1 for k in zip(g["site"], g["cycle"], strict=False) if k in e1_cycles)
        )
    days = sorted(set(day_n_s1) | set(day_n_s2))
    if len(days) == 0:
        raise RuntimeError("P1 bootstrap 失败：无任何 day 含 S1/S2 cycle")
    rng = np.random.default_rng(seed)
    diffs: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(days), size=len(days))
        n1 = sum(day_n_s1.get(days[i], 0) for i in idx)
        n2 = sum(day_n_s2.get(days[i], 0) for i in idx)
        if n1 == 0 or n2 == 0:
            continue
        e1_1 = sum(day_e1_s1.get(days[i], 0) for i in idx)
        e1_2 = sum(day_e1_s2.get(days[i], 0) for i in idx)
        diffs.append(e1_2 / n2 - e1_1 / n1)
    if len(diffs) == 0:
        raise RuntimeError("P1 bootstrap 失败：所有重采样样本都缺 S1 或 S2 状态")
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return (float(lo), float(hi))
