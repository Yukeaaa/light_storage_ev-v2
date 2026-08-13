"""D0-2 自然 pilot 变化事件库（review §5-6；最重要的数据工作）。

检测真实历史中“充电桩允许功率发生改变 → 车辆实际功率真实怎么变化”，为 M2 上调能力验证
与园区回放标定提供真实依据。目的不是预测，是寻找真实响应支持量。

规则全部从 e7_fast.yaml 冻结（PilotStepRules）；禁止在代码硬编码阈值。
- 检测用 pilot_a（A）；记录用 pilot_power_kw（kW）。
- 正向：Δpilot>=2A 且 Δpilot/pilot_before>=15%；负向同理。
- 前置稳定 3 min（pilot 无第二次变化 / actual 非缺失 / actual 无剧烈跳变）。
- 后置观察 1/3/5 min 实际响应。
- 排除：接入后最初 5 min / severe_gap 跨窗 / 非物理 / doneCharging±10min（离线标签）。
- 禁止外推（review §22）：观察到的实际变化量 = 本事件可验证的响应支持量，非车辆真实最大能力。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.e7_fast.config import E7FastConfig

_EVENT_COLUMNS = [
    "event_id", "session_id", "station_id", "site", "timestamp", "direction",
    "pilot_before_a", "pilot_after_a", "delta_pilot_a",
    "pilot_before_kw", "pilot_after_kw", "delta_pilot_kw",
    "actual_before_kw", "actual_1min_kw", "actual_3min_kw", "actual_5min_kw",
    "delta_actual_1min_kw", "delta_actual_3min_kw", "delta_actual_5min_kw",
    "history_q95_before_kw", "history_count", "connected_elapsed_min",
    "response_gain_1m", "response_gain_3m", "response_gain_5m",
    "info_mode_before", "split", "field_mode", "month",
]


def _lookup_neighbors(
    cand: pd.DataFrame, full: pd.DataFrame, lags: list[int]
) -> pd.DataFrame:
    """对每个候选事件行，按 timestamp + lag 分钟查同 session 邻居行的实际/导引/缺口等列。

    用 merge 实现（精确分钟匹配；缺失分钟 → NaN → 后续检查自然失败）。
    """
    base = cand.copy()
    lookup_cols = [
        "session_id", "timestamp_utc", "actual_power_kw", "pilot_a",
        "pilot_power_kw", "severe_gap_before", "run_id",
    ]
    lookup = full[lookup_cols].copy()
    for lag in lags:
        key_ts = base["timestamp_utc"] + pd.Timedelta(minutes=lag)
        tmp = base[["session_id"]].copy()
        tmp["_lookup_ts"] = key_ts
        merged = tmp.merge(
            lookup,
            left_on=["session_id", "_lookup_ts"],
            right_on=["session_id", "timestamp_utc"],
            how="left",
            suffixes=("", f"_lag{lag}"),
        )
        for col in ["actual_power_kw", "pilot_a", "pilot_power_kw", "severe_gap_before", "run_id"]:
            src = (
                col
                if col in merged.columns and f"{col}_lag{lag}" not in merged.columns
                else f"{col}_lag{lag}"
            )
            base[f"{col}_lag{lag}"] = merged[src].to_numpy()
    return base


def extract_pilot_step_events(
    df_info: pd.DataFrame, cfg: E7FastConfig
) -> pd.DataFrame:
    """从已附加 info_class 的 1-min 表提取自然 pilot step 事件。

    输入：attach_info_class 的输出（含 run_id / info_mode / q95_history_kw）。
    输出：每事件一行，列见 _EVENT_COLUMNS；未通过排除的候选不入表。
    """
    rules = cfg.d0.pilot_rules
    guard = cfg.power_guard

    # 只处理有 pilot 观测的 session
    pilot_sessions = df_info.loc[df_info["pilot_available"], "session_id"].unique()
    df = df_info[df_info["session_id"].isin(pilot_sessions)].sort_values(
        ["session_id", "timestamp_utc"], kind="stable"
    ).copy()

    grp = df.groupby(["session_id", "run_id"], sort=False)
    df["pilot_a_before"] = grp["pilot_a"].shift(1)
    df["delta_pilot_a"] = df["pilot_a"] - df["pilot_a_before"]
    df["delta_time_min"] = grp["timestamp_utc"].diff().dt.total_seconds() / 60.0
    df["pilot_kw_before"] = grp["pilot_power_kw"].shift(1)
    df["delta_pilot_kw"] = df["pilot_power_kw"] - df["pilot_kw_before"]

    valid_step = (
        df["pilot_available"]
        & df["pilot_a_before"].notna()
        & (df["pilot_a_before"] > 0)
        & (df["delta_time_min"] == 1.0)
    )
    pos = valid_step & (df["delta_pilot_a"] >= rules.pos_delta_a_min) & (
        df["delta_pilot_a"] / df["pilot_a_before"] >= rules.pos_rel_ratio_min
    )
    neg = valid_step & (df["delta_pilot_a"] <= rules.neg_delta_a_max) & (
        df["delta_pilot_a"].abs() / df["pilot_a_before"] >= rules.neg_rel_ratio_min
    )
    cand_mask = pos | neg
    cand = df[cand_mask].copy()
    if cand.empty:
        return pd.DataFrame(columns=_EVENT_COLUMNS)
    cand["direction"] = np.where(pos[cand_mask], "up", "down")

    # 查邻居：前置 -3/-2/-1，后置 +1/+3/+5
    cand = _lookup_neighbors(cand, df, [-3, -2, -1, 1, 3, 5])

    # --- 前置稳定（review §5）---
    pno = rules.pre_pilot_no_second_change_a   # pilot 无第二次变化阈值
    ano = rules.pre_actual_no_big_jump_kw      # actual 无剧烈跳变阈值
    pre_ok = (
        cand["run_id_lag-3"].eq(cand["run_id"])
        & cand["run_id_lag-2"].eq(cand["run_id"])
        & cand["run_id_lag-1"].eq(cand["run_id"])
        & cand["actual_power_kw_lag-3"].notna()
        & cand["actual_power_kw_lag-2"].notna()
        & cand["actual_power_kw_lag-1"].notna()
        & (cand["pilot_a_lag-2"].sub(cand["pilot_a_lag-1"]).abs() < pno)
        & (cand["pilot_a_lag-3"].sub(cand["pilot_a_lag-2"]).abs() < pno)
        & (cand["actual_power_kw_lag-2"].sub(cand["actual_power_kw_lag-1"]).abs() < ano)
        & (cand["actual_power_kw_lag-3"].sub(cand["actual_power_kw_lag-2"]).abs() < ano)
    )

    # --- 后置观察：1/3/5 min 同 run 且 actual 非缺失 ---
    post_ok = (
        cand["run_id_lag1"].eq(cand["run_id"])
        & cand["run_id_lag3"].eq(cand["run_id"])
        & cand["run_id_lag5"].eq(cand["run_id"])
        & cand["actual_power_kw_lag1"].notna()
        & cand["actual_power_kw_lag3"].notna()
        & cand["actual_power_kw_lag5"].notna()
    )

    # --- 缺口跨窗排除 ---
    gap_cols = [f"severe_gap_before_lag{lag}" for lag in [-3, -2, -1, 1, 3, 5]]
    no_gap = ~cand[gap_cols].any(axis=1) & ~cand["severe_gap_before"].fillna(True)

    # --- 排除：接入后最初 5 min ---
    not_first = cand["connected_elapsed_min"] >= rules.first_connect_min

    # --- 排除：非物理功率 ---
    actual_before = cand["actual_power_kw_lag-1"]
    non_physical = (
        actual_before.lt(guard.actual_kw_min)
        | actual_before.gt(guard.actual_kw_max)
        | cand["pilot_a"].gt(guard.pilot_a_max)
        | cand["pilot_a_before"].gt(guard.pilot_a_max)
    )

    # --- 排除：doneCharging±10min（离线标签；绝不作在线特征）---
    done = pd.to_datetime(cand["done_charging_time"], errors="coerce", utc=True)
    done_diff_min = (cand["timestamp_utc"] - done).dt.total_seconds().abs() / 60.0
    not_near_done = done_diff_min.isna() | (done_diff_min >= rules.offline_done_window_min)

    usable = pre_ok & post_ok & no_gap & not_first & ~non_physical & not_near_done
    events = cand[usable].copy()
    if events.empty:
        return pd.DataFrame(columns=_EVENT_COLUMNS)

    # --- 组装事件记录（review §6）---
    out = pd.DataFrame(index=events.index)
    out["session_id"] = events["session_id"]
    out["station_id"] = events["station_id"]
    out["site"] = events["site"]
    out["timestamp"] = events["timestamp_utc"]
    out["direction"] = events["direction"]
    out["pilot_before_a"] = events["pilot_a_before"]
    out["pilot_after_a"] = events["pilot_a"]
    out["delta_pilot_a"] = events["delta_pilot_a"]
    out["pilot_before_kw"] = events["pilot_kw_before"]
    out["pilot_after_kw"] = events["pilot_power_kw"]
    out["delta_pilot_kw"] = events["delta_pilot_kw"]
    out["actual_before_kw"] = events["actual_power_kw_lag-1"]
    out["actual_1min_kw"] = events["actual_power_kw_lag1"]
    out["actual_3min_kw"] = events["actual_power_kw_lag3"]
    out["actual_5min_kw"] = events["actual_power_kw_lag5"]
    out["delta_actual_1min_kw"] = out["actual_1min_kw"] - out["actual_before_kw"]
    out["delta_actual_3min_kw"] = out["actual_3min_kw"] - out["actual_before_kw"]
    out["delta_actual_5min_kw"] = out["actual_5min_kw"] - out["actual_before_kw"]
    out["history_q95_before_kw"] = events["q95_history_kw"]
    out["history_count"] = events["history_count"]
    out["connected_elapsed_min"] = events["connected_elapsed_min"]
    safe_dp = out["delta_pilot_kw"].replace(0.0, np.nan)
    out["response_gain_1m"] = out["delta_actual_1min_kw"] / safe_dp
    out["response_gain_3m"] = out["delta_actual_3min_kw"] / safe_dp
    out["response_gain_5m"] = out["delta_actual_5min_kw"] / safe_dp
    out["info_mode_before"] = events["info_mode"]
    out["split"] = events["split"]
    out["field_mode"] = events["field_mode"]
    out["month"] = events["timestamp_utc"].dt.strftime("%Y-%m")
    out = out.reset_index(drop=True)
    out["event_id"] = (
        out["session_id"].astype(str) + "|"
        + out["timestamp"].astype(str) + "|" + out["direction"]
    )
    return out[_EVENT_COLUMNS]
