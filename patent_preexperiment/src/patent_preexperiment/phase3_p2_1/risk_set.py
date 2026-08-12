"""P2.1A eligible risk-set builder（v1.3 §4.2；所有 trigger 共用）。

职责：从 JPL train current-only 分钟表构建 eligible risk set——每个 M3 segment 的
qualifying cycle 集合。复用 P2 boundary.build_boundary_frame 计算 run_id /
history_sufficient / protective_bound。

**本模块禁止计算 Y / gain / Δ / CI**（Step-0 物理隔离要求，v1.3 §10 implementation
强制项）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from patent_preexperiment.phase3_p2.boundary import build_boundary_frame
from patent_preexperiment.phase3_p2.schema import SchemaConfig
from patent_preexperiment.phase3_p2_1.frozen import FROZEN


@dataclass(frozen=True)
class EligibleCycle:
    """一个 eligible trigger 候选 cycle（属于某 M3 segment 的 risk-set 成员）。

    segment_id = (session_id, run_id) 唯一标识一个 M3 segment；每 segment 最多取第一个
    qualifying trigger（D3 recovery 单向，v1.3 §4.2）。
    """

    session_id: str
    run_id: int
    segment_id: str  # f"{session_id}#{run_id}"，稳定标识
    timestamp_utc: pd.Timestamp
    cycle_index: int
    protective_bound: float
    actual_power_kw: float


def _segment_id(session_id: str, run_id: int) -> str:
    return f"{session_id}#{run_id}"


def build_boundary_frame_sorted(
    pool: pd.DataFrame,
    scfg: SchemaConfig,
) -> pd.DataFrame:
    """构建并排序边界帧（run 上下文完整，供 trigger 掩码在真实 run 上计算）。

    输出与 build_eligible_risk_set 相同的列集，另含 `_eligible`（M3 可评价候选）与
    `post_window_ok`。排序键 (session_id, run_id, timestamp_utc)。
    """
    w = FROZEN.y_window_w
    bf = build_boundary_frame(pool, scfg)
    bf = bf.sort_values(["session_id", "run_id", "timestamp_utc"]).reset_index(drop=True)

    # M3 可评价：history_sufficient 且 protective_bound>0 且 actual 非空
    # （M3 current-only 分支的确定性代理；info_mode 计算是 P2 pipeline 职责）。
    m3_eligible = (
        bf["history_sufficient"].fillna(False)
        & (bf["protective_bound"] > 0.0)
        & bf["actual_power_kw"].notna()
    )
    bf["_eligible"] = m3_eligible.to_numpy()
    bf["post_window_ok"] = _post_window_ok(bf, w)
    bf["segment_id"] = [
        _segment_id(s, r)
        for s, r in zip(bf["session_id"], bf["run_id"], strict=True)
    ]
    return bf


def eligible_mask(bf: pd.DataFrame) -> pd.Series:
    """eligible 条件（M3 可评价 & post-window 完整）→ bool Series，与 bf 对齐。"""
    return pd.Series(
        (bf["_eligible"] & bf["post_window_ok"]).to_numpy(dtype=bool), index=bf.index
    )


def build_eligible_risk_set(
    pool: pd.DataFrame,
    scfg: SchemaConfig,
) -> pd.DataFrame:
    """构建 eligible risk set（v1.3 §4.2）。等价于 build_boundary_frame_sorted 后取
    _eligible & post_window_ok。**不计算 Y / gain / Δ / CI**。

    保留 bf 的行索引（不 reset），便于 compute_y(bf).loc[eligible.index] 对齐。
    """
    bf = build_boundary_frame_sorted(pool, scfg)
    eligible = bf.loc[eligible_mask(bf)].copy()
    eligible = eligible.drop(columns=["_eligible"])
    keep = [
        "session_id", "run_id", "segment_id", "timestamp_utc", "cycle_index",
        "protective_bound", "actual_power_kw", "history_sufficient", "post_window_ok",
        "station_id", "site",  # formal diagnostics 需要站点身份（不进 Gate）
    ]
    return eligible[keep]


def _post_window_ok(bf: pd.DataFrame, w: int) -> pd.Series:
    """向量化 post-window 完整性：行 i 的 [i+1, i+W] 窗口内无 run reset / gap / 缺失。

    - invalid[j] = j 是 run 起始行（session/run 与 j-1 不同）或 severe_gap_before
      （NaN 视为 gap，fail-closed）或 actual_power_kw 缺失。
    - 行已按 (session_id, run_id, timestamp_utc) 排序，run 内连续；窗口跨 run 即无效。
    - 返回 bool Series，与 bf 对齐。
    """
    n = len(bf)
    if n == 0 or w <= 0:
        return pd.Series(np.zeros(n, dtype=bool), index=bf.index)

    sid = bf["session_id"].to_numpy()
    rid = bf["run_id"].to_numpy()
    invalid = np.zeros(n, dtype=bool)
    if n > 1:
        invalid[1:] = (sid[1:] != sid[:-1]) | (rid[1:] != rid[:-1])
    invalid[0] = True
    sg = bf["severe_gap_before"].fillna(True).to_numpy()
    apk = bf["actual_power_kw"].to_numpy()
    invalid |= sg | np.isnan(apk)

    # 每个位置右侧最近的 invalid 位置（含自身）
    nxt_inv = np.empty(n, dtype=np.int64)
    pos = np.flatnonzero(invalid)
    if len(pos) == 0:
        nxt_inv[:] = n
    else:
        # 用反向搜索：对每个 i，nxt_inv[i] = min{ j>=i : invalid[j] }（无则 n）
        nxt_inv = _next_invalid(indices=pos, n=n)

    # 对 i：窗口 [i+1, i+W] 有效 ⟺ nxt_inv[i+1] >= i+W+1（窗口内无 invalid）
    ok = np.zeros(n, dtype=bool)
    limit = n - w - 1
    if limit >= 0:
        i = np.arange(limit + 1)
        ok[i] = nxt_inv[i + 1] >= (i + w + 1)
    return pd.Series(ok, index=bf.index)


def _next_invalid(*, indices: np.ndarray, n: int) -> np.ndarray:
    """对每个 i，返回右侧（含）最近 invalid 位置；无则返回 n。indices 升序。"""
    out = np.full(n, n, dtype=np.int64)
    p = len(indices)  # 当前候选下标（indices[p] = 首个 >= i 的 invalid，未定）
    for i in range(n - 1, -1, -1):
        while p > 0 and indices[p - 1] >= i:
            p -= 1
        if p < len(indices):
            out[i] = indices[p]
    return out


def eligible_segments(eligible: pd.DataFrame) -> list[str]:
    """返回 distinct segment_id 列表（每 segment 最多一个 trigger 的基础）。"""
    return sorted(eligible["segment_id"].unique().tolist())


def first_trigger_per_segment(
    eligible: pd.DataFrame,
    trigger_mask: pd.Series,
) -> pd.DataFrame:
    """对每 segment 取第一个 qualifying trigger（v1.3 §4.2）。

    trigger_mask: bool Series，index 与 eligible 对齐，标记哪些 cycle 满足该 trigger 规则。
    返回：trigger DataFrame（每 segment 至多 1 行）。
    """
    triggered = eligible[trigger_mask].copy()
    if triggered.empty:
        return triggered
    # 每 segment 保留 timestamp 最小的一行
    triggered = triggered.sort_values(["segment_id", "timestamp_utc"])
    first = triggered.groupby("segment_id", as_index=False).first()
    return first.reset_index(drop=True)
