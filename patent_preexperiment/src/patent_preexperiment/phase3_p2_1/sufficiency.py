"""P2.1A Step-0 data sufficiency（v1.3 §5；只读计数，禁止读 Y/gain/Δ/CI）。

sufficiency 条件（全部满足才允许 formal A-gate exposure）：
  a. eligible M3 segments >= 100（suff_min_eligible_segments）
  b. B0–B4 每个 baseline 的 trigger **distinct session** 数 >= 30（第 5 轮：按 session 去重）

本模块只消费 build_trigger_counts（无 Y）；在 SUFFICIENT 之前任何代码路径不得调用
metrics.build_trigger_table / outcome.compute_y / bootstrap（物理隔离，v1.3 §7 [7]）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from patent_preexperiment.phase3_p2_1.frozen import FROZEN
from patent_preexperiment.phase3_p2_1.triggers import ALL_BASELINES


@dataclass(frozen=True)
class Sufficiency:
    """data sufficiency 判定结果（只含计数，不含 Y）。"""

    sufficient: bool
    n_eligible_segments: int
    trigger_sessions: dict[str, int]  # method → distinct session 数
    failed: tuple[str, ...]  # 失败条件名称（空 = 通过）

    def to_dict(self) -> dict[str, Any]:
        return {
            "sufficient": self.sufficient,
            "n_eligible_segments": self.n_eligible_segments,
            "min_eligible_segments": FROZEN.suff_min_eligible_segments,
            "trigger_distinct_sessions": dict(self.trigger_sessions),
            "min_trigger_sessions": FROZEN.suff_min_trigger_sessions,
            "failed": list(self.failed),
        }


def evaluate_sufficiency(
    eligible: Any,
    trigger_counts: Any,
) -> Sufficiency:
    """Step-0 只读判定：eligible 段数 + 每 baseline distinct trigger session 数。

    Args:
        eligible: build_eligible_risk_set 输出（只读 segment_id 数）。
        trigger_counts: metrics.build_trigger_counts 输出（无 Y）。
    """
    n_eligible_segments = int(eligible["segment_id"].nunique()) if len(eligible) else 0
    trigger_sessions: dict[str, int] = {}
    if len(trigger_counts):
        for method, sub in trigger_counts.groupby("method"):
            trigger_sessions[str(method)] = int(sub["session_id"].nunique())
    for method in ALL_BASELINES:
        trigger_sessions.setdefault(method, 0)

    failed: list[str] = []
    if n_eligible_segments < FROZEN.suff_min_eligible_segments:
        failed.append("eligible_segments")
    for method in ALL_BASELINES:
        if trigger_sessions[method] < FROZEN.suff_min_trigger_sessions:
            failed.append(f"trigger_sessions_{method}")

    return Sufficiency(
        sufficient=not failed,
        n_eligible_segments=n_eligible_segments,
        trigger_sessions=trigger_sessions,
        failed=tuple(failed),
    )
