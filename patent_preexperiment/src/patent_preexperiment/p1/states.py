"""P1 三态映射（Phase 3 v1.0.2 §1.5 step 3）。

- train_q50 只在 office001 **train** 上拟合一次（v1.0.1，quartile 边不依赖 duplicate-edge）；
- S1/S2 主切分直接用 raw median：S1 = recent_var ≤ train_q50，S2 = recent_var > train_q50；
- S3 insufficient = recent_var 不可评估（min_recent_samples=2 未满足 / run 内历史不足）；
- 次指标 quartile direction 用 A5 duplicate-edge rule（Q1=(-inf,q25]，Q4=(q75,+inf)；
  不足 2 个 effective bins → insufficient_bin_resolution，不得重找 cutpoint）。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

S1 = "S1"
S2 = "S2"
S3 = "S3"


def fit_train_q50(obs_train: pd.DataFrame) -> float:
    """office001 train 内可评估 cycle 的 recent_var 中位数（q50）。"""
    series = obs_train["median_recent_actual_var"].dropna()
    if len(series) == 0:
        raise ValueError("P1 train q50 拟合失败：train 无任何可评估 cycle")
    return float(series.median())


def assign_states(obs: pd.DataFrame, train_q50: float) -> pd.DataFrame:
    """把 cycle 级 recent_var 映射为 S1/S2/S3（v1.0.1 冻结）。

    S3 = recent_var 不可评估（NaN，即 min_recent_samples 未满足）。S1/S2 用 raw
    median 切分，不依赖任何 quartile label。
    """
    out = obs.copy()
    v = out["median_recent_actual_var"]
    out["state"] = np.select(
        [v.isna(), v <= train_q50],
        [S3, S1],
        default=S2,
    )
    return out


def fit_quartile_edges(
    obs_train: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A5 duplicate-edge rule：Q1=(-inf,q25] / Q4=(q75,+inf)，不足 2 bins 标记。

    返回 (edges_result, prov)。edges_result 用于对任何 split apply；
    prov 供 manifest 记录 fit provenance（与 A5 `_fit_quartile_edges` 同规则）。
    """
    vp: dict[str, Any] = {
        "n_nonnull": 0,
        "q25": None,
        "q50": None,
        "q75": None,
        "edges": None,
        "labels": None,
        "effective_bins": 0,
        "insufficient_bin_resolution": True,
        "reason": "",
    }
    series = obs_train["median_recent_actual_var"].dropna()
    vp["n_nonnull"] = int(len(series))
    if len(series) == 0:
        vp["reason"] = "no_observable_cycles"
        return dict(vp), dict(vp)
    q25 = float(series.quantile(0.25))
    q50 = float(series.quantile(0.50))
    q75 = float(series.quantile(0.75))
    vp.update(q25=q25, q50=q50, q75=q75)
    merged: list[float] = []
    for e in [q25, q50, q75]:
        if merged and abs(e - merged[-1]) < 1e-12:
            continue
        merged.append(e)
    edges = [-np.inf] + merged + [np.inf]
    labels = [f"Q{i + 1}" for i in range(len(merged) + 1)]
    cuts = pd.cut(
        series, bins=edges, labels=labels, right=True, include_lowest=True
    ).dropna()
    n_nonempty = int(cuts.nunique())
    vp.update(edges=edges, labels=labels, effective_bins=n_nonempty)
    if n_nonempty < 2:
        vp["reason"] = "duplicate_edge_insufficient_bins"
        return dict(vp), dict(vp)
    vp["insufficient_bin_resolution"] = False
    vp["reason"] = ""
    edges_result = {
        "edges": edges,
        "labels": labels,
        "insufficient_bin_resolution": False,
        "q25": q25,
        "q50": q50,
        "q75": q75,
        "n_train_nonnull": int(len(series)),
        "effective_bins": n_nonempty,
    }
    return edges_result, dict(vp)


def apply_quartile_bin(
    obs: pd.DataFrame,
    edges_result: dict[str, Any],
) -> pd.Series:
    """对任意 split apply 冻结 quartile edges（val/test 只 apply，不重拟合）。"""
    if edges_result.get("insufficient_bin_resolution"):
        return pd.Series([pd.NA] * len(obs), index=obs.index, dtype="category")
    return pd.cut(
        obs["median_recent_actual_var"],
        bins=edges_result["edges"],
        labels=edges_result["labels"],
        right=True,
        include_lowest=True,
    )
