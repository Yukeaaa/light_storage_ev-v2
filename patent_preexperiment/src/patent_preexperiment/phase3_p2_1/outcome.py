"""P2.1A outcome Y（v1.3 §4.4）——future boundary-support persistence。

Y(t) = 1 若 actual_power(t+1 .. t+W) 的 Q50 >= 0.9 × protective_bound(t)，W=10。

- 窗口是**完整分钟序列**上的连续窗口（不是 eligible 子集上的相邻行）——eligible 的
  post_window_ok 只保证窗口内无 gap/reset/缺失，Y 必须回到全量 bf 计算。
- 本模块只计算 Y（物理代理，用 actual，不依赖任何合成 request）；不计算 gain / Δ / CI。
- Y 只在 Step-0 DATA SUFFICIENT 之后被消费（formal exposure）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.phase3_p2_1.frozen import FROZEN


def compute_y(bf: pd.DataFrame) -> pd.Series:
    """对全量边界帧 bf 计算 Y（bool/NaN，index 与 bf 对齐）。

    bf 必须含 post_window_ok（build_boundary_frame_sorted 输出）。post_window_ok=False 的
    行 Y=NaN（未定义）；eligible 行全部 post_window_ok=True，因此 Y 有定义。
    Y=1 ⟺ Q50(actual[i+1 .. i+W]) >= 0.9 × protective_bound(i)。
    """
    w = FROZEN.y_window_w
    actual = bf["actual_power_kw"].to_numpy(dtype=float)
    pb = bf["protective_bound"].to_numpy(dtype=float)
    run_id = bf["run_id"].to_numpy()
    n = len(bf)

    q50 = np.full(n, np.nan, dtype=float)
    if n > 0 and w > 0:
        cols = np.full((n, w), np.nan, dtype=float)
        for j in range(1, w + 1):
            col = np.full(n, np.nan, dtype=float)
            valid = np.zeros(n, dtype=bool)
            if n > j:
                col[:-j] = actual[j:]
                valid[:-j] = run_id[j:] == run_id[:-j]
            cols[:, j - 1] = np.where(valid, col, np.nan)
        # 只对有有限值的行算 nanmedian，避免全 NaN 行触发 "All-NaN slice" 警告
        has_finite = np.isfinite(cols).any(axis=1)
        q50 = np.full(n, np.nan, dtype=float)
        if has_finite.any():
            q50[has_finite] = np.nanmedian(cols[has_finite], axis=1)

    pwo = bf["post_window_ok"].to_numpy(dtype=bool)
    threshold = FROZEN.y_q_threshold * pb
    y = np.full(n, np.nan, dtype=float)
    defined = pwo & np.isfinite(q50) & (pb > 0.0)
    y[defined] = (q50[defined] >= threshold[defined]).astype(float)
    return pd.Series(y, index=bf.index)


def compute_y_eligible(bf: pd.DataFrame, eligible_index: pd.Index) -> pd.Series:
    """对 eligible 行取 Y（formal 专用；eligible_index 为 build_eligible_risk_set 索引）。"""
    y_full = compute_y(bf)
    return y_full.loc[eligible_index].astype(bool)
