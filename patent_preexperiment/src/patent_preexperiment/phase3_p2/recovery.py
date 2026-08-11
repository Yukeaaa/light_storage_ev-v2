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

from patent_preexperiment.phase3_p2.schema import M4, NORMAL, PROTECTIVE, SchemaConfig

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
        # 修复：M4 前置必须与 recovery 之前的时间段联合判定（原实现把
        # `(info_mode==M4).any()` 与 `(ts<recovery_ts).any()` 分开做 `.any()`，
        # 只要 run 里任何位置有 M4、且 run 里任何位置在 recovery 之前就会误判为 True）。
        m4_before = bool(
            ((run["info_mode"] == M4) & (run["timestamp_utc"] < recovery_ts)).any()
        )
        # before 邻域字段从实际 transition 前一行读出（不硬编码）。
        prev = run[run["timestamp_utc"] < recovery_ts]
        if not prev.empty:
            prev_row = prev.iloc[-1]
            mode_before = str(prev_row["info_mode"])
            state_before = str(prev_row["application_state"])
            boundary_mode_before = str(prev_row["boundary_mode"])
        else:
            mode_before = None
            state_before = None
            boundary_mode_before = None
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
            "mode_before": mode_before,
            "state_before": state_before,
            "state_after": str(row["application_state"]),
            "boundary_mode_before": boundary_mode_before,
            "boundary_mode_after": str(row["boundary_mode"]),
            "before_allowed_l": before_l,
            "before_allowed_u": before_u,
            "after_allowed_l": after_l,
            "after_allowed_u": after_u,
            "after_diff": after_diff,
            # complete 判门：在冻结 P2 协议 §5.6 定义（m4_before + after_diff）基础上，
            # 显式校验 transition invariants（recovery 定义上即 PROTECTIVE→NORMAL 且
            # boundary_mode 不变）。这些不变量由状态机结构保证，对冻结 1060 条 complete
            # trace 计数无影响；加入是为 fail-closed：未来任何 bug 导致 transition 元数据
            # 异常时，该 trace 不被计为 complete。mode_before 是否要求 == M3 留待 P2.1
            # 协议定义，此处不凭感觉加入（审查 2608120033 §3 谨慎条款）。
            "complete": (
                m4_before
                and after_diff
                and state_before == PROTECTIVE
                and str(row["application_state"]) == NORMAL
                and boundary_mode_before is not None
                and boundary_mode_before == str(row["boundary_mode"])
            ),
            "n_post_recovery_cycles": int(len(post)),
            "first_post_recovery_diff_utc": first_diff_utc,
        })
    return pd.DataFrame(records, columns=_TRACE_COLUMNS)
