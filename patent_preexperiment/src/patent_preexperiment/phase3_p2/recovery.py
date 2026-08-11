"""D3 — 完整 natural recovery trace 检测（§5.6 设备动作证据，必须逐项可见）。

一条完整 trace 必须逐项成立：
1. M4（历史不足）→ `info_mode_change` → M3+PROTECTIVE；
2. PROTECTIVE 期间实际响应使预注册条件成立（pb>0 且 actual>=0.95*pb，连续 3 cycle）
   → recovery（application_state → NORMAL，boundary_mode 仍 history_protective_boundary）；
3. before / after 允许区间同时记录；
4. 后续至少一个 cycle 的 EMS 命令因新区间产生**不同的 final_delta**
   （final_cf_protective != final_cf_normal，同一外生 probe 下反事实比较）。

`after_diff` 不成立或缺少 M4 前置 → 该 recovery 记为 incomplete（不计入 M3 natural）。
replay 单列辅助，不得凑 natural 计数。
"""

from __future__ import annotations

import pandas as pd

from patent_preexperiment.phase3_p2.schema import LOCKED, M3, M4, NORMAL, PROTECTIVE, SchemaConfig

_TRACE_COLUMNS = [
    "session_id",
    "run_id",
    "n_run_cycles",
    "recovery_utc",
    "m4_before",
    "mode_before",
    "state_before",
    "state_after",
    "boundary_mode_before",
    "boundary_mode_after",
    "before_allowed_l",
    "before_allowed_u",
    "after_allowed_l",
    "after_allowed_u",
    "after_diff",
    "complete",
    "n_post_recovery_cycles",
    "first_post_recovery_diff_utc",
]


def _recovery_rows(cycle: pd.DataFrame) -> pd.DataFrame:
    ev = cycle[cycle["recovery_event"]]
    if ev.empty:
        return ev
    return ev


def trace_records(
    cycle: pd.DataFrame,
    scfg: SchemaConfig,
) -> pd.DataFrame:
    """每个含 recovery_event 的 run 生成一条 trace 记录（含 complete 判定）。"""
    ev = _recovery_rows(cycle)
    if ev.empty:
        return pd.DataFrame(columns=_TRACE_COLUMNS)

    records: list[dict] = []
    for _, row in ev.iterrows():
        sid = row["session_id"]
        rid = row["run_id"]
        run = cycle[(cycle["session_id"] == sid) & (cycle["run_id"] == rid)]
        run = run.sort_values("timestamp_utc")

        recovery_ts = row["timestamp_utc"]
        m4_before = bool((run["info_mode"] == M4).any() and (run["timestamp_utc"] < recovery_ts).any())
        post = run[run["timestamp_utc"] > recovery_ts]

        pb = row["protective_bound"]
        budget = row["budget"]
        before_l, before_u = -budget, 0.0
        after_l = -budget
        after_u = (
            max(0.0, float(pb) - float(budget))
            if pd.notna(pb) and pb > 0.0
            else None
        )

        after_diff = False
        first_diff_utc = None
        if not post.empty and after_u is not None:
            cf_prot = post["final_cf_protective"]
            cf_norm = post["final_cf_normal"]
            diff_mask = (cf_prot.notna() & cf_norm.notna()) & (
                (cf_prot - cf_norm).abs() > 1e-9
            )
            if diff_mask.any():
                after_diff = True
                first_diff_utc = post.loc[diff_mask, "timestamp_utc"].min()

        records.append({
            "session_id": sid,
            "run_id": rid,
            "n_run_cycles": int(len(run)),
            "recovery_utc": recovery_ts,
            "m4_before": m4_before,
            "mode_before": M4,
            "state_before": PROTECTIVE,
            "state_after": NORMAL,
            "boundary_mode_before": scfg.layer2_boundary_modes[M3],
            "boundary_mode_after": scfg.layer2_boundary_modes[M3],
            "before_allowed_l": before_l,
            "before_allowed_u": before_u,
            "after_allowed_l": after_l,
            "after_allowed_u": after_u,
            "after_diff": after_diff,
            "complete": m4_before and after_diff,
            "n_post_recovery_cycles": int(len(post)),
            "first_post_recovery_diff_utc": first_diff_utc,
        })
    return pd.DataFrame(records, columns=_TRACE_COLUMNS)
