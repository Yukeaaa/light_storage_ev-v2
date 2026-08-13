"""四个 system arm（用户口径 §9；不新增第五个）。

S0_unrestricted: allowed_up = park_requested（乐观上限）
S1_conservative: allowed_up = 0（最保守）
S2_rolling_q95:  allowed_up = max(q95 - actual, 0)（★ 最强简单 baseline）
S3_our_scheme:   M2 allowed_up = max(min(pilot, q95) - actual, 0)；M3/M4 = 0

D3-U 用 M2 评价集事件 → S3 即 C_candidate_m2（与 D2 一致）。
时序锁定同 D2：actual_before / pilot_after / q95_before 因果化。
"""

from __future__ import annotations

import pandas as pd

SYSTEM_ARMS = ("S0_unrestricted", "S1_conservative", "S2_rolling_q95", "S3_our_scheme")
STRONGEST_BASELINE = "S2_rolling_q95"


def compute_arm_allowed_up(
    arm: str,
    actual_before: pd.Series,
    pilot_after: pd.Series,
    q95_before: pd.Series,
    park_requested: pd.Series,
) -> pd.Series:
    """各 arm 的 ev_accepted_delta（事前安排给 EV 的上调量，kW）。"""
    if arm == "S0_unrestricted":
        return park_requested.clip(lower=0.0)
    if arm == "S1_conservative":
        return pd.Series(0.0, index=actual_before.index)
    if arm == "S2_rolling_q95":
        import numpy as np
        return pd.Series(np.maximum(q95_before - actual_before, 0.0), index=actual_before.index)
    if arm == "S3_our_scheme":
        # M2: max(min(pilot, q95) - actual, 0) = min(B1, B2)（与 D2 C_candidate 一致）
        import numpy as np
        inner = np.minimum(pilot_after, q95_before) - actual_before
        return pd.Series(np.maximum(inner, 0.0), index=actual_before.index)
    raise ValueError(f"未知 system arm: {arm!r}")
