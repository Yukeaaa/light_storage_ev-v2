"""P2.1A adversarial baselines 触发规则（v1.3 §4.3；机械冻结，无随机/选择自由度）。

在同一 eligible risk set 上，用以下方法各自产生 trigger 时点（每 segment 取第一个）：
  B0  D3 original          原冻结 trigger（pb>0 且 actual >= 0.95×pb，连续 3 cycle）
  B1  simple persistence   连续 3 cycle，max(actual)−min(actual) <= 5%×median(actual_3cycle)
  B2a rolling median       actual >= rolling_median(actual, 15min, shift(1))，连续 3 cycle
  B2b rolling max          actual >= rolling_max(actual, 15min, shift(1))，连续 3 cycle
  B4  lag-shuffle null     用 actual 的 lag(1) 版本触发 B0 条件

所有掩码先在全量边界帧（bf）上按 run 计算（连续 3 cycle 不跨 run），再与 eligible
risk set 求交——trigger 候选 t 必须是 eligible cycle（post_window_ok 保证 Y 可计算）。
B3（random matched）由 b3_map 单独生成（C2：一次生成、永久固定）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.phase3_p2_1.frozen import FROZEN

B0 = "B0"
B1 = "B1"
B2A = "B2a"
B2B = "B2b"
B3 = "B3"
B4 = "B4"

ALL_BASELINES = (B0, B1, B2A, B2B, B3, B4)
"""B3 之外由本模块计算 mask 的 baselines（B3 走 b3_map）。"""
MASKED_BASELINES = (B0, B1, B2A, B2B, B4)


def run_change_mask(bf: pd.DataFrame) -> np.ndarray:
    """bool ndarray：每行是否开启新 run（session 或 run_id 变化）。"""
    n = len(bf)
    change = np.zeros(n, dtype=bool)
    if n > 1:
        change[1:] = (
            (bf["session_id"].to_numpy()[1:] != bf["session_id"].to_numpy()[:-1])
            | (bf["run_id"].to_numpy()[1:] != bf["run_id"].to_numpy()[:-1])
        )
    return change


def sustained_window(cond: np.ndarray, run_change: np.ndarray, k: int) -> np.ndarray:
    """连续 k 个 cycle 内 cond 全真（不跨 run）→ True；run 内不足 k 个 → False。"""
    n = len(cond)
    out = np.zeros(n, dtype=bool)
    if n == 0 or k <= 0:
        return out
    run_grp = np.cumsum(run_change)
    prefix = np.cumsum(cond.astype(np.int64))
    j = np.arange(n) - k + 1
    valid = j >= 0
    j_clip = np.clip(j, 0, None)
    same_run = run_grp == run_grp[j_clip]
    prev = np.where(j > 0, prefix[j_clip - 1], 0)
    window_sum = prefix - prev
    out = valid & same_run & (window_sum == k)
    return out


def trigger_masks(bf: pd.DataFrame, scfg: object) -> dict[str, pd.Series]:
    """计算 B0/B1/B2a/B2b/B4 的触发掩码（bool Series，index 与 bf 对齐）。

    bf 必须已按 (session_id, run_id, timestamp_utc) 排序（build_eligible_risk_set 保证）。
    掩码语义：该 cycle 满足对应规则（含 run 内连续 3 cycle 要求）。与 eligible 求交即得
    trigger 候选。
    """
    actual = bf["actual_power_kw"].to_numpy(dtype=float)
    pb = bf["protective_bound"].to_numpy(dtype=float)
    run_change = run_change_mask(bf)
    k = FROZEN.b0_sustained_cycles
    ratio = getattr(scfg, "recovery_ratio", FROZEN.expected_recovery_ratio)

    pb_ok = np.isfinite(pb) & (pb > 0.0)
    b0_cond = pb_ok & np.isfinite(actual) & (actual >= ratio * pb)
    b0 = sustained_window(b0_cond, run_change, k)

    b1 = _b1_mask(actual, run_change)

    roll_med, roll_max = _rolling_15min(bf, scfg)
    b2a_cond = np.isfinite(roll_med) & np.isfinite(actual) & (actual >= roll_med)
    b2b_cond = np.isfinite(roll_max) & np.isfinite(actual) & (actual >= roll_max)
    b2a = sustained_window(b2a_cond, run_change, k)
    b2b = sustained_window(b2b_cond, run_change, k)

    lag1 = np.full(len(actual), np.nan, dtype=float)
    lag1[1:] = actual[:-1]
    lag1[run_change] = np.nan  # 不跨 run 取 lag
    b4_cond = pb_ok & np.isfinite(lag1) & (lag1 >= ratio * pb)
    b4 = sustained_window(b4_cond, run_change, k)

    idx = bf.index
    return {
        B0: pd.Series(b0, index=idx),
        B1: pd.Series(b1, index=idx),
        B2A: pd.Series(b2a, index=idx),
        B2B: pd.Series(b2b, index=idx),
        B4: pd.Series(b4, index=idx),
    }


def _b1_mask(actual: np.ndarray, run_change: np.ndarray) -> np.ndarray:
    """B1：窗口 [t-2, t] 内 max−min <= 5%×median，窗口全部在同一个 run 内。"""
    n = len(actual)
    out = np.zeros(n, dtype=bool)
    if n < 3:
        return out
    a0, a1, a2 = actual[:-2], actual[1:-1], actual[2:]
    mx = np.maximum(np.maximum(a0, a1), a2)
    mn = np.minimum(np.minimum(a0, a1), a2)
    med = a0 + a1 + a2 - mx - mn  # 3 个数的中位数 = 和 − 最大值 − 最小值
    finite3 = np.isfinite(a0) & np.isfinite(a1) & np.isfinite(a2)
    win_change = run_change[:-2] | run_change[1:-1] | run_change[2:]
    mid = finite3 & ~win_change & ((mx - mn) <= FROZEN.b1_epsilon_frac * med)
    out[2:] = mid
    return out


def _rolling_15min(bf: pd.DataFrame, scfg: object) -> tuple[np.ndarray, np.ndarray]:
    """因果化 rolling median / max（shift(1) + 15min 窗口，按 run 分组；min_periods=1）。

    复用 boundary.protective_bound 的 rolling 模式，但 min_periods=1（B2 无需最小样本门槛）。
    """
    window = getattr(scfg, "history_window_min", FROZEN.b2_window_min)
    n = len(bf)
    keys = ["session_id", "run_id"]

    shifted = bf.groupby(keys)["actual_power_kw"].shift(1)
    dfi = bf.copy()
    dfi["_shift"] = shifted.to_numpy()
    dfi["_row_id"] = range(n)
    dfi = dfi.set_index("_row_id")

    med_roll = (
        dfi.groupby(keys)[["_shift", "timestamp_utc"]]
        .rolling(f"{window}min", min_periods=1, on="timestamp_utc")
        .median()
        .reset_index()
    )
    med_ordered = med_roll.sort_values("_row_id").set_index("_row_id")
    if len(med_ordered) != n:
        raise RuntimeError("B2 rolling median 对齐失败")
    med = med_ordered["_shift"].to_numpy(dtype=float)

    max_roll = (
        dfi.groupby(keys)[["_shift", "timestamp_utc"]]
        .rolling(f"{window}min", min_periods=1, on="timestamp_utc")
        .max()
        .reset_index()
    )
    max_ordered = max_roll.sort_values("_row_id").set_index("_row_id")
    if len(max_ordered) != n:
        raise RuntimeError("B2 rolling max 对齐失败")
    mx = max_ordered["_shift"].to_numpy(dtype=float)
    return med, mx
