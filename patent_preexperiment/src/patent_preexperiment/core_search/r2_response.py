"""R2 响应指标与 R2-P0-B0 存在性杀伤门。

核心方法学（CORE_SEARCH_MASTER_PLAN.md 通用规则）：
自然控制事件若用 t+h 的 actual 解释"设备持续响应"，必须同步审计 (t,t+h] 内控制输入轨迹。
本模块对 binding down 事件重建 t+1..t+5 的 pilot 轨迹，区分 pilot-stable 与非稳定事件，
在 pilot-stable 子集上评估下调"欠交付"异质性是否存在。

response_fraction(down): r_lag = (actual_before − actual_lag) / (actual_before − pilot_after)
retention_lag:           (actual_before − actual_lag) / (actual_before − actual_1min)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.r2_config import R2P0B0Config


def attach_pilot_trace(
    events: pd.DataFrame, session_lookup: pd.DataFrame, horizon_min: int = 5
) -> pd.DataFrame:
    """为 binding down 事件重建 t+1..t+horizon 的 pilot 轨迹并标注稳定区间。

    events: 含 event_id / session_id / timestamp / pilot_after_a。
    session_lookup: 含 session_id / timestamp_utc / pilot_a（已去重）。
    返回: 附加 pilot_{k} 列（k=1..horizon_min）。
    """
    base = events.copy()
    base["session_id"] = base["session_id"].astype(str)
    lookup = session_lookup[["session_id", "timestamp_utc", "pilot_a"]].copy()
    lookup["session_id"] = lookup["session_id"].astype(str)
    for k in range(1, horizon_min + 1):
        tmp = base[["session_id"]].copy()
        tmp["_t"] = base["timestamp"] + pd.Timedelta(minutes=k)
        m = tmp.merge(
            lookup,
            left_on=["session_id", "_t"],
            right_on=["session_id", "timestamp_utc"],
            how="left",
        )
        base[f"pilot_{k}"] = m["pilot_a"].to_numpy()
    return base


def max_pilot_deviation(trace: pd.DataFrame, horizon_min: int) -> pd.Series:
    """每个事件在 t+1..t+horizon 内 |pilot_k − pilot_after_a| 的最大值。"""
    after = trace["pilot_after_a"].to_numpy()
    cols = [f"pilot_{k}" for k in range(1, horizon_min + 1)]
    devs = [(trace[c] - after).abs() for c in cols]
    return cast(pd.Series, pd.concat(devs, axis=1).max(axis=1))


def compute_down_response_fraction(
    events: pd.DataFrame, lag_min: tuple[int, ...], clip: tuple[float, float]
) -> pd.DataFrame:
    """binding down 事件的 response_fraction（相对要求削减量）。

    r_lag = (actual_before − actual_lag) / (actual_before − pilot_after)，clip 到 [low, high]。
    """
    out = events.copy()
    ab = out["actual_before_kw"].to_numpy()
    pa = out["pilot_after_kw"].to_numpy()
    denom = pd.Series(ab - pa, index=out.index).replace(0.0, np.nan)
    for lag in lag_min:
        col = f"actual_{lag}min_kw"
        num = pd.Series(ab - out[col].to_numpy(), index=out.index)
        rf = (num / denom).clip(clip[0], clip[1])
        out[f"r_{lag}m"] = rf
    return out


def compute_retention(events: pd.DataFrame, lag_min: tuple[int, ...]) -> pd.DataFrame:
    """retention_lag = (actual_before − actual_lag) / (actual_before − actual_1min)。"""
    out = events.copy()
    ab = out["actual_before_kw"].to_numpy()
    a1 = out["actual_1min_kw"].to_numpy()
    denom = pd.Series(ab - a1, index=out.index).replace(0.0, np.nan)
    for lag in lag_min:
        col = f"actual_{lag}min_kw"
        num = pd.Series(ab - out[col].to_numpy(), index=out.index)
        out[f"retention_{lag}m"] = (num / denom).clip(0.0, 2.0)
    return out


def _summary(stable: pd.DataFrame, lag: int, ud_thr: float) -> dict[str, float]:
    col = f"r_{lag}m"
    s = stable[col].dropna()
    if s.empty:
        return {
            "n": 0.0, "median": np.nan, "p10": np.nan, "p25": np.nan,
            "p75": np.nan, "p90": np.nan, "iqr": np.nan, "under80": np.nan,
        }
    return {
        "n": float(s.shape[0]),
        "median": float(s.median()),
        "p10": float(s.quantile(0.10)),
        "p25": float(s.quantile(0.25)),
        "p75": float(s.quantile(0.75)),
        "p90": float(s.quantile(0.90)),
        "iqr": float(s.quantile(0.75) - s.quantile(0.25)),
        "under80": float((s < ud_thr).mean()),
    }


@dataclass(frozen=True)
class R2P0B0Verdict:
    verdict: str  # CLOSED / CONDITIONAL / OPEN
    reason: str
    primary_n: int
    primary_under80: float
    primary_p10: float
    primary_r1m_median: float
    primary_r1m_iqr: float
    sensitivity_n: int
    sensitivity_under80: float
    sensitivity_p10: float
    sensitivity_reversed: bool


def evaluate_r2_p0b0_gate(
    primary: pd.DataFrame, sensitivity: pd.DataFrame, cfg: R2P0B0Config
) -> R2P0B0Verdict:
    """R2-P0-B0 三区门判定（优先级 CLOSED → OPEN → CONDITIONAL）。

    CLOSED      : under80 ≤ closed_under80_max AND p10 ≥ closed_p10_min
    OPEN        : under80 ≥ open_under80_min OR p10 < open_p10_max
    CONDITIONAL : 其余（灰区，主要是 under80 低但 p10 ∈ [cond_p10_low, cond_p10_high)）
    敏感性 <2A 不得方向性反转（CLOSED 时 sensitivity 也必须满足 CLOSED 阈值）。
    """
    g = cfg.gate
    ud_thr = g.under_delivery_threshold
    p = _summary(primary, 1, ud_thr)
    s = _summary(sensitivity, 1, ud_thr)
    under80, p10 = p["under80"], p["p10"]

    closed = (not np.isnan(under80) and under80 <= g.closed_under80_max) and (
        not np.isnan(p10) and p10 >= g.closed_p10_min
    )
    open_ = (not np.isnan(under80) and under80 >= g.open_under80_min) or (
        not np.isnan(p10) and p10 < g.open_p10_max
    )

    sensitivity_reversed = (
        g.sensitivity_no_reversal
        and closed
        and not (
            (not np.isnan(s["under80"]) and s["under80"] <= g.closed_under80_max)
            and (not np.isnan(s["p10"]) and s["p10"] >= g.closed_p10_min)
        )
    )

    if closed and not sensitivity_reversed:
        verdict = "CLOSED"
        reason = (
            f"pilot-stable(<{cfg.primary_max_dev_a:.0f}A) 下欠交付几乎不存在："
            f"under80={under80:.3f}≤{g.closed_under80_max} 且 p10={p10:.3f}≥{g.closed_p10_min}；"
            f"<2A 敏感性无方向性反转"
        )
    elif open_:
        verdict = "OPEN"
        reason = (
            f"存在大量欠交付：under80={under80:.3f} 或 p10={p10:.3f}；"
            f"需进一步验证欠交付是否有在线可观测状态的可重复结构"
        )
    else:
        verdict = "CONDITIONAL"
        reason = (
            f"欠交付处于灰区：under80={under80:.3f}（{g.cond_under80_low}~{g.cond_under80_high}），"
            f"p10={p10:.3f}；仅诊断结构，不启动完整 R2-B"
        )

    return R2P0B0Verdict(
        verdict=verdict,
        reason=reason,
        primary_n=int(p["n"]),
        primary_under80=float(under80) if not np.isnan(under80) else 0.0,
        primary_p10=float(p10) if not np.isnan(p10) else 0.0,
        primary_r1m_median=float(p["median"]) if not np.isnan(p["median"]) else 0.0,
        primary_r1m_iqr=float(p["iqr"]) if not np.isnan(p["iqr"]) else 0.0,
        sensitivity_n=int(s["n"]),
        sensitivity_under80=float(s["under80"]) if not np.isnan(s["under80"]) else 0.0,
        sensitivity_p10=float(s["p10"]) if not np.isnan(s["p10"]) else 0.0,
        sensitivity_reversed=bool(sensitivity_reversed),
    )
