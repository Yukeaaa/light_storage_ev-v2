"""K1.2.2：时间置换负对照——置换事件分子强制限制在 core_sessions 母体。

设计约束（审查结论4）：点估计、每种子置换率、bootstrap 95%CI 必须来自
**同一会话母体**。真实/置换核心事件分子在进入任何计数前先过滤到
core_sessions（与点估计 core_denom 同定义），避免"真实 core 阶段不活跃、
置换后可能在 core 阶段活跃"的母体外会话混入置换分子。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from patent_preexperiment.metrics.bootstrap import bootstrap_session_diff_ci, core_run_session_ids
from patent_preexperiment.response.done import PHASE_CORE, PHASE_MISSING, add_done_phases
from patent_preexperiment.response.events import GapThresholds, detect_gap_events

_EVENT_COLS = [
    "session_id", "site", "garage", "station_id", "start_utc", "end_utc",
    "duration_min", "max_gap_kw", "median_gap_kw", "p95_gap_kw", "gap_energy_kwh",
    "working_power_median_kw", "month", "phase", "event_phase",
]


def _events_with_phase(labeled: pd.DataFrame, thr: GapThresholds) -> pd.DataFrame:
    """检测事件并在阶段边界切断；事件行携带 event_phase。"""
    ev = detect_gap_events(labeled, thr, phase_col="phase")
    if len(ev):
        ev["event_phase"] = ev["phase"].fillna(PHASE_MISSING)
    else:
        ev["event_phase"] = pd.Series(dtype=str)
    return ev


def permutation_negative_control(
    labeled: pd.DataFrame,
    thr: GapThresholds,
    real_core_events: pd.DataFrame,
    perm_seeds: Sequence[int],
    bootstrap_seed: int = 42,
    n_boot: int = 2000,
) -> dict:
    """会话内时间置换负对照：输出 diff/ratio 与多种子 bootstrap 95%CI。

    口径统一：`real_core_session_rate`、每种子置换率、bootstrap 全部由同一布尔
    矩阵（事件会话标记 × core_sessions 母体）计算，结构上保证
    点估计母体 = 每种子置换率母体 = bootstrap 母体 = core_denom。

    Args:
        labeled: 已分类并带 done 阶段标签的分钟表。
        thr: 事件阈值。
        real_core_events: 真实核心运行段事件表（event_phase 过滤后）。
        perm_seeds: 置换随机种子列表。
        bootstrap_seed: bootstrap 重采样种子。
        n_boot: bootstrap 重采样次数。

    Returns:
        dict：含 real_core_session_rate / perm_rate_mean / perm_rate_per_seed /
        diff_real_minus_perm / ratio_real_over_perm / diff_bootstrap_ci95 /
        bootstrap_n_sessions / 母体过滤诊断字段；内部键 _real_has / _perm_has /
        perm_core_reference（调用方负责在落 JSON 前剥离）。
    """
    sessions = core_run_session_ids(labeled)
    core_session_set = set(sessions)
    n_core = int(len(sessions))

    if n_core == 0:
        return {
            "evaluable": False,
            "reason": "no_core_sessions",
            "real_core_session_rate": 0.0,
            "perm_rate_mean": 0.0,
            "perm_rate_per_seed": [
                {
                    "seed": int(seed),
                    "core_events": 0,
                    "core_session_rate": 0.0,
                    "n_perm_event_sessions_before_population_filter": 0,
                    "n_perm_event_sessions_outside_core_population": 0,
                    "n_perm_event_sessions_after_population_filter": 0,
                }
                for seed in perm_seeds
            ],
            "diff_real_minus_perm": 0.0,
            "ratio_real_over_perm": 0.0,
            "diff_bootstrap_ci95": [0.0, 0.0],
            "bootstrap_n_sessions": 0,
            "n_perm_event_sessions_before_population_filter_total": 0,
            "n_perm_event_sessions_outside_core_population_total": 0,
            "n_perm_event_sessions_after_population_filter_total": 0,
            "interpretation": (
                "无核心运行窗口会话，负对照不可评估（evaluable=False, no_core_sessions）；"
                "调用方应跳过该池/月，避免空数组均值产生 NaN。"
            ),
            "_real_has": np.empty(0, dtype=bool),
            "_perm_has": np.empty((len(perm_seeds), 0), dtype=bool),
            "perm_core_reference": pd.DataFrame(columns=_EVENT_COLS),
        }

    real_core_sess = set(real_core_events["session_id"].unique()) & core_session_set
    real_has = np.isin(sessions, list(real_core_sess))
    real_rate = float(real_has.mean())

    per_seed: list[dict] = []
    perm_core_frames: dict[int, pd.DataFrame] = {}
    for s, seed in enumerate(perm_seeds):
        rng = np.random.default_rng(seed)
        perm = labeled.copy()
        perm["actual_power_kw"] = perm.groupby("session_id", group_keys=False)[
            "actual_power_kw"
        ].apply(lambda x, rng=rng: pd.Series(rng.permutation(x.to_numpy()), index=x.index))
        perm = add_done_phases(perm, thr.p_on_kw)
        core = _events_with_phase(perm, thr)
        core = core[core["event_phase"] == PHASE_CORE]
        before_sess = set(core["session_id"].unique())
        core = core[core["session_id"].isin(core_session_set)]
        after_sess = set(core["session_id"].unique())
        outside_sess = before_sess - core_session_set
        perm_core_frames[s] = core
        per_seed.append({
            "seed": seed,
            "core_events": int(len(core)),
            "core_session_rate": len(after_sess) / max(n_core, 1),
            "n_perm_event_sessions_before_population_filter": int(len(before_sess)),
            "n_perm_event_sessions_outside_core_population": int(len(outside_sess)),
            "n_perm_event_sessions_after_population_filter": int(len(after_sess)),
        })

    perm_has = np.stack([
        np.isin(sessions, list(perm_core_frames[s]["session_id"].unique()))
        for s in perm_core_frames
    ])
    perm_rates = perm_has.mean(axis=1)
    mean_perm = float(perm_rates.mean())
    diff = float(real_rate - mean_perm)
    ratio = float(real_rate / max(mean_perm, 1e-9))
    lo, hi = bootstrap_session_diff_ci(real_has, perm_has, seed=bootstrap_seed, n_boot=n_boot)

    return {
        "evaluable": True,
        "reason": None,
        "real_core_session_rate": real_rate,
        "perm_rate_mean": mean_perm,
        "perm_rate_per_seed": per_seed,
        "diff_real_minus_perm": diff,
        "ratio_real_over_perm": ratio,
        "diff_bootstrap_ci95": [float(lo), float(hi)],
        "bootstrap_n_sessions": n_core,
        "n_perm_event_sessions_before_population_filter_total": int(
            sum(p["n_perm_event_sessions_before_population_filter"] for p in per_seed)
        ),
        "n_perm_event_sessions_outside_core_population_total": int(
            sum(p["n_perm_event_sessions_outside_core_population"] for p in per_seed)
        ),
        "n_perm_event_sessions_after_population_filter_total": int(
            sum(p["n_perm_event_sessions_after_population_filter"] for p in per_seed)
        ),
        "interpretation": (
            "真实时序显著增强事件（diff CI 下界>0），但 pilot/actual 边际分布本身"
            "也可产生一定事件率；不得表述为'完全排除时序伪相关'。"
            "bootstrap 母体=有核心运行窗口会话（同 core_denom）；置换事件分子已强制"
            "限制在该母体，点估计/每种子置换率/CI 均由同一布尔矩阵计算（K1.2.2）。"
        ),
        "_real_has": real_has,
        "_perm_has": perm_has,
        "perm_core_reference": perm_core_frames[0],
    }
