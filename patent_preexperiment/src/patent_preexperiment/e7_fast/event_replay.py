"""D3 事件回放：5 个核心冻结量（用户口径 §4 + §5 + 审查 corrective audit）。

对每个真实 M2 正向事件，构造园区短周期场景，按各 arm 计算：
- park_requested_ev_delta = delta_pilot_kw（独立于 S2/S3）
- arm_allowed_up = 该 arm 的车辆侧 allowed_up（未 cap）
- ev_accepted_delta = min(park_requested, arm_allowed_up)  # ★ request-cap（审查 P0 修正）
- ev_observed_support = max(actual_5min - actual_before, 0)（与 D2 P_support 一致）
- ev_realized_delta = min(ev_accepted_delta, ev_observed_support)（保守回放）
- planned_bess_delta = park_requested - ev_accepted（事前正常协调；>=0 因 accepted<=request）
- unexpected_ev_shortfall = max(ev_accepted - ev_observed_support, 0)（★ EV 执行缺口）
- unplanned_bess_correction = min(shortfall, bess_fast_available)（★ 事后临时补偿）
- pcc_residual = shortfall - unplanned_bess_correction

★ 审查 P0 修正（review/申请前技术尽调-审查.md §5-8）：
  ev_accepted 必须 = min(park_requested, arm_allowed_up)。
  EMS 只要求 EV 增加 ΔP_req，控制器不能安排 EV 增加超过 ΔP_req。
  硬断言：0 <= ev_accepted <= park_requested。
  旧代码 ev_accepted = arm_allowed_up（未 cap）→ D3 shortfall 实际是 D2 Over 原样搬运。
  修复后 S2（更激进）被 cap 更多 → S3 vs S2 系统收益可能下降。

禁止把 planned_bess 算进 unplanned_bess_correction（用户口径 §5）。
时序锁定同 D2。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.e7_fast.bess import bess_fast_available_power, make_bess_params
from patent_preexperiment.e7_fast.system_arms import SYSTEM_ARMS, compute_arm_allowed_up

_EVENT_REPLAY_COLUMNS = [
    "event_id", "session_id", "station_id", "site", "timestamp", "month", "split",
    "arm",
    "park_requested_ev_delta",
    "arm_allowed_up_uncapped",
    "ev_accepted_delta",
    "ev_observed_support",
    "ev_realized_delta",
    "planned_bess_delta",
    "unexpected_ev_shortfall",
    "unplanned_bess_correction",
    "pcc_residual",
    "bess_fast_available_power",
    "actual_before_kw", "pilot_after_kw", "q95_before_kw",
]


def replay_arm(
    arm: str,
    events: pd.DataFrame,
    *,
    bess_power_ratio: float = 0.5,
) -> pd.DataFrame:
    """对单 arm 在 M2 正向事件上回放，返回每事件的核心量（kW）。

    ★ 审查 P0 修正：ev_accepted = min(park_requested, arm_allowed_up)。
    """
    actual_before = events["actual_before_kw"]
    pilot_after = events["pilot_after_kw"]
    q95_before = events["history_q95_before_kw"].fillna(0.0)
    park_requested = events["delta_pilot_kw"].clip(lower=0.0)
    actual_5min = events["actual_5min_kw"]

    arm_allowed_up = compute_arm_allowed_up(
        arm, actual_before, pilot_after, q95_before, park_requested
    )
    # ★ 审查 P0 修正：request-cap。EMS 只要求 ΔP_req，不能安排超过它。
    ev_accepted = pd.Series(
        np.minimum(park_requested, arm_allowed_up), index=actual_before.index
    )
    # 硬断言：0 <= ev_accepted <= park_requested
    assert ((ev_accepted >= 0) & (ev_accepted <= park_requested + 1e-9)).all(), (
        f"request-cap 硬断言失败：arm={arm}, "
        f"min={ev_accepted.min()}, max={ev_accepted.max()}, "
        f"max_request={park_requested.max()}"
    )

    ev_observed_support = pd.Series(
        np.maximum(actual_5min - actual_before, 0.0), index=actual_before.index
    )
    ev_realized = pd.Series(
        np.minimum(ev_accepted, ev_observed_support), index=actual_before.index
    )
    # accepted <= request, so planned_bess is non-negative without clipping.
    planned_bess = pd.Series(
        park_requested - ev_accepted, index=actual_before.index
    )
    unexpected_shortfall = pd.Series(
        np.maximum(ev_accepted - ev_observed_support, 0.0), index=actual_before.index
    )
    # BESS 快速可用功率（D3-U = charge 方向；按每事件 actual_before 缩放）
    bess_avail = pd.Series(
        [
            bess_fast_available_power(
                make_bess_params(ab, power_ratio=bess_power_ratio), direction="charge"
            )
            for ab in actual_before
        ],
        index=actual_before.index,
    )
    unplanned_bess = pd.Series(
        np.minimum(unexpected_shortfall, bess_avail), index=actual_before.index
    )
    pcc_residual = pd.Series(
        unexpected_shortfall - unplanned_bess, index=actual_before.index
    )

    out = pd.DataFrame({
        "event_id": events["event_id"].values,
        "session_id": events["session_id"].values,
        "station_id": events["station_id"].values,
        "site": events["site"].values,
        "timestamp": events["timestamp"].values,
        "month": events["month"].values,
        "split": events["split"].values,
        "arm": arm,
        "park_requested_ev_delta": park_requested.values,
        "arm_allowed_up_uncapped": arm_allowed_up.values,
        "ev_accepted_delta": ev_accepted.values,
        "ev_observed_support": ev_observed_support.values,
        "ev_realized_delta": ev_realized.values,
        "planned_bess_delta": planned_bess.values,
        "unexpected_ev_shortfall": unexpected_shortfall.values,
        "unplanned_bess_correction": unplanned_bess.values,
        "pcc_residual": pcc_residual.values,
        "bess_fast_available_power": bess_avail.values,
        "actual_before_kw": actual_before.values,
        "pilot_after_kw": pilot_after.values,
        "q95_before_kw": q95_before.values,
    })
    return out[_EVENT_REPLAY_COLUMNS]


def replay_all_arms(
    events: pd.DataFrame, *, bess_power_ratio: float = 0.5
) -> pd.DataFrame:
    """对所有 4 个 arm 回放，返回拼接 DataFrame。"""
    parts = [replay_arm(arm, events, bess_power_ratio=bess_power_ratio) for arm in SYSTEM_ARMS]
    return pd.concat(parts, ignore_index=True)
