"""P0-B：EV 群真实短时柔性规模（review §六；CORE-PATENT SEARCH 第二道零成本数据门）。

目的：**EV 是否真的足以改变 BESS 尺寸/运行。**

不追求"神奇真实能力"，建立多档柔性口径（F0 乐观 / F1 历史简单 / F2 已验证 M2 / F3 conservative）。
第一版只用 ACN 真实 5min 控制池（`datasets/pool_state_5min/pool_state_5min.parquet`），
15min 池当前缺失，仅标注不作门判集。

多档口径（本版可计算）：
- F0 乐观上调：pilot headroom = max(P_pilot_total − P_actual_total, 0)
- F3 conservative 上调：0（没有足够证据不允许增加）
- 下调：P_actual × r_down（r_down 来自 P0-A binding down 的 5min response_fraction median，
  不用 pilot headroom 假设 actual 必降）

量纲比较（最重要）：EV 总功率 / 柔性功率 / 柔性占 EV 功率比例，与 100–200kW BESS 同量级？
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.config import P0BConfig

# --- 并发分档（诊断维度，非 gate 阈值）---
_CONCURRENCY_EDGES = (1, 5, 10, 20)  # 在充会话数分档


@dataclass(frozen=True)
class P0BGateVerdict:
    """P0-B 量纲门判定结果。"""

    verdict: str  # GO / NO_GO
    reason: str
    r_down_calibration: float
    ev_peak_kw: float
    ev_p95_kw: float
    ev_median_kw: float
    flex_up_f0_peak_kw: float
    flex_down_reliable_peak_kw: float
    flex_down_reliable_p95_kw: float
    flex_down_reliable_median_kw: float
    flex_to_ev_peak_ratio: float


def compute_pool_flexibility(pool: pd.DataFrame, r_down: float) -> pd.DataFrame:
    """每控制周期（5min）计算 EV 群柔性各档口径。

    入列（pool_state_5min）：actual_power_kw_total / pilot_upper_kw_total /
    pilot_coverage / n_active / n_charging / n_matched / site / garage / timestamp_utc。
    """
    out = pool.copy()
    out["hour"] = out["timestamp_utc"].dt.hour
    out["month"] = out["timestamp_utc"].dt.strftime("%Y-%m")
    out["p_ev_actual_kw"] = out["actual_power_kw_total"].astype(float)
    # F0 乐观上调：pilot headroom（pilot 缺失聚合为 0 → headroom=0，语义=无 pilot 支撑）
    out["flex_up_f0_kw"] = (
        out["pilot_upper_kw_total"] - out["actual_power_kw_total"]
    ).clip(lower=0.0)
    # F3 conservative 上调：没有足够证据不允许增加
    out["flex_up_f3_kw"] = 0.0
    # 下调：F0 全量可削减（actual），F3 校准（actual × r_down）
    out["flex_down_f0_kw"] = out["actual_power_kw_total"].astype(float)
    out["flex_down_reliable_kw"] = out["actual_power_kw_total"].astype(float) * r_down
    return out


def summarize_flex_scale(flex: pd.DataFrame) -> pd.DataFrame:
    """按 site（=garage，独立控制池）汇总量纲指标。"""
    if flex.empty:
        return pd.DataFrame(
            columns=[
                "site", "garage", "periods", "pilot_coverage_mean",
                "ev_peak_kw", "ev_p95_kw", "ev_p50_kw",
                "flex_up_f0_peak_kw", "flex_up_f0_p95_kw", "flex_up_f0_p50_kw",
                "flex_down_reliable_peak_kw", "flex_down_reliable_p95_kw",
                "flex_down_reliable_p50_kw", "flex_to_ev_peak_ratio",
            ]
        )
    rows: list[dict[str, object]] = []
    for site, g in flex.groupby("site", observed=True):
        ev = g["p_ev_actual_kw"].astype(float)
        up = g["flex_up_f0_kw"].astype(float)
        dn = g["flex_down_reliable_kw"].astype(float)
        ev_peak = float(ev.max())
        rows.append({
            "site": site,
            "garage": str(g["garage"].iloc[0]),
            "periods": int(g.shape[0]),
            "pilot_coverage_mean": float(g["pilot_coverage"].mean()),
            "ev_peak_kw": ev_peak,
            "ev_p95_kw": float(ev.quantile(0.95)),
            "ev_p50_kw": float(ev.quantile(0.50)),
            "flex_up_f0_peak_kw": float(up.max()),
            "flex_up_f0_p95_kw": float(up.quantile(0.95)),
            "flex_up_f0_p50_kw": float(up.quantile(0.50)),
            "flex_down_reliable_peak_kw": float(dn.max()),
            "flex_down_reliable_p95_kw": float(dn.quantile(0.95)),
            "flex_down_reliable_p50_kw": float(dn.quantile(0.50)),
            "flex_to_ev_peak_ratio": (
                float(dn.max() / ev_peak) if ev_peak > 0 else np.nan
            ),
        })
    return pd.DataFrame(rows)


def summarize_by_hour(flex: pd.DataFrame) -> pd.DataFrame:
    """按小时统计 EV 总功率与可靠下调柔性（p50/p95/max）。"""
    if flex.empty:
        return pd.DataFrame(columns=["hour", "periods", "ev_p95_kw", "down_reliable_p95_kw"])
    rows: list[dict[str, object]] = []
    hours = sorted(flex["hour"].dropna().unique().tolist())
    for hour in hours:
        g = flex[flex["hour"] == hour]
        ev = g["p_ev_actual_kw"].astype(float)
        dn = g["flex_down_reliable_kw"].astype(float)
        rows.append({
            "hour": int(hour),
            "periods": int(g.shape[0]),
            "ev_p95_kw": float(ev.quantile(0.95)),
            "down_reliable_p95_kw": float(dn.quantile(0.95)),
        })
    return pd.DataFrame(rows)


def _concurrency_bin(n: float) -> str:
    if n <= _CONCURRENCY_EDGES[0]:
        return "1"
    if n <= _CONCURRENCY_EDGES[1]:
        return "2-5"
    if n <= _CONCURRENCY_EDGES[2]:
        return "6-10"
    if n <= _CONCURRENCY_EDGES[3]:
        return "11-20"
    return ">20"


def summarize_by_concurrency(flex: pd.DataFrame) -> pd.DataFrame:
    """按并发活动会话数分档统计 EV 总功率与可靠下调柔性。

    注：gold benchmark 的 `n_charging` 全为 0，改用 `n_active`（活动会话数，
    与 `n_matched` 一致）作为并发口径。
    """
    if flex.empty:
        return pd.DataFrame(
            columns=["concurrency_bin", "periods", "ev_p95_kw", "down_reliable_p95_kw"]
        )
    work = flex.copy()
    work["concurrency_bin"] = work["n_active"].astype(float).map(_concurrency_bin)
    order = ["1", "2-5", "6-10", "11-20", ">20"]
    rows: list[dict[str, object]] = []
    for b in order:
        g = work[work["concurrency_bin"] == b]
        if g.empty:
            continue
        ev = g["p_ev_actual_kw"].astype(float)
        dn = g["flex_down_reliable_kw"].astype(float)
        rows.append({
            "concurrency_bin": b,
            "periods": int(g.shape[0]),
            "ev_p95_kw": float(ev.quantile(0.95)),
            "down_reliable_p95_kw": float(dn.quantile(0.95)),
        })
    return pd.DataFrame(rows)


def evaluate_p0b_gate(
    summary: pd.DataFrame, cfg: P0BConfig, r_down: float
) -> P0BGateVerdict:
    """P0-B 量纲门判定（取各独立控制池中的最大可靠下调柔性峰值与 BESS 量级比较）。"""
    g = cfg.gate
    if summary.empty:
        return P0BGateVerdict(
            verdict="NO_GO", reason="无可用控制池数据", r_down_calibration=float(r_down),
            ev_peak_kw=0.0, ev_p95_kw=0.0, ev_median_kw=0.0,
            flex_up_f0_peak_kw=0.0, flex_down_reliable_peak_kw=0.0,
            flex_down_reliable_p95_kw=0.0, flex_down_reliable_median_kw=0.0,
            flex_to_ev_peak_ratio=0.0,
        )

    ev_peak = float(summary["ev_peak_kw"].max())
    ev_p95 = float(summary["ev_p95_kw"].max())
    ev_med = float(summary["ev_p50_kw"].max())
    up_peak = float(summary["flex_up_f0_peak_kw"].max())
    dn_peak = float(summary["flex_down_reliable_peak_kw"].max())
    dn_p95 = float(summary["flex_down_reliable_p95_kw"].max())
    dn_med = float(summary["flex_down_reliable_p50_kw"].max())
    ratio = float(dn_peak / ev_peak) if ev_peak > 0 else 0.0

    go = dn_peak >= g.go_reliable_flex_peak_min_kw
    if go:
        verdict = "GO"
        reason = (
            f"可靠下调柔性峰值 {dn_peak:.1f} kW >= {g.go_reliable_flex_peak_min_kw:.0f} kW，"
            f"与最小 BESS({g.bess_comparison_kw_low:.0f}kW) 同量级"
        )
    else:
        verdict = "NO_GO"
        reason = (
            f"可靠下调柔性峰值 {dn_peak:.1f} kW < {g.go_reliable_flex_peak_min_kw:.0f} kW，"
            f"且乐观上调柔性峰值 {up_peak:.1f} kW（上调响应未经 P0-A 验证，见 P0-A up r_5m≈0），"
            f"EV 柔性量纲不足以替代/显著改变 100–200kW BESS"
        )

    return P0BGateVerdict(
        verdict=verdict,
        reason=reason,
        r_down_calibration=float(r_down),
        ev_peak_kw=ev_peak,
        ev_p95_kw=ev_p95,
        ev_median_kw=ev_med,
        flex_up_f0_peak_kw=up_peak,
        flex_down_reliable_peak_kw=dn_peak,
        flex_down_reliable_p95_kw=dn_p95,
        flex_down_reliable_median_kw=dn_med,
        flex_to_ev_peak_ratio=ratio,
    )
