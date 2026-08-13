"""D3 系统层 6 指标 + Go 门（用户口径 §14 + §15）。

排序固定：①unexpected_shortfall ②unplanned_bess ③pcc_residual ④accepted_flex
⑤conservatism ⑥total_bess_activity（只诊断，不入 GO 门）。
比较 baseline = S2_rolling_q95；工程效果不做 CI。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from patent_preexperiment.e7_fast.system_arms import STRONGEST_BASELINE, SYSTEM_ARMS


@dataclass(frozen=True)
class ArmSystemMetrics:
    arm: str
    n_events: int
    unexpected_ev_shortfall_sum: float       # ① 核心
    unplanned_bess_correction_sum: float     # ② 核心
    pcc_residual_sum: float                  # ③ 核心
    accepted_real_ev_flex_sum: float         # ④ 防止靠禁止取胜
    conservatism_sum: float                  # ⑤ 实际有能力但没用掉
    total_bess_activity_sum: float           # ⑥ 诊断 only（planned + unplanned）


@dataclass(frozen=True)
class D3Verdict:
    level: str               # GO / CONDITIONAL / FAIL
    verdict: str
    comparison_baseline: str
    unexpected_shortfall_reduction_pct: float   # S3 vs S2
    unplanned_bess_reduction_pct: float
    pcc_residual_not_worsened: bool
    s3_flex_significantly_higher_than_s1: bool
    reason: str
    per_arm: dict[str, ArmSystemMetrics] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)


def compute_arm_metrics(replay: pd.DataFrame, arm: str) -> ArmSystemMetrics:
    sub = replay[replay["arm"] == arm]
    n = int(len(sub))
    if n == 0:
        return ArmSystemMetrics(arm, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return ArmSystemMetrics(
        arm=arm,
        n_events=n,
        unexpected_ev_shortfall_sum=float(sub["unexpected_ev_shortfall"].sum()),
        unplanned_bess_correction_sum=float(sub["unplanned_bess_correction"].sum()),
        pcc_residual_sum=float(sub["pcc_residual"].sum()),
        accepted_real_ev_flex_sum=float(sub["ev_realized_delta"].sum()),
        conservatism_sum=float(
            (sub["ev_observed_support"] - sub["ev_realized_delta"]).clip(lower=0.0).sum()
        ),
        total_bess_activity_sum=float(
            sub["planned_bess_delta"].sum() + sub["unplanned_bess_correction"].sum()
        ),
    )


def evaluate_system_gate(
    replay: pd.DataFrame, cfg: Any
) -> tuple[dict[str, ArmSystemMetrics], D3Verdict]:
    """按用户口径 §15 判定 D3-U 系统 Go 门（S3 vs S2）。"""
    gate_cfg = cfg.raw["d3_park_system"]["system_gate"]
    go_shortfall_min = float(
        gate_cfg["GO"]["unexpected_ev_shortfall_reduction_pct_min"]
    )
    go_bess_min = float(
        gate_cfg["GO"]["unplanned_bess_correction_reduction_pct_min"]
    )
    cond_lo, cond_hi = gate_cfg["CONDITIONAL"]["reduction_pct_range"]
    fail_max = float(gate_cfg["NO_GO"]["s3_vs_s2_reduction_pct_max"])

    per_arm = {arm: compute_arm_metrics(replay, arm) for arm in SYSTEM_ARMS}

    s2 = per_arm[STRONGEST_BASELINE]
    s3 = per_arm["S3_our_scheme"]
    s1 = per_arm["S1_conservative"]

    def _reduction_pct(baseline_val: float, cand_val: float) -> float:
        if baseline_val > 1e-9:
            return (1.0 - cand_val / baseline_val) * 100.0
        # baseline 已 0（无缺口）→ 无改善空间
        return 0.0 if cand_val <= 1e-9 else -100.0

    shortfall_reduction = _reduction_pct(
        s2.unexpected_ev_shortfall_sum, s3.unexpected_ev_shortfall_sum
    )
    bess_reduction = _reduction_pct(
        s2.unplanned_bess_correction_sum, s3.unplanned_bess_correction_sum
    )
    pcc_not_worsened = s3.pcc_residual_sum <= s2.pcc_residual_sum + 1e-9
    # S3 真实利用的 flex 显著高于 S1（S1 allowed_up=0 → flex=0）
    s3_flex_higher_than_s1 = s3.accepted_real_ev_flex_sum > s1.accepted_real_ev_flex_sum * 1.1

    if (
        shortfall_reduction >= go_shortfall_min
        and bess_reduction >= go_bess_min
        and pcc_not_worsened
        and s3_flex_higher_than_s1
    ):
        level, verdict, reason = "GO", "D3_system_value_valid", (
            f"S3 vs S2: unexpected_shortfall 降 {shortfall_reduction:.1f}%>={go_shortfall_min}%，"
            f"unplanned_bess 降 {bess_reduction:.1f}%>={go_bess_min}%，"
            f"PCC residual 未恶化，S3 flex({s3.accepted_real_ev_flex_sum:.0f})"
            f">S1({s1.accepted_real_ev_flex_sum:.0f})×1.1。"
        )
    elif shortfall_reduction >= float(cond_lo) or bess_reduction >= float(cond_lo):
        level, verdict, reason = "CONDITIONAL", "D3_narrow_only", (
            f"S3 vs S2: shortfall 降 {shortfall_reduction:.1f}% / bess 降 {bess_reduction:.1f}%"
            f"（条件区间 {cond_lo}-{cond_hi}%）；写窄，M2 只作条件实施方式。"
        )
    else:
        level, verdict, reason = "FAIL", "D3_no_system_value", (
            f"S3 vs S2: shortfall 降 {shortfall_reduction:.1f}%<{fail_max}% "
            f"或系统优势只靠极端参数；"
            f"停止 performance 扩展。不调 Q95、不加 ML、不恢复 D3。"
        )

    d3_verdict = D3Verdict(
        level=level, verdict=verdict,
        comparison_baseline=STRONGEST_BASELINE,
        unexpected_shortfall_reduction_pct=shortfall_reduction,
        unplanned_bess_reduction_pct=bess_reduction,
        pcc_residual_not_worsened=pcc_not_worsened,
        s3_flex_significantly_higher_than_s1=s3_flex_higher_than_s1,
        reason=reason, per_arm=per_arm,
        extras={
            "n_events": s3.n_events,
            "s2_shortfall": s2.unexpected_ev_shortfall_sum,
            "s3_shortfall": s3.unexpected_ev_shortfall_sum,
            "s2_bess": s2.unplanned_bess_correction_sum,
            "s3_bess": s3.unplanned_bess_correction_sum,
        },
    )
    return per_arm, d3_verdict
