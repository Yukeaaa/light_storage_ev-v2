"""P2 回放管线 + D3 recovery + Step0 kill gate 单测（合成池，覆盖四分支 replay）。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from patent_preexperiment.phase3_p2.metrics import (
    PoolAgg,
    k1_verdict,
    k2_verdict,
    k3_verdict,
    pool_verdict,
)
from patent_preexperiment.phase3_p2.pipeline import (
    ReplayTransform,
    build_cycle_frame,
    process_pool,
    seeds_for_pool,
)
from patent_preexperiment.phase3_p2.recovery import trace_records
from patent_preexperiment.phase3_p2.schema import LOCKED, M1, M2, M3, M4, NORMAL, PROTECTIVE, load_schema
from tests._p2_helpers import (
    low_budget_session_ids as _low_budget_session_ids,
    make_session,
    stable_current_only_session,
    stable_pilot_session,
)

PP = Path(__file__).resolve().parents[1]
SCFG = load_schema(PP / "configs" / "phase3_p2_action_schema.yaml")

NATURAL = "natural"
MASK = "mask_pilot"
TRUNCATE = "truncate_history"
INJECT = "inject_capability"


def _low_budget_session_id() -> str:
    """找一个 seed%4==0（budget=3.0，边界余量最大）的会话 id。"""
    return _low_budget_session_ids(SCFG, 1)[0]


def test_natural_current_only_branch_and_recovery() -> None:
    sid = _low_budget_session_id()
    pool = stable_current_only_session(sid, n_minutes=35, actual_kw=5.0)
    cycle = build_cycle_frame(pool, SCFG, seeds_for_pool(pool), ReplayTransform(name=NATURAL))

    # 0-4：history 不足 → M4；5+：history 足够 → M3
    assert cycle.loc[:4, "info_mode"].tolist() == [M4] * 5
    assert cycle.loc[5:, "info_mode"].tolist() == [M3] * 30
    # 状态机：0-4 LOCKED → 5-6 PROTECTIVE → 7+ NORMAL（D3 recovery）
    assert cycle.loc[:4, "application_state"].tolist() == [LOCKED] * 5
    assert cycle.loc[5:6, "application_state"].tolist() == [PROTECTIVE] * 2
    assert cycle.loc[7:, "application_state"].tolist() == [NORMAL] * 28
    # 边界模式：M4→conservative_fallback，M3→history_protective_boundary
    bm = cycle["boundary_mode"].value_counts().to_dict()
    assert bm["conservative_fallback"] == 5
    assert bm["history_protective_boundary"] == 30

    # recovery_event 恰好 1 个，位于 cycle 7
    assert cycle["recovery_event"].sum() == 1
    assert bool(cycle.loc[cycle["recovery_event"], "recovery_event"].iloc[0])

    # D3 trace：完整（M4 前置 + after_diff）
    tr = trace_records(cycle, SCFG)
    assert len(tr) == 1
    row = tr.iloc[0]
    assert bool(row["m4_before"])
    assert bool(row["complete"])
    assert row["state_before"] == PROTECTIVE and row["state_after"] == NORMAL


def test_process_pool_current_only_metrics_and_kill_gates() -> None:
    sessions = [
        stable_current_only_session(sid, 35, 5.0)
        for sid in _low_budget_session_ids(SCFG, 6)
    ]
    # 短会话（history 不足）→ 纯 M4 conservative fallback
    sessions.append(stable_current_only_session("p2sess_short1", 3, 5.0))
    sessions.append(stable_current_only_session("p2sess_short2", 3, 5.0))
    pool = pd.concat(sessions, ignore_index=True)

    summary, trace_df = process_pool(
        pool, SCFG, seeds_for_pool(pool), ReplayTransform(name=NATURAL)
    )
    assert summary["m1"] == 1.0
    assert summary["m2"] == 1.0
    assert summary["m2_disp_ok"] == 1.0
    assert summary["m4"] == 0.0
    assert summary["n_diff_lock_prot"] > 0
    assert summary["n_diff_prot_normal"] > 0
    assert summary["boundary_mode_counts"]["history_protective_boundary"] > 0
    assert summary["boundary_mode_counts"]["conservative_fallback"] > 0
    assert summary["mode_counts"][M3] > 0 and summary["mode_counts"][M4] > 0
    assert trace_df["complete"].sum() >= 1
    assert summary["traces"]["n_traces_complete"] >= 1

    assert k2_verdict(SCFG, summary) == "PASS"
    assert k3_verdict(SCFG, summary) == "PASS"

    # pool_verdict（Success/Conditional/No-Go）用 PoolAgg 直接验证
    agg = PoolAgg()
    cycle = build_cycle_frame(pool, SCFG, seeds_for_pool(pool), ReplayTransform(name=NATURAL))
    agg.add(cycle)
    agg.add_traces(trace_df)
    verdict = pool_verdict(agg, SCFG)
    assert verdict in ("Success", "Conditional")


def test_measured_pilot_natural_gives_m2_branch() -> None:
    pool = stable_pilot_session("p2pilot_1", 12, actual_kw=5.0, pilot_kw=6.0)
    summary, _ = process_pool(pool, SCFG, seeds_for_pool(pool), ReplayTransform(name=NATURAL))
    # M2 出现 → response_history_boundary；history 不足的前 5 cycle → M4
    assert summary["mode_counts"][M2] > 0
    assert summary["mode_counts"][M4] > 0
    assert summary["boundary_mode_counts"]["response_history_boundary"] > 0
    assert summary["boundary_mode_counts"]["conservative_fallback"] > 0


def _caltech_replay_pool() -> pd.DataFrame:
    frames = [stable_pilot_session(f"p2r_pilot{i:02d}", 10, 5.0, 6.0) for i in range(4)]
    frames += [
        make_session(f"p2r_short{i}", "caltech", "measured_pilot", 3, actual=5.0)
        for i in range(4)
    ]
    return pd.concat(frames, ignore_index=True)


def test_replay_transforms_produce_distinct_boundary_modes() -> None:
    pool = _caltech_replay_pool()
    seed_map = seeds_for_pool(pool)
    replays: dict[str, dict] = {}
    transforms = [
        ReplayTransform(name=NATURAL),
        ReplayTransform(name=MASK, mask_pilot=True),
        ReplayTransform(name=TRUNCATE, history_limit_per_run=4),
        ReplayTransform(name=INJECT, inject_capability=True),
    ]
    for t in transforms:
        s, tr = process_pool(pool, SCFG, seed_map, t)
        replays[t.name] = s

    assert replays[NATURAL]["boundary_mode_counts"].get("response_history_boundary", 0) > 0
    assert replays[MASK]["boundary_mode_counts"].get("history_protective_boundary", 0) > 0
    assert replays[MASK]["boundary_mode_counts"].get("response_history_boundary", 0) == 0
    assert set(replays[TRUNCATE]["boundary_mode_counts"].keys()) == {"conservative_fallback"}
    assert set(replays[INJECT]["boundary_mode_counts"].keys()) == {"capability_supported_boundary"}

    # 信息面变化真的改变 boundary mode → K1 PASS
    jpl_pool = stable_current_only_session(_low_budget_session_id(), 20, 5.0)
    nat_summary, _ = process_pool(
        jpl_pool, SCFG, seeds_for_pool(jpl_pool), ReplayTransform(name=NATURAL)
    )
    assert k1_verdict(SCFG, nat_summary, replays) == "PASS"


def test_k2_fails_on_all_m4_pool() -> None:
    pool = stable_current_only_session("p2m4_short", 3, 5.0)
    summary, _ = process_pool(pool, SCFG, seeds_for_pool(pool), ReplayTransform(name=NATURAL))
    assert set(summary["boundary_mode_counts"].keys()) == {"conservative_fallback"}
    assert k2_verdict(SCFG, summary) == "PROJECT_NO_GO"


def test_k3_fails_on_no_trace() -> None:
    summary = {
        "traces": {"n_traces_complete": 0},
    }
    assert k3_verdict(SCFG, summary) == "PROJECT_NO_GO"


def test_severe_gap_reset_restarts_history() -> None:
    severe = [False] * 12
    severe[6] = True  # 第 7 分钟 severe gap → 新 run，history 重置
    pool = make_session(
        "p2gap_1", "jpl", "current_only", 12, actual=5.0, severe_gap=severe
    )
    cycle = build_cycle_frame(pool, SCFG, seeds_for_pool(pool), ReplayTransform(name=NATURAL))
    # run1: 0-5（M4 0-4, M3 at 5）；run2: 6-11（M4 6-10, M3 at 11）
    assert cycle.loc[:4, "info_mode"].tolist() == [M4] * 5
    assert cycle.loc[5, "info_mode"] == M3
    assert cycle.loc[6:10, "info_mode"].tolist() == [M4] * 5
    assert cycle.loc[11, "info_mode"] == M3
    assert cycle["run_id"].nunique() == 2


def test_chunking_and_determinism() -> None:
    pool = pd.concat(
        [stable_current_only_session(_low_budget_session_id(), 20, 5.0)]
        + [stable_pilot_session(f"p2d{i:02d}", 8, 5.0, 6.0) for i in range(10)],
        ignore_index=True,
    )
    seed_map = seeds_for_pool(pool)
    s1, tr1 = process_pool(pool, SCFG, seed_map, ReplayTransform(name=NATURAL), chunk_sessions=2)
    s2, tr2 = process_pool(pool, SCFG, seed_map, ReplayTransform(name=NATURAL), chunk_sessions=100)

    keys = ["n_cycles", "n_sessions", "n_runs", "n_m1", "n_m2", "n_m3", "n_m4",
            "n_clip_ok", "n_disp_ok", "n_release_violations"]
    for k in keys:
        assert s1[k] == s2[k], f"{k}: {s1[k]} != {s2[k]}"
    assert s1["mode_counts"] == s2["mode_counts"]
    assert s1["boundary_mode_counts"] == s2["boundary_mode_counts"]
    assert s1["traces"] == s2["traces"]
    assert len(tr1) == len(tr2)

    # 结果可 JSON 序列化（step0/formal summary 直接落盘）
    json.dumps(s1, ensure_ascii=False)


def test_m1_capability_isolation() -> None:
    """capability 注入 → M1，不受 history 影响（capability 独立于 history 成立）。"""
    pool = stable_current_only_session("p2cap_1", 3, 5.0)
    cycle = build_cycle_frame(
        pool, SCFG, seeds_for_pool(pool), ReplayTransform(name=INJECT, inject_capability=True)
    )
    assert cycle["info_mode"].tolist() == [M1] * 3
    assert cycle["boundary_value"].tolist() == [SCFG.injection_value_kw] * 3


def test_mask_pilot_degrades_m2_to_m3() -> None:
    """同一 measured_pilot 池 mask 掉 pilot → M2 分支消失，转 current-only M3。"""
    pool = stable_pilot_session("p2mask_1", 12, actual_kw=5.0, pilot_kw=6.0)
    seed_map = seeds_for_pool(pool)
    nat, _ = process_pool(pool, SCFG, seed_map, ReplayTransform(name=NATURAL))
    mask, _ = process_pool(pool, SCFG, seed_map, ReplayTransform(name=MASK, mask_pilot=True))
    assert nat["mode_counts"].get(M2, 0) > 0
    assert mask["mode_counts"].get(M2, 0) == 0
    assert mask["mode_counts"].get(M3, 0) > 0
    assert mask["mode_counts"].get(M4, 0) > 0


def test_boundary_unavailable_only_on_missing_boundary() -> None:
    """M2 是 dispatch-only（无 boundary_value）→ boundary_unavailable；M3/M4 有界。"""
    pool = stable_pilot_session("p2bu_1", 12, actual_kw=5.0, pilot_kw=6.0)
    cycle = build_cycle_frame(pool, SCFG, seeds_for_pool(pool), ReplayTransform(name=NATURAL))
    m2_cycles = cycle[cycle["info_mode"] == M2]
    assert (m2_cycles["disposition"] == "boundary_unavailable").all()
    m34 = cycle[cycle["info_mode"].isin([M3, M4])]
    assert (m34["disposition"] != "boundary_unavailable").all()


# ---- 审查 2608120033 §3 回归：m4_before 联合判定 + transition invariants fail-closed ----


def _mk_trace_cycle(rows: list[dict]) -> pd.DataFrame:
    """构造最小 cycle frame 供 trace_records 单测（不经过真实 pipeline）。"""
    cols = [
        "session_id", "run_id", "timestamp_utc", "info_mode", "application_state",
        "boundary_mode", "recovery_event", "protective_bound", "budget",
        "final_cf_protective", "final_cf_normal",
    ]
    return pd.DataFrame(rows, columns=cols)


def test_m4_before_requires_m4_before_recovery() -> None:
    """M4 只出现在 recovery 之后 → m4_before=False（回归原 .any() 分开判定 bug）。"""
    t0 = pd.Timestamp("2026-01-01 00:00")
    rows = [
        # recovery 在 cycle 7；M4 只在 cycle 8（recovery 之后）出现
        {"session_id": "s", "run_id": "r", "timestamp_utc": t0 + pd.Timedelta(minutes=i),
         "info_mode": M3, "application_state": PROTECTIVE if i < 7 else NORMAL,
         "boundary_mode": "history_protective_boundary",
         "recovery_event": i == 7, "protective_bound": 5.0, "budget": 3.0,
         "final_cf_protective": 0.0, "final_cf_normal": 2.0 if i > 7 else 0.0}
        for i in range(10)
    ]
    # 把 cycle 8 改成 M4（recovery 之后）
    rows[8]["info_mode"] = M4
    cycle = _mk_trace_cycle(rows)
    tr = trace_records(cycle, SCFG)
    assert len(tr) == 1
    row = tr.iloc[0]
    # M4 全部在 recovery 之后 → m4_before 必须 False（原 bug 会因 run 内有 M4 且 run 内
    # 有 recovery 之前的行而误判 True）
    assert bool(row["m4_before"]) is False
    # complete 依赖 m4_before → False
    assert bool(row["complete"]) is False


def test_complete_rejects_anomalous_transition() -> None:
    """transition 元数据异常（state_before != PROTECTIVE）→ 不计为 complete（fail-closed）。"""
    t0 = pd.Timestamp("2026-01-01 00:00")
    rows = [
        {"session_id": "s", "run_id": "r", "timestamp_utc": t0 + pd.Timedelta(minutes=i),
         "info_mode": M4 if i < 5 else M3,
         # 故意把 recovery 前一行 state 设成 NORMAL（异常：recovery 应从 PROTECTIVE 触发）
         "application_state": NORMAL,
         "boundary_mode": "history_protective_boundary",
         "recovery_event": i == 7, "protective_bound": 5.0, "budget": 3.0,
         "final_cf_protective": 0.0, "final_cf_normal": 2.0 if i > 7 else 0.0}
        for i in range(10)
    ]
    cycle = _mk_trace_cycle(rows)
    tr = trace_records(cycle, SCFG)
    assert len(tr) == 1
    row = tr.iloc[0]
    # m4_before=True、after_diff=True，但 state_before=NORMAL（非 PROTECTIVE）→ complete 必须 False
    assert bool(row["m4_before"]) is True
    assert bool(row["after_diff"]) is True
    assert str(row["state_before"]) == NORMAL
    assert bool(row["complete"]) is False
