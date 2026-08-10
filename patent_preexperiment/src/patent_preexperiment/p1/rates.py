"""P1 主/次指标与穷尽判定（Phase 3 v1.0.2 §1.5 step 4 / §1.6）。

主指标：E1 evidence rate（cycle 级，event-start snapshot，与 A5 同口径）按 S1/S2 分层；
rate_ratio = rate_S2 / rate_S1（effect size）、rate_diff = rate_S2 - rate_S1（inferential）。
次指标：quartile direction（A5 duplicate-edge rule）。

§1.6 穷尽映射（v1.0.2）全部机器实现，不留给 test 暴露后发明处理。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.p1.states import apply_quartile_bin

RATIO_GO = 1.5
RATIO_CONDITIONAL = 1.2


@dataclass(frozen=True)
class RateResult:
    n_s1: int
    n_s2: int
    n_e1_s1: int
    n_e1_s2: int
    rate_s1: float
    rate_s2: float
    rate_diff: float


def state_rates(
    obs_states: pd.DataFrame,
    e1_cycles: set[tuple[str, pd.Timestamp]],
) -> RateResult:
    """按 S1/S2 分层计算 E1 evidence rate（cycle 级，event-start snapshot）。

    分母 = 该 state 的可评估 cycle 数；分子 = 其中是 E1 event-start cycle 的数量。
    S3 不计入 rate 分母（insufficient）。
    """
    s1 = obs_states[obs_states["state"] == "S1"]
    s2 = obs_states[obs_states["state"] == "S2"]
    n_s1 = int(len(s1))
    n_s2 = int(len(s2))

    def _e1_count(df: pd.DataFrame) -> int:
        if len(df) == 0:
            return 0
        keys = set(zip(df["site"], df["cycle"], strict=False))
        return int(sum(1 for k in keys if k in e1_cycles))

    n_e1_s1 = _e1_count(s1)
    n_e1_s2 = _e1_count(s2)
    rate_s1 = n_e1_s1 / n_s1 if n_s1 else 0.0
    rate_s2 = n_e1_s2 / n_s2 if n_s2 else 0.0
    return RateResult(
        n_s1=n_s1,
        n_s2=n_s2,
        n_e1_s1=n_e1_s1,
        n_e1_s2=n_e1_s2,
        rate_s1=rate_s1,
        rate_s2=rate_s2,
        rate_diff=rate_s2 - rate_s1,
    )


@dataclass(frozen=True)
class RatioResult:
    ratio: float | None  # +inf 用 float('inf')；NA 用 None
    ratio_kind: str  # "finite" | "positive_infinity" | "na_zero_zero" | "state_missing"
    state_missing: bool


def exhaustive_ratio(r: RateResult) -> RatioResult:
    """§1.6 穷尽映射（v1.0.2）：覆盖全部 outcome，不允许未定义分支。

    B. n_S1=0 或 n_S2=0 → state_missing → NOT_EVALUABLE + route Conditional；
    A. 可评估：rate_S1=0∧rate_S2>0 → +∞；rate_S1=0∧rate_S2=0 → NA → No-Go；
       rate_S1>0 → rate_S2/rate_S1。
    """
    if r.n_s1 == 0 or r.n_s2 == 0:
        return RatioResult(ratio=None, ratio_kind="state_missing", state_missing=True)
    if r.rate_s1 == 0.0 and r.rate_s2 > 0.0:
        return RatioResult(
            ratio=math.inf, ratio_kind="positive_infinity", state_missing=False
        )
    if r.rate_s1 == 0.0 and r.rate_s2 == 0.0:
        return RatioResult(ratio=None, ratio_kind="na_zero_zero", state_missing=False)
    return RatioResult(
        ratio=r.rate_s2 / r.rate_s1, ratio_kind="finite", state_missing=False
    )


def _ratio_effect_passes(ratio: RatioResult) -> tuple[bool, float]:
    """effect-size 门（②）：raw rate_ratio ≥ 1.5。+∞ 视为通过。

    返回 (pass, effective_ratio)，effective_ratio 供分级（1.2/1.5）。
    """
    if ratio.ratio_kind == "positive_infinity":
        return True, math.inf
    if ratio.ratio is None:
        return False, 0.0
    return bool(ratio.ratio >= RATIO_GO), ratio.ratio


def quartile_direction(
    obs_states: pd.DataFrame,
    edges_result: dict[str, Any],
    e1_cycles: set[tuple[str, pd.Timestamp]],
) -> dict[str, Any]:
    """次指标：最高/最低 effective variance bin 的 E1 rate 方向。A5 duplicate-edge rule。

    不硬编码 Q4/Q1：label 顺序来自 edges_result['labels']（低→高 variance），
    只比较实际非空（effective）的顶部/底部 bin。不足 2 个 effective bins →
    insufficient_bin_resolution（不重找 cutpoint）。
    返回 {direction, low_label, high_label, rate_low, rate_high, high_gt_low,
    insufficient_bin_resolution}。
    """
    def _result(*, direction: str, low_label: str | None, high_label: str | None,
                rate_low: float | None, rate_high: float | None,
                high_gt_low: bool | None, insufficient: bool) -> dict[str, Any]:
        return {
            "direction": direction,
            "low_label": low_label,
            "high_label": high_label,
            "rate_low": rate_low,
            "rate_high": rate_high,
            "high_gt_low": high_gt_low,
            "insufficient_bin_resolution": insufficient,
        }

    if edges_result.get("insufficient_bin_resolution"):
        return _result(
            direction="insufficient_bin_resolution", low_label=None, high_label=None,
            rate_low=None, rate_high=None, high_gt_low=None, insufficient=True,
        )
    obs = obs_states.copy()
    obs["_qbin"] = apply_quartile_bin(obs, edges_result)

    def _rate(label: str) -> float | None:
        sub = obs[obs["_qbin"] == label]
        if len(sub) == 0:
            return None
        keys = set(zip(sub["site"], sub["cycle"], strict=False))
        n_e1 = int(sum(1 for k in keys if k in e1_cycles))
        return n_e1 / len(sub)

    ordered = list(edges_result["labels"])
    present = [lab for lab in ordered if (obs["_qbin"] == lab).any()]
    if len(present) < 2:
        return _result(
            direction="insufficient_bin_resolution",
            low_label=present[0] if present else None,
            high_label=present[-1] if present else None,
            rate_low=_rate(present[0]) if present else None,
            rate_high=_rate(present[-1]) if present else None,
            high_gt_low=None,
            insufficient=True,
        )
    low_label, high_label = present[0], present[-1]
    rate_low = _rate(low_label)
    rate_high = _rate(high_label)
    if rate_low is None or rate_high is None:
        return _result(
            direction="insufficient_bin_resolution",
            low_label=low_label, high_label=high_label,
            rate_low=rate_low, rate_high=rate_high,
            high_gt_low=None, insufficient=True,
        )
    if rate_high > rate_low:
        direction = f"{high_label}>{low_label}"
    elif rate_high == rate_low:
        direction = "equal"
    else:
        direction = f"{high_label}<{low_label}"
    return _result(
        direction=direction,
        low_label=low_label,
        high_label=high_label,
        rate_low=rate_low,
        rate_high=rate_high,
        high_gt_low=rate_high > rate_low,
        insufficient=False,
    )


def _is_positive(v: float) -> bool:
    return np.isfinite(v) and v > 0.0


def p1_verdict(
    r: RateResult,
    ratio: RatioResult,
    ci: tuple[float, float] | None,
    quartile: dict[str, Any],
    pretest_ok: bool,
) -> dict[str, Any]:
    """综合 Go / Conditional / No-Go（§1.6 穷尽映射 + Success ②③④）。

    ① 预检由 Step 0 判定，这里仅接收 pretest_ok。
    ② effect-size：raw rate_ratio ≥ 1.5（+∞ 视为通过）；
    ③ inferential：cluster bootstrap 95% CI of rate_diff 下界 > 0；
    ④ quartile direction：最高 effective bin rate > 最低 effective bin rate
       （不足 2 bins → 不满足 Go，走 Conditional）。
    """
    if not pretest_ok:
        return {"verdict": "No-Go", "reason": "pretest_not_feasible"}
    if ratio.state_missing:
        return {
            "verdict": "NOT_EVALUABLE",
            "patent_route": "Conditional",
            "reason": "state_missing（n_S1=0 或 n_S2=0；train-q50 外推后缺状态，非机制反证）",
        }
    if ci is None:
        return {
            "verdict": "NOT_EVALUABLE",
            "patent_route": "Conditional",
            "reason": "inferential_missing（bootstrap CI 不可得）",
        }
    if ratio.ratio_kind == "na_zero_zero":
        return {
            "verdict": "No-Go",
            "reason": (
                "rate_S1=0 且 rate_S2=0 → rate_ratio=NA → No-Go"
                "（可评估但无正向 state separation）"
            ),
        }
    # 可评估且存在率：rate_S2 > rate_S1 才有正向分离
    if r.rate_s2 <= r.rate_s1:
        return {
            "verdict": "No-Go",
            "reason": f"rate_S2={r.rate_s2:.6f} <= rate_S1={r.rate_s1:.6f}（含 equality）",
        }

    effect_pass, eff_ratio = _ratio_effect_passes(ratio)
    ci_lo, ci_hi = ci
    inferential_pass = _is_positive(ci_lo)
    quartile_pass = quartile.get("high_gt_low") is True
    if effect_pass and inferential_pass and quartile_pass:
        return {
            "verdict": "Go",
            "reason": (
                f"rate_ratio={eff_ratio if math.isinf(eff_ratio) else round(eff_ratio, 4)} "
                f"≥1.5 且 rate_diff CI({ci_lo:.6f}, {ci_hi:.6f}) 下界>0 且 "
                f"{quartile.get('high_label')}>{quartile.get('low_label')}"
            ),
        }
    # Conditional：方向正确但弱 / CI 含 0 / quartile 不满足
    if eff_ratio >= RATIO_CONDITIONAL or inferential_pass or quartile_pass:
        parts = []
        if eff_ratio < RATIO_GO:
            eff_txt = eff_ratio if math.isinf(eff_ratio) else round(eff_ratio, 4)
            parts.append(f"rate_ratio={eff_txt} in [1.2, 1.5)")
        if not inferential_pass:
            parts.append(f"rate_diff CI({ci_lo:.6f}, {ci_hi:.6f}) 下界≤0")
        if not quartile_pass:
            parts.append(f"quartile direction={quartile['direction']}")
        return {
            "verdict": "Conditional",
            "reason": "方向正确但部分条件未满：" + "；".join(parts) if parts else "Conditional",
        }
    return {
        "verdict": "Conditional",
        "reason": "方向正确但 rate_ratio 未达 1.2",
    }
