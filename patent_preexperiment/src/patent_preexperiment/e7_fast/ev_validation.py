"""D2 真实 EV 数据验证：M2 上限 + baselines + 指标 + Go 门（review §14-18 + 用户冻结口径）。

四个控制器（review §15；纯函数，无 station/month/connected/gain/future/done/ML）：
- B0_no_increase: allowed_up = 0（最保守）
- B1_pilot_only:  allowed_up = max(pilot_after - actual_before, 0)（把 pilot 当能力的错误）
- B2_rolling_q95: allowed_up = max(q95_before - actual_before, 0)（★ 固定最强简单 baseline）
- C_candidate_m2: allowed_up = max(min(pilot_after, q95_before) - actual_before, 0)
  数学上 C = min(B1, B2)；天然不比 B2 激进。

P_support（review §15）= max(actual_5min - actual_before, 0)
  = 真实自然事件中观察到的实际增加量；非车辆理论最大能力。

时序锁定（用户口径 §2）：对时刻 t 的正 pilot step，
  actual_before = t-1 实际功率；pilot_after = t 新允许功率（拟执行调整值，非响应证据）；
  q95_before = 严格由 t 之前 actual 构造；actual_1/3/5min 只作结果，绝不进 Candidate。

指标（review §16 + 用户口径 §5）：
- over: max(P_allowed - P_support, 0)           越小越好
- under: max(P_support - P_allowed, 0)          越小越不保守；必须摆主表
- hit_rate: candidate 说可增加>0 且真实后续确实增加 的比例
- coverage: 功率加权 = Σ min(P_allowed, P_support) / Σ P_support  （禁止靠每事件放一点虚称高覆盖）

Go 门（review §17 + 用户冻结公式；不做 CI，工程效果）：
- Over improvement = 1 - ΣOver_C / ΣOver_B2 （求和）
- CoverageRatio = Coverage_C / Coverage_B2
- GO:     improvement ≥10% 且 CoverageRatio ≥50% 且 session 等权方向一致
- COND:   improvement 5-10% 或 总体与 session 等权方向不一致
- FAIL:   improvement <5% 或与 rolling Q95 同效
Under 损失大时只能描述为"更保守抑制"，不得称"更准确识别能力"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.e7_fast.config import E7FastConfig
from patent_preexperiment.phase3_p2.schema import M2

CONTROLLERS = ("B0_no_increase", "B1_pilot_only", "B2_rolling_q95", "C_candidate_m2")
STRONGEST_BASELINE = "B2_rolling_q95"  # review §15 固定；不按 over 最小自动选
GATE_SPLITS = ("train", "validation")  # 用户口径 §6：test 物理过滤，最后才看


def compute_allowed_up(
    controller: str,
    actual_before: pd.Series,
    pilot_after: pd.Series,
    q95_before: pd.Series,
) -> pd.Series:
    """按 review §15 纯函数公式计算各控制器 allowed_up（kW）。

    输入只用 actual_before / pilot_after / q95_before（时序锁定）。
    """
    if controller == "B0_no_increase":
        return pd.Series(np.zeros(len(actual_before)), index=actual_before.index, dtype=float)
    if controller == "B1_pilot_only":
        return pd.Series(np.maximum(pilot_after - actual_before, 0.0), index=actual_before.index)
    if controller == "B2_rolling_q95":
        return pd.Series(np.maximum(q95_before - actual_before, 0.0), index=actual_before.index)
    if controller == "C_candidate_m2":
        # C = max(min(pilot_after, q95_before) - actual_before, 0) = min(B1, B2)
        inner = np.minimum(pilot_after, q95_before) - actual_before
        return pd.Series(np.maximum(inner, 0.0), index=actual_before.index)
    raise ValueError(f"未知 controller: {controller!r}")


def compute_p_support(actual_before: pd.Series, actual_5min: pd.Series) -> pd.Series:
    """P_support = max(actual_5min - actual_before, 0)（review §15）。"""
    return pd.Series(np.maximum(actual_5min - actual_before, 0.0), index=actual_before.index)


def filter_m2_evaluation_set(events: pd.DataFrame, cfg: E7FastConfig) -> pd.DataFrame:
    """正式评价集过滤（用户口径 §1）：正向 + info_mode==M2 + q95/actual 有效
    + train+val + 排除 external。

    info_mode_before 必须为 M2_pilot_actual（pilot+actual+history sufficient）。
    history_q95_before_kw / actual_before_kw 有效（非 NaN/None）。
    """
    external_only = set(cfg.split.external_only)
    mask = (
        (events["direction"] == "up")
        & (events["split"].isin(GATE_SPLITS))
        & (~events["site"].isin(external_only))
        & (events["info_mode_before"] == M2)
        & events["history_q95_before_kw"].notna()
        & (events["history_q95_before_kw"] > 0)
        & events["actual_before_kw"].notna()
        & (events["actual_before_kw"] >= 0)
    )
    return events[mask].copy()


@dataclass(frozen=True)
class ControllerMetrics:
    name: str
    n_events: int
    over_sum: float
    under_sum: float
    over_mean: float
    under_mean: float
    over_median: float
    under_median: float
    hit_rate: float
    coverage: float          # 功率加权 = Σ min(allowed,support) / Σ support
    mean_allowed_up: float
    n_p_support_positive: int


def _metrics_for(
    controller: str,
    allowed_up: pd.Series,
    p_support: pd.Series,
) -> ControllerMetrics:
    over = pd.Series(np.maximum(allowed_up - p_support, 0.0), index=allowed_up.index)
    under = pd.Series(np.maximum(p_support - allowed_up, 0.0), index=allowed_up.index)
    n = int(len(allowed_up))
    says_up = allowed_up > 0
    real_up = p_support > 0
    hit = says_up & real_up
    hit_rate = float(hit.sum()) / float(says_up.sum()) if says_up.sum() > 0 else 0.0
    n_support_pos = int(real_up.sum())
    # 功率加权 coverage（用户口径 §5）：Σ min(allowed, support) / Σ support
    support_sum = float(p_support.sum())
    coverage = (
        float(np.minimum(allowed_up, p_support).sum()) / support_sum
        if support_sum > 1e-9
        else 0.0
    )
    return ControllerMetrics(
        name=controller,
        n_events=n,
        over_sum=float(over.sum()),
        under_sum=float(under.sum()),
        over_mean=float(over.mean()) if n > 0 else 0.0,
        under_mean=float(under.mean()) if n > 0 else 0.0,
        over_median=float(over.median()) if n > 0 else 0.0,
        under_median=float(under.median()) if n > 0 else 0.0,
        hit_rate=hit_rate,
        coverage=coverage,
        mean_allowed_up=float(allowed_up.mean()) if n > 0 else 0.0,
        n_p_support_positive=n_support_pos,
    )


def _session_equal_metrics(
    controller: str,
    events: pd.DataFrame,
    allowed_up: pd.Series,
    p_support: pd.Series,
) -> tuple[float, float]:
    """session 等权：每 session 先求 over/under 均值，再跨 session 求均值（用户口径 §7）。"""
    df = pd.DataFrame({
        "session_id": events["session_id"].values,
        "over": pd.Series(np.maximum(allowed_up - p_support, 0.0)).values,
        "under": pd.Series(np.maximum(p_support - allowed_up, 0.0)).values,
    })
    sess_over = df.groupby("session_id")["over"].mean()
    sess_under = df.groupby("session_id")["under"].mean()
    return float(sess_over.mean()), float(sess_under.mean())


@dataclass(frozen=True)
class D2Verdict:
    level: str               # GO / CONDITIONAL / FAIL
    verdict: str
    strongest_baseline: str
    over_improvement_pct: float       # 1 - ΣOver_C / ΣOver_B2
    coverage_ratio_pct: float         # Coverage_C / Coverage_B2
    session_equal_over_improvement_pct: float  # session 等权方向
    session_equal_direction_consistent: bool
    reason: str
    per_controller: dict[str, ControllerMetrics] = field(default_factory=dict)
    session_equal_over: dict[str, float] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)


def evaluate_ev_gate(
    events: pd.DataFrame, cfg: E7FastConfig
) -> tuple[dict[str, ControllerMetrics], D2Verdict]:
    """对正向 M2 pilot 事件计算四控制器指标并按 review §17 + 用户冻结公式判定 Go 门。"""
    gate_cfg = cfg.raw["d2_ev_validation"]["gate"]
    go_over_min = float(gate_cfg["GO"]["over_improvement_vs_strongest_baseline_pct_min"])
    go_cov_min = float(gate_cfg["GO"]["coverage_ratio_pct_min"])
    cond_range = gate_cfg["CONDITIONAL"]["over_improvement_pct_range"]
    fail_max = float(gate_cfg["FAIL"]["over_improvement_pct_max"])

    pos = filter_m2_evaluation_set(events, cfg)

    if pos.empty:
        verdict = D2Verdict(
            level="FAIL", verdict="NO_M2_EVENTS",
            strongest_baseline=STRONGEST_BASELINE,
            over_improvement_pct=0.0, coverage_ratio_pct=0.0,
            session_equal_over_improvement_pct=0.0,
            session_equal_direction_consistent=False,
            reason=("M2 评价集为空（正向 + info_mode==M2 + q95/actual 有效 "
                    "+ train+val）；无法验证 M2。"),
        )
        return {}, verdict

    actual_before = pos["actual_before_kw"]
    pilot_after = pos["pilot_after_kw"]
    q95_before = pos["history_q95_before_kw"].fillna(0.0)
    actual_5min = pos["actual_5min_kw"]
    p_support = compute_p_support(actual_before, actual_5min)

    per_ctrl: dict[str, ControllerMetrics] = {}
    sess_over: dict[str, float] = {}
    for ctrl in CONTROLLERS:
        allowed_up = compute_allowed_up(ctrl, actual_before, pilot_after, q95_before)
        per_ctrl[ctrl] = _metrics_for(ctrl, allowed_up, p_support)
        so, _su = _session_equal_metrics(ctrl, pos, allowed_up, p_support)
        sess_over[ctrl] = so

    b2 = per_ctrl[STRONGEST_BASELINE]
    cand = per_ctrl["C_candidate_m2"]

    # Over improvement = 1 - ΣOver_C / ΣOver_B2（求和，用户冻结公式）
    over_improvement_pct = (
        (1.0 - cand.over_sum / b2.over_sum) * 100.0 if b2.over_sum > 1e-9 else 0.0
    )
    # CoverageRatio = Coverage_C / Coverage_B2
    coverage_ratio_pct = (
        cand.coverage / b2.coverage * 100.0 if b2.coverage > 1e-9 else 0.0
    )
    # session 等权 Over improvement
    sess_b2_over = sess_over[STRONGEST_BASELINE]
    sess_c_over = sess_over["C_candidate_m2"]
    sess_over_improvement_pct = (
        (1.0 - sess_c_over / sess_b2_over) * 100.0 if sess_b2_over > 1e-9 else 0.0
    )
    # 方向一致：两者同号且都 >0 改善 或 都 <=0
    direction_consistent = (over_improvement_pct > 1e-6) == (sess_over_improvement_pct > 1e-6)

    # 判定（review §17 + 用户口径）
    if (
        over_improvement_pct >= go_over_min
        and coverage_ratio_pct >= go_cov_min
        and direction_consistent
    ):
        level, verdict_name, reason = "GO", "M2_active_increase_valid", (
            f"C vs B2 Over improvement={over_improvement_pct:.1f}%>={go_over_min}%，"
            f"CoverageRatio={coverage_ratio_pct:.1f}%>={go_cov_min}%，"
            f"session 等权方向一致（{sess_over_improvement_pct:.1f}%）；M2 双重限制有效。"
        )
    elif over_improvement_pct >= float(cond_range[0]) or not direction_consistent:
        level, verdict_name, reason = "CONDITIONAL", "M2_dependent_only", (
            f"C improvement={over_improvement_pct:.1f}%"
            f"（条件区间 {cond_range[0]}-{cond_range[1]}%）"
            f"或 session 等权方向不一致（总体 {over_improvement_pct:.1f}% "
            f"vs 等权 {sess_over_improvement_pct:.1f}%）；M2 只作从属/窄场景。"
        )
    else:
        level, verdict_name, reason = "FAIL", "M2_not_in_core", (
            f"C improvement={over_improvement_pct:.1f}%<{fail_max}% 或与 rolling Q95 同效；"
            f"M2 不进核心，收缩到 M3/M4 信息不足保护。不调 Q95、不换模型、不继续 ML。"
        )

    d2_verdict = D2Verdict(
        level=level, verdict=verdict_name,
        strongest_baseline=STRONGEST_BASELINE,
        over_improvement_pct=over_improvement_pct,
        coverage_ratio_pct=coverage_ratio_pct,
        session_equal_over_improvement_pct=sess_over_improvement_pct,
        session_equal_direction_consistent=direction_consistent,
        reason=reason, per_controller=per_ctrl,
        session_equal_over=sess_over,
        extras={
            "n_events": int(len(pos)),
            "n_p_support_positive": cand.n_p_support_positive,
            "n_sessions": int(pos["session_id"].nunique()),
            "n_stations": int(pos["station_id"].nunique()),
            "n_months": int(pos["month"].nunique()),
            "go_over_min_pct": go_over_min,
            "go_cov_min_pct": go_cov_min,
        },
    )
    return per_ctrl, d2_verdict


def negative_event_calibration(events: pd.DataFrame, cfg: E7FastConfig) -> dict[str, Any]:
    """负向 pilot 事件响应标定（review §18；不造新算法，用于园区回放）。"""
    external_only = set(cfg.split.external_only)
    neg = events[
        (events["direction"] == "down")
        & (events["split"].isin(GATE_SPLITS))
        & (~events["site"].isin(external_only))
    ].copy()
    if neg.empty:
        return {"n_events": 0}
    safe_dp = neg["delta_pilot_kw"].replace(0.0, np.nan)
    gain_5m = (neg["delta_actual_5min_kw"] / safe_dp).dropna()
    delta_5m = neg["delta_actual_5min_kw"]
    no_response = (delta_5m >= -1e-9).sum()
    return {
        "n_events": int(len(neg)),
        "response_gain_5m_median": float(gain_5m.median()) if len(gain_5m) else 0.0,
        "response_gain_5m_p25": float(gain_5m.quantile(0.25)) if len(gain_5m) else 0.0,
        "response_gain_5m_p75": float(gain_5m.quantile(0.75)) if len(gain_5m) else 0.0,
        "delta_actual_5min_median_kw": float(delta_5m.median()),
        "no_response_ratio": float(no_response) / float(len(neg)),
    }


def compute_event_scores(
    events: pd.DataFrame, cfg: E7FastConfig
) -> pd.DataFrame:
    """为每个 M2 评价集事件计算四控制器 allowed_up / over / under
    （产物 d2_trainval_event_scores）。"""
    pos = filter_m2_evaluation_set(events, cfg)
    if pos.empty:
        return pd.DataFrame()
    actual_before = pos["actual_before_kw"]
    pilot_after = pos["pilot_after_kw"]
    q95_before = pos["history_q95_before_kw"].fillna(0.0)
    p_support = compute_p_support(actual_before, pos["actual_5min_kw"])
    out = pos[["event_id", "session_id", "station_id", "site", "timestamp",
               "month", "split", "info_mode_before",
               "actual_before_kw", "pilot_after_kw", "history_q95_before_kw",
               "actual_5min_kw"]].copy()
    out["p_support_kw"] = p_support.values
    for ctrl in CONTROLLERS:
        au = compute_allowed_up(ctrl, actual_before, pilot_after, q95_before)
        out[f"allowed_up_{ctrl}"] = au.values
        out[f"over_{ctrl}"] = pd.Series(np.maximum(au - p_support, 0.0)).values
        out[f"under_{ctrl}"] = pd.Series(np.maximum(p_support - au, 0.0)).values
    return out.reset_index(drop=True)


def station_month_diagnostic(
    events: pd.DataFrame, cfg: E7FastConfig
) -> pd.DataFrame:
    """按 station × month 拆分 C vs B2 的 over_sum（诊断是否被高频桩/月支配）。"""
    scores = compute_event_scores(events, cfg)
    if scores.empty:
        return pd.DataFrame()
    g = scores.groupby(["site", "station_id", "month"], observed=True).agg(
        n_events=("event_id", "size"),
        over_B2_rolling_q95_sum=("over_B2_rolling_q95", "sum"),
        over_C_candidate_m2_sum=("over_C_candidate_m2", "sum"),
        p_support_sum=("p_support_kw", "sum"),
    ).reset_index()
    g["over_improvement_pct"] = np.where(
        g["over_B2_rolling_q95_sum"] > 1e-9,
        (1.0 - g["over_C_candidate_m2_sum"] / g["over_B2_rolling_q95_sum"]) * 100.0,
        0.0,
    )
    return g.sort_values("n_events", ascending=False)
