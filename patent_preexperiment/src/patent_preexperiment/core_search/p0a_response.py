"""P0-A：真实 EV 响应时间谱（review §五；CORE-PATENT SEARCH 阶段第一道零成本数据门）。

目的：**EV 到底是不是一种具有可利用时间动态的柔性资源？**

严格区分 binding / non-binding 事件（不能用全部 negative step 粗统计）：
- binding decrease: pilot_after < actual_before − tolerance（新桩侧允许值确实压到原实际功率以下）
- non-binding decrease: pilot_after >= actual_before − tolerance（actual 不降也不说明 EV 不响应）
- 正向同理分类。

对 binding 事件计算 response_fraction（1/3/5min）：
- down: r_lag = (actual_before − actual_lag) / (actual_before − pilot_after)
- up:   r_lag = (actual_lag − actual_before) / (pilot_after − actual_before)
- clip 到 [clip_low, clip_high]，只用于诊断不掩盖异常。

分层汇总：site / station / month / session_phase / actual_before 档 / step magnitude 档 /
previous pilot state。同 session 多次 step 的 first→later 一致性（repeatability）。

**复用 E7-FAST D0 已提取的 pilot_step_events.parquet**（含正向+负向事件 + 1/3/5min actual
响应 + 全部所需列），不重新提取，零重复造轮子。

数据来源：results/raw/e7_fast/d0/d0_pilot_step_events.parquet（DERIVED_REAL）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.config import BindingRules, P0AConfig, ResponseLagRules

# --- 诊断分档常量（非 gate 阈值，仅用于分层汇总；review §五"必须看"维度）---
_SESSION_PHASE_EDGES: tuple[float, float] = (15.0, 120.0)  # min: early/mid/late
_POWER_BIN_EDGES: tuple[float, float] = (2.0, 5.0)  # kW: low/mid/high
_STEP_MAG_EDGES: tuple[float, float] = (2.0, 5.0)  # |delta_pilot_kw|: small/medium/large


@dataclass(frozen=True)
class P0AGateVerdict:
    """P0-A 门判定结果。"""

    verdict: str  # GO / CONDITIONAL / NO_GO
    reason: str
    binding_up_events: int
    binding_down_events: int
    binding_up_sessions: int
    binding_down_sessions: int
    binding_up_stations: int
    binding_down_stations: int
    binding_up_months: int
    binding_down_months: int
    rf_1m_median_up: float
    rf_1m_median_down: float
    rf_1m_std_up: float
    rf_1m_std_down: float
    rf_3m_median_up: float
    rf_3m_median_down: float
    rf_5m_median_up: float
    rf_5m_median_down: float
    time_dynamic_diff: bool
    heterogeneity_iqr: float
    repeatability_corr: float
    binding_sufficient: bool
    no_go_deterministic_1m: bool


def classify_binding(
    events: pd.DataFrame, rules: BindingRules
) -> pd.DataFrame:
    """对每个事件加 binding 标签（binding / non_binding）。

    down: binding = pilot_after_kw < actual_before_kw - tolerance
    up:   binding = pilot_after_kw > actual_before_kw + tolerance
    """
    out = events.copy()
    tol = rules.tolerance_kw
    is_down = out["direction"] == "down"
    is_up = out["direction"] == "up"
    binding_down = is_down & (
        out["pilot_after_kw"] < out["actual_before_kw"] - tol
    )
    binding_up = is_up & (
        out["pilot_after_kw"] > out["actual_before_kw"] + tol
    )
    out["binding"] = np.where(
        binding_down | binding_up, "binding", "non_binding"
    )
    return out


def compute_response_fraction(
    events: pd.DataFrame, rules: ResponseLagRules
) -> pd.DataFrame:
    """对 binding 事件计算 response_fraction（1/3/5min）；non_binding 设 NaN。

    down: r_lag = (actual_before - actual_lag) / (actual_before - pilot_after)
    up:   r_lag = (actual_lag - actual_before) / (pilot_after - actual_before)
    clip 到 [clip_low, clip_high]。
    """
    out = events.copy()
    is_binding = out["binding"] == "binding"
    is_down = out["direction"] == "down"
    is_up = out["direction"] == "up"

    for lag in rules.lag_min:
        lag_col = f"actual_{lag}min_kw"
        rf_col = f"response_fraction_{lag}m"
        actual_lag = out[lag_col]
        actual_before = out["actual_before_kw"]
        pilot_after = out["pilot_after_kw"]

        denom_down = actual_before - pilot_after  # > tol > 0 for binding down
        denom_up = pilot_after - actual_before  # > tol > 0 for binding up
        numer_down = actual_before - actual_lag
        numer_up = actual_lag - actual_before

        rf = pd.Series(np.nan, index=out.index, dtype=float)
        mask_down = is_binding & is_down & (denom_down > 0)
        mask_up = is_binding & is_up & (denom_up > 0)
        rf.loc[mask_down] = (numer_down / denom_down)[mask_down]
        rf.loc[mask_up] = (numer_up / denom_up)[mask_up]

        rf = rf.clip(rules.fraction_clip_low, rules.fraction_clip_high)
        out[rf_col] = rf
    return out


def add_strata(events: pd.DataFrame) -> pd.DataFrame:
    """加分层列（诊断维度；review §五"必须看"）。

    session_phase / actual_before_bin / step_magnitude_bin / previous_pilot_bin。
    """
    out = events.copy()
    elapsed = out["connected_elapsed_min"]
    out["session_phase"] = np.select(
        [elapsed < _SESSION_PHASE_EDGES[0], elapsed < _SESSION_PHASE_EDGES[1]],
        ["early", "mid"],
        default="late",
    )
    ab = out["actual_before_kw"]
    out["actual_before_bin"] = np.select(
        [ab < _POWER_BIN_EDGES[0], ab < _POWER_BIN_EDGES[1]],
        ["low", "mid"],
        default="high",
    )
    sm = out["delta_pilot_kw"].abs()
    out["step_magnitude_bin"] = np.select(
        [sm < _STEP_MAG_EDGES[0], sm < _STEP_MAG_EDGES[1]],
        ["small", "medium"],
        default="large",
    )
    pb = out["pilot_before_kw"]
    out["previous_pilot_bin"] = np.select(
        [pb < _POWER_BIN_EDGES[0], pb < _POWER_BIN_EDGES[1]],
        ["low", "mid"],
        default="high",
    )
    return out


def summarize_response(
    binding_events: pd.DataFrame, lags: tuple[int, ...]
) -> pd.DataFrame:
    """response_1_3_5m_summary：binding 事件按 direction 的 1/3/5min 响应汇总。"""
    if binding_events.empty:
        return pd.DataFrame(
            columns=["direction", "lag_min", "median", "p25", "p75",
                     "mean", "std", "count"]
        )
    rows: list[dict[str, Any]] = []
    for direction in sorted(binding_events["direction"].unique()):
        sub = binding_events[binding_events["direction"] == direction]
        for lag in lags:
            col = f"response_fraction_{lag}m"
            s = sub[col].dropna()
            rows.append({
                "direction": direction,
                "lag_min": lag,
                "median": float(s.median()) if not s.empty else np.nan,
                "p25": float(s.quantile(0.25)) if not s.empty else np.nan,
                "p75": float(s.quantile(0.75)) if not s.empty else np.nan,
                "mean": float(s.mean()) if not s.empty else np.nan,
                "std": float(s.std()) if not s.empty else np.nan,
                "count": int(s.shape[0]),
            })
    return pd.DataFrame(rows)


def summarize_by_station(
    binding_events: pd.DataFrame, lag: int = 3
) -> pd.DataFrame:
    """station_response_summary：按 site × station 的 response_fraction 汇总（看异质性）。"""
    col = f"response_fraction_{lag}m"
    if binding_events.empty or col not in binding_events.columns:
        return pd.DataFrame()
    grp = binding_events.groupby(["site", "station_id", "direction"], observed=True)
    rows: list[dict[str, Any]] = []
    for (site, station, direction), g in grp:
        s = g[col].dropna()
        rows.append({
            "site": site,
            "station_id": station,
            "direction": direction,
            "median": float(s.median()) if not s.empty else np.nan,
            "mean": float(s.mean()) if not s.empty else np.nan,
            "std": float(s.std()) if not s.empty else np.nan,
            "count": int(s.shape[0]),
        })
    return pd.DataFrame(rows)


def compute_session_repeatability(
    binding_events: pd.DataFrame, lag: int = 3
) -> tuple[pd.DataFrame, float]:
    """session_repeatability：同 session 多次 binding step 的 first → later 一致性。

    返回 (repeatability_table, first_later_corr)。
    repeatability_table: 每个有 >=2 binding 事件的 session 的 first/later response_fraction。
    first_later_corr: first vs later response_fraction 的 Pearson 相关（全体方向合并）。
    """
    col = f"response_fraction_{lag}m"
    if binding_events.empty or col not in binding_events.columns:
        return pd.DataFrame(), np.nan

    df = binding_events.dropna(subset=[col]).sort_values(
        ["session_id", "timestamp"], kind="stable"
    )
    df["ord_in_session"] = df.groupby("session_id").cumcount()
    multi = df[df["session_id"].isin(
        df.groupby("session_id").size().loc[lambda s: s >= 2].index
    )]
    if multi.empty:
        return pd.DataFrame(), np.nan

    first = multi[multi["ord_in_session"] == 0].set_index("session_id")[col].rename("first_rf")
    later = (
        multi[multi["ord_in_session"] > 0]
        .groupby("session_id")[col].mean().rename("later_rf_mean")
    )
    rep = pd.concat([first, later], axis=1).dropna()

    corr = float(rep["first_rf"].corr(rep["later_rf_mean"])) if len(rep) >= 5 else np.nan

    out = rep.reset_index()
    out["direction"] = multi.groupby("session_id")["direction"].first().values
    out["site"] = multi.groupby("session_id")["site"].first().values
    return out, corr


def evaluate_p0a_gate(
    binding_trainval: pd.DataFrame,
    repeatability_corr: float,
    cfg: P0AConfig,
) -> P0AGateVerdict:
    """P0-A 门判定（train+validation 主判集，排除 external/stress）。

    GO = binding 充分 AND (时间动态不同 OR 异质性 OR repeatability)
    NO_GO_deterministic = binding 充分 AND 1min median > 0.9 AND std < 0.1
    NO_GO_insufficient = binding 不充分
    """
    g = cfg.gate
    rf_1m = "response_fraction_1m"
    rf_3m = "response_fraction_3m"
    rf_5m = "response_fraction_5m"

    def _stats(direction: str) -> dict[str, float]:
        sub = binding_trainval[binding_trainval["direction"] == direction]
        if sub.empty:
            return {
                "events": 0, "sessions": 0, "stations": 0, "months": 0,
                "rf_1m_med": np.nan, "rf_1m_std": np.nan,
                "rf_3m_med": np.nan, "rf_5m_med": np.nan,
            }
        s1 = sub[rf_1m].dropna() if rf_1m in sub.columns else pd.Series(dtype=float)
        s3 = sub[rf_3m].dropna() if rf_3m in sub.columns else pd.Series(dtype=float)
        s5 = sub[rf_5m].dropna() if rf_5m in sub.columns else pd.Series(dtype=float)
        return {
            "events": int(sub.shape[0]),
            "sessions": int(sub["session_id"].nunique()),
            "stations": int(sub["station_id"].nunique()),
            "months": int(sub["month"].nunique()),
            "rf_1m_med": float(s1.median()) if not s1.empty else np.nan,
            "rf_1m_std": float(s1.std()) if not s1.empty else np.nan,
            "rf_3m_med": float(s3.median()) if not s3.empty else np.nan,
            "rf_5m_med": float(s5.median()) if not s5.empty else np.nan,
        }

    up = _stats("up")
    dn = _stats("down")

    binding_up_sufficient = (
        up["events"] >= g.usable_events_min
        and up["sessions"] >= g.unique_sessions_min
        and up["stations"] >= g.stations_min
        and up["months"] >= g.months_min
    )
    binding_down_sufficient = (
        dn["events"] >= g.usable_events_min
        and dn["sessions"] >= g.unique_sessions_min
        and dn["stations"] >= g.stations_min
        and dn["months"] >= g.months_min
    )
    binding_sufficient = binding_up_sufficient or binding_down_sufficient

    # 时间动态：1/3/5min response_fraction median 是否有差异
    def _time_dynamic(d: dict[str, float]) -> bool:
        med1, med3, med5 = d["rf_1m_med"], d["rf_3m_med"], d["rf_5m_med"]
        if any(np.isnan(v) for v in (med1, med3, med5)):
            return False
        return (
            abs(med3 - med1) > g.time_dynamic_diff_threshold
            or abs(med5 - med1) > g.time_dynamic_diff_threshold
        )

    time_dynamic_diff = _time_dynamic(up) or _time_dynamic(dn)

    # 异质性：station 间 response_fraction_3m median 的 IQR
    station_medians: list[float] = []
    if not binding_trainval.empty and rf_3m in binding_trainval.columns:
        st = binding_trainval.dropna(subset=[rf_3m]).groupby(["site", "station_id"])[rf_3m].median()
        station_medians = st.dropna().tolist()
    heterogeneity_iqr = (
        float(np.percentile(station_medians, 75) - np.percentile(station_medians, 25))
        if len(station_medians) >= 5
        else 0.0
    )
    heterogeneity = heterogeneity_iqr > g.heterogeneity_iqr_threshold

    # repeatability
    rep_valid = (
        not np.isnan(repeatability_corr)
        and abs(repeatability_corr) > g.repeatability_corr_threshold
    )

    # NO_GO: binding 后 1min 确定性完全响应（只对有事件的方向检查；空方向不阻止）
    def _det_1m(d: dict[str, float]) -> bool:
        if d["events"] == 0:
            return False  # 无事件的方向不构成确定性响应证据
        med, std = d["rf_1m_med"], d["rf_1m_std"]
        if np.isnan(med):
            return False
        return med > g.no_go_1m_full_response_median and (
            np.isnan(std) or std < g.no_go_1m_full_response_std
        )

    has_any_binding = up["events"] > 0 or dn["events"] > 0
    # 所有有 binding 事件的方向都确定性响应 → 无时间动态可利用
    det_directions = [d for d in (up, dn) if d["events"] > 0]
    no_go_deterministic_1m = (
        binding_sufficient
        and has_any_binding
        and len(det_directions) > 0
        and all(_det_1m(d) for d in det_directions)
    )

    # 判定
    if not binding_sufficient:
        verdict = "NO_GO"
        reason = (
            f"binding 事件不充分（up={up['events']}/sessions={up['sessions']}, "
            f"down={dn['events']}/sessions={dn['sessions']}）；"
            f"阈值 events>={g.usable_events_min} sessions>={g.unique_sessions_min}"
        )
    elif no_go_deterministic_1m:
        verdict = "NO_GO"
        reason = (
            f"binding 后 1min 内几乎完全确定性响应"
            f"（up median={up['rf_1m_med']:.3f} std={up['rf_1m_std']:.3f}, "
            f"down median={dn['rf_1m_med']:.3f} std={dn['rf_1m_std']:.3f}）→ "
            f"BESS先接EV慢慢接力 方向直接降级"
        )
    elif time_dynamic_diff or heterogeneity or rep_valid:
        verdict = "GO"
        signals = []
        if time_dynamic_diff:
            signals.append("1/3/5min 响应明显不同")
        if heterogeneity:
            signals.append(f"车辆间响应异质性 IQR={heterogeneity_iqr:.3f}")
        if rep_valid:
            signals.append(f"session repeatability corr={repeatability_corr:.3f}")
        reason = (
            f"binding 事件充分（up={up['events']}, down={dn['events']}）；"
            f"可利用时间动态信号：{'; '.join(signals)}"
        )
    else:
        verdict = "CONDITIONAL"
        reason = (
            f"binding 事件充分（up={up['events']}, down={dn['events']}），"
            f"但时间动态信号弱（time_diff={time_dynamic_diff}, "
            f"IQR={heterogeneity_iqr:.3f}, corr={repeatability_corr:.3f}）；"
            f"需进一步诊断"
        )

    return P0AGateVerdict(
        verdict=verdict,
        reason=reason,
        binding_up_events=int(up["events"]),
        binding_down_events=int(dn["events"]),
        binding_up_sessions=int(up["sessions"]),
        binding_down_sessions=int(dn["sessions"]),
        binding_up_stations=int(up["stations"]),
        binding_down_stations=int(dn["stations"]),
        binding_up_months=int(up["months"]),
        binding_down_months=int(dn["months"]),
        rf_1m_median_up=float(up["rf_1m_med"]),
        rf_1m_median_down=float(dn["rf_1m_med"]),
        rf_1m_std_up=float(up["rf_1m_std"]),
        rf_1m_std_down=float(dn["rf_1m_std"]),
        rf_3m_median_up=float(up["rf_3m_med"]),
        rf_3m_median_down=float(dn["rf_3m_med"]),
        rf_5m_median_up=float(up["rf_5m_med"]),
        rf_5m_median_down=float(dn["rf_5m_med"]),
        time_dynamic_diff=bool(time_dynamic_diff),
        heterogeneity_iqr=float(heterogeneity_iqr),
        repeatability_corr=float(repeatability_corr) if not np.isnan(repeatability_corr) else 0.0,
        binding_sufficient=bool(binding_sufficient),
        no_go_deterministic_1m=bool(no_go_deterministic_1m),
    )
