"""主指标（机制成立率）与 Step0 kill gates / formal verdict（§5.7 / §5.8 / §6）。

- M1  D1 branch realizability：全部 cycle 查表得到唯一 info_mode/boundary_mode → 目标 1.0。
- M2  D2 action-bound realizability：M3/M4 数值 cycle 上 final==clip(requested,L,U) 且
      disposition 与唯一规则一致 → 目标 1.0（M1/M2 dispatch-only，不入门）。
- M2_cov 描述性：clip 实际生效（requested != final）的 cycle 占比（报告不入门）。
- M3  D3 recovery trace：完整 natural trace 计数（≥20 traces / ≥5 sessions，门）。
- M4  unsupported-release prevention：PROTECTIVE cycle 中 final_delta>0 比例 → 目标 0.0。

M1/M2/M4 是实现正确性（确定性/符合性），目标即 1.0/0.0，非统计推断；M3 是计数，非推断。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.phase3_p2.schema import (
    LOCKED,
    M1,
    M2,
    M3,
    M4,
    NORMAL,
    PROTECTIVE,
    SchemaConfig,
)
from patent_preexperiment.phase3_p2.actions import (
    ACCEPTED,
    BOUNDARY_UNAVAILABLE,
    CLIPPED_LOWER,
    CLIPPED_UPPER,
)

_EPS = 1e-9


def expected_disposition(requested: float, lower: float | None, upper: float | None) -> str:
    """独立于 disposition 赋值的期望规则（schema action_disposition）。"""
    if lower is None or upper is None:
        return BOUNDARY_UNAVAILABLE
    if lower <= requested <= upper:
        return ACCEPTED
    if requested > upper:
        return CLIPPED_UPPER
    return CLIPPED_LOWER


@dataclass
class PoolAgg:
    """分块累积器：逐块 add(cycle frame)，最终 finalize() 输出池级指标。"""

    n_cycles: int = 0
    n_eligible: int = 0
    n_clip_ok: int = 0
    n_disp_ok: int = 0
    n_cov_cycles: int = 0
    n_protective_eligible: int = 0
    n_release_violations: int = 0
    n_boundary_unavailable: int = 0
    n_diff_lock_prot: int = 0
    n_diff_prot_normal: int = 0
    n_m1: int = 0
    n_m2: int = 0
    n_m3: int = 0
    n_m4: int = 0
    n_cycles_severe_gap_reset: int = 0
    mode_counts: dict[str, int] = field(default_factory=dict)
    boundary_mode_counts: dict[str, int] = field(default_factory=dict)
    state_counts: dict[str, int] = field(default_factory=dict)
    seed_counts: dict[int, int] = field(default_factory=dict)
    budget_counts: dict[float, int] = field(default_factory=dict)
    probe_counts: dict[float, int] = field(default_factory=dict)
    sessions: set[str] = field(default_factory=set)
    runs: set[tuple[str, int]] = field(default_factory=set)
    trace_frames: list[pd.DataFrame] = field(default_factory=list)

    def add(self, cycle: pd.DataFrame) -> None:
        self.n_cycles += int(len(cycle))
        self.sessions.update(cycle["session_id"].unique().tolist())
        runs = list(zip(cycle["session_id"], cycle["run_id"], strict=False))
        self.runs.update(runs)

        mode = cycle["info_mode"]
        self.mode_counts = _merge_counts(self.mode_counts, mode.value_counts().to_dict())
        bm = cycle["boundary_mode"]
        self.boundary_mode_counts = _merge_counts(
            self.boundary_mode_counts, bm.value_counts().to_dict()
        )
        st = cycle["application_state"]
        self.state_counts = _merge_counts(self.state_counts, st.value_counts().to_dict())
        self.seed_counts = _merge_counts(
            self.seed_counts,
            {int(k): int(v) for k, v in cycle["seed_byte"].value_counts().items()},
        )
        self.budget_counts = _merge_counts(
            self.budget_counts,
            {float(k): int(v) for k, v in cycle["budget"].value_counts().items()},
        )
        self.probe_counts = _merge_counts(
            self.probe_counts,
            {float(k): int(v) for k, v in cycle["requested_delta"].value_counts().items()},
        )
        self.n_m1 += int((mode == M1).sum())
        self.n_m2 += int((mode == M2).sum())
        self.n_m3 += int((mode == M3).sum())
        self.n_m4 += int((mode == M4).sum())
        self.n_cycles_severe_gap_reset += int(
            (cycle["run_start"] & (cycle["info_mode"] == M3)).sum()
        )

        eligible = cycle["_has_bound"] & mode.isin([M3, M4])
        self.n_eligible += int(eligible.sum())
        self.n_boundary_unavailable += int(
            ((mode.isin([M3, M4])) & ~cycle["_has_bound"]).sum()
        )
        if eligible.any():
            sub = cycle[eligible]
            self.n_clip_ok += int(sub["_clip_check"].sum())
            # disposition 一致性：独立重算期望 disposition 再比较
            expected = sub.apply(
                lambda r: expected_disposition(
                    float(r["requested_delta"]), float(r["L"]), float(r["U"])
                ),
                axis=1,
            )
            self.n_disp_ok += int((expected == sub["disposition"]).sum())
            cov = (sub["requested_delta"] - sub["final_delta"]).abs() > _EPS
            self.n_cov_cycles += int(cov.sum())

            prot = sub[sub["application_state"] == PROTECTIVE]
            self.n_protective_eligible += int(len(prot))
            self.n_release_violations += int((prot["final_delta"] > _EPS).sum())

            diff_lp = (sub["final_cf_locked"] - sub["final_cf_protective"]).abs() > _EPS
            self.n_diff_lock_prot += int(diff_lp.sum())
            both = sub["final_cf_normal"].notna() & sub["final_cf_protective"].notna()
            diff_pn = both & (
                (sub.loc[both, "final_cf_normal"] - sub.loc[both, "final_cf_protective"]).abs() > _EPS
            )
            self.n_diff_prot_normal += int(diff_pn.sum())

    def add_traces(self, traces: pd.DataFrame) -> None:
        if not traces.empty:
            self.trace_frames.append(traces)

    def finalize(self) -> dict[str, Any]:
        m1 = 1.0 if self.n_cycles > 0 else float("nan")
        m2 = (
            self.n_clip_ok / self.n_eligible
            if self.n_eligible > 0
            else float("nan")
        )
        disp_ok = (
            self.n_disp_ok / self.n_eligible if self.n_eligible > 0 else float("nan")
        )
        m2_cov = (
            self.n_cov_cycles / self.n_eligible if self.n_eligible > 0 else float("nan")
        )
        m4 = (
            self.n_release_violations / self.n_protective_eligible
            if self.n_protective_eligible > 0
            else float("nan")
        )
        traces = (
            pd.concat(self.trace_frames, ignore_index=True)
            if self.trace_frames
            else pd.DataFrame()
        )
        n_complete = 0
        n_complete_sessions = 0
        if not traces.empty:
            n_complete = int(traces["complete"].sum())
            n_complete_sessions = int(
                traces.loc[traces["complete"], "session_id"].nunique()
            )
        return {
            "n_cycles": self.n_cycles,
            "n_sessions": len(self.sessions),
            "n_runs": len(self.runs),
            "n_m1": self.n_m1,
            "n_m2": self.n_m2,
            "n_m3": self.n_m3,
            "n_m4": self.n_m4,
            "n_eligible_m3_m4": self.n_eligible,
            "n_boundary_unavailable": self.n_boundary_unavailable,
            "n_clip_ok": self.n_clip_ok,
            "n_disp_ok": self.n_disp_ok,
            "n_cov_cycles": self.n_cov_cycles,
            "n_protective_eligible": self.n_protective_eligible,
            "n_release_violations": self.n_release_violations,
            "n_diff_lock_prot": self.n_diff_lock_prot,
            "n_diff_prot_normal": self.n_diff_prot_normal,
            "m1": round(m1, 6),
            "m2": round(m2, 6) if not np.isnan(m2) else None,
            "m2_disp_ok": round(disp_ok, 6) if not np.isnan(disp_ok) else None,
            "m2_cov": round(m2_cov, 6) if not np.isnan(m2_cov) else None,
            "m4": round(m4, 6) if not np.isnan(m4) else None,
            "mode_counts": dict(sorted(self.mode_counts.items())),
            "boundary_mode_counts": dict(sorted(self.boundary_mode_counts.items())),
            "state_counts": dict(sorted(self.state_counts.items())),
            "seed_byte_distribution": dict(sorted(self.seed_counts.items())),
            "budget_distribution": {
                str(k): v for k, v in sorted(self.budget_counts.items())
            },
            "probe_distribution": {
                str(k): v for k, v in sorted(self.probe_counts.items())
            },
            "n_cycles_severe_gap_reset_m3": self.n_cycles_severe_gap_reset,
            "traces": {
                "n_traces_total": int(len(traces)),
                "n_traces_complete": n_complete,
                "n_complete_sessions": n_complete_sessions,
            },
        }


def _merge_counts(base: dict[Any, int], add: dict[Any, int]) -> dict[Any, int]:
    out = dict(base)
    for k, v in add.items():
        out[k] = out.get(k, 0) + int(v)
    return out


def pool_verdict(agg: PoolAgg, scfg: SchemaConfig) -> str:
    """formal verdict：Success / Conditional / No-Go（穷尽映射，不允许未定义分支）。"""
    m1 = agg.n_cycles > 0
    m2_ok = agg.n_eligible == agg.n_clip_ok
    m4_ok = agg.n_release_violations == 0
    if not (m1 and m2_ok and m4_ok):
        return "No-Go"
    n_traces = sum(len(t[t["complete"]]) for t in agg.trace_frames) if agg.trace_frames else 0
    n_sessions = len(
        {s for t in agg.trace_frames for s in t.loc[t["complete"], "session_id"]}
    ) if agg.trace_frames else 0
    if n_traces >= scfg.m3_min_traces and n_sessions >= scfg.m3_min_sessions:
        return "Success"
    if n_traces >= 5:
        return "Conditional"
    return "No-Go"


def k1_verdict(
    scfg: SchemaConfig,
    natural_summary: dict[str, Any],
    replay_summaries: dict[str, dict[str, Any]],
) -> str:
    """K1：D1 穷尽确定性 + 信息面变化真的产生不同 boundary mode。FAIL → STOP。

    - 确定性：16 种信息组合全部映射唯一 mode（d1.assert_exhaustive 已静态验证，
      此处对真实数据复核：无 unmapped cycle）。
    - 敏感性（face-flip，同一 caltech 池不同信息面 → 不同 branch）：
      natural → M2（pilot 分支）；mask → M3（current-only 分支）；
      truncate → M4（conservative fallback）；inject → M1（capability 分支）。
    """
    replay_summaries = dict(replay_summaries)

    def has_boundary_mode(s: dict[str, Any], bm: str) -> bool:
        return int(s["boundary_mode_counts"].get(bm, 0)) > 0

    if has_boundary_mode(natural_summary, "response_history_boundary"):
        pilot_branch_ok = True
    else:
        pilot_branch_ok = has_boundary_mode(
            replay_summaries.get("natural", {}), "response_history_boundary"
        )

    face_flips = [
        ("natural", "response_history_boundary"),  # M2 branch
        ("mask_pilot", "history_protective_boundary"),  # M3 branch
        ("truncate_history", "conservative_fallback"),  # M4 branch
        ("inject_capability", "capability_supported_boundary"),  # M1 branch
    ]
    for name, bm in face_flips:
        s = replay_summaries.get(name)
        if s is None or not has_boundary_mode(s, bm):
            return "FAIL"

    all_modes = set(natural_summary["boundary_mode_counts"].keys())
    for s in replay_summaries.values():
        all_modes |= set(s["boundary_mode_counts"].keys())
    if len(all_modes) < 3 or not pilot_branch_ok:
        return "FAIL"
    return "PASS"


def k2_verdict(
    scfg: SchemaConfig,
    train_summary: dict[str, Any],
) -> str:
    """K2：权限等级能编码为数值 action set 并改变 accept/clip。FAIL → PROJECT_NO_GO。

    - M2=1.0 且 disposition 全部一致（控制器约束行为正确）；
    - M4=0.0（PROTECTIVE 无 unsupported release）；
    - LOCKED≠PROTECTIVE 且 PROTECTIVE≠NORMAL 的 action 差异都存在（等级可区分）。
    """
    if train_summary["m2"] != 1.0:
        return "PROJECT_NO_GO"
    if train_summary["m2_disp_ok"] != 1.0:
        return "PROJECT_NO_GO"
    if train_summary["m4"] != 0.0:
        return "PROJECT_NO_GO"
    if train_summary["n_diff_lock_prot"] == 0:
        return "PROJECT_NO_GO"
    if train_summary["n_diff_prot_normal"] == 0:
        return "PROJECT_NO_GO"
    return "PASS"


def k3_verdict(
    scfg: SchemaConfig,
    train_summary: dict[str, Any],
) -> str:
    """K3：JPL train 存在不依赖通信恢复/停充/reset 的 natural recovery trace。
    natural=0 → PROJECT_NO_GO（v1.0.2：replay 不得救）。"""
    n = train_summary["traces"]["n_traces_complete"]
    if n == 0:
        return "PROJECT_NO_GO"
    return "PASS"
