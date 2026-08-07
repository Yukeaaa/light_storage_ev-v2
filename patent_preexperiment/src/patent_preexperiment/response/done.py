"""K1.1-A：done-relative 阶段划分与离线完成锚点推断（仅排伪，不入在线特征）。

评审要求：真正需要排除的是"充电完成/持续降流"区间，而非物理拔枪前尾段。
核心运行段 = 距 doneChargingTime > CORE_MARGIN_MIN(120) 分钟。
done 缺失时用离线锚点推断：功率 < LOW_KW 持续 SUSTAIN_MIN 分钟且此后未恢复到工作功率。
推断值只能用于离线排伪，禁止进入在线特征。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

LOW_KW = 0.3
SUSTAIN_MIN = 20
CORE_MARGIN_MIN = 120.0  # 核心运行段：距 done > 120 分钟
MID_MIN = 30.0  # 完成前中段：30 < 距 done <= 120
TAIL_MIN = 30.0  # 完成前尾段：0 <= 距 done <= 30

PHASE_CORE = "core_run_segment"
PHASE_MID = "pre_done_mid"
PHASE_TAIL = "pre_done_tail"
PHASE_POST = "post_done"
PHASE_MISSING = "done_missing"

PHASE_ORDER = [PHASE_POST, PHASE_TAIL, PHASE_MID, PHASE_CORE, PHASE_MISSING]


def minutes_to_done_of(
    done: pd.Timestamp, ts: pd.Series
) -> pd.Series:
    """返回 (done - ts) 的分钟数；done 为 None 时返回全 NaN。"""
    if done is None:
        return pd.Series(np.nan, index=ts.index, dtype="float64")
    secs = (done - ts).dt.total_seconds()
    return pd.Series(secs.to_numpy() / 60.0, index=ts.index, dtype="float64")


def infer_done(
    df_sess: pd.DataFrame, p_on_kw: float, low_kw: float = LOW_KW, sustain_min: int = SUSTAIN_MIN
) -> pd.Timestamp | None:
    """离线推断单会话完成时间（仅离线排伪用）。

    口径：最后一个工作功率(actual>=p_on_kw)分钟之后，第一个
    [t, t+sustain_min) 全部 < low_kw 的窗口起点。
    """
    a = df_sess["actual_power_kw"].astype(float).to_numpy()
    n = len(a)
    working = a >= p_on_kw
    if not working.any():
        return None
    last_work = int(np.flatnonzero(working).max())
    low = a < low_kw
    for t in range(last_work + 1, n - sustain_min + 1):
        if low[t : t + sustain_min].all():
            ts = df_sess["timestamp_utc"].iloc[t]
            return pd.Timestamp(ts)
    return None


def add_done_phases(
    df: pd.DataFrame,
    p_on_kw: float,
    low_kw: float = LOW_KW,
    sustain_min: int = SUSTAIN_MIN,
    core_margin_min: float = CORE_MARGIN_MIN,
    mid_min: float = MID_MIN,
    tail_min: float = TAIL_MIN,
) -> pd.DataFrame:
    """在分钟表上增加 done-relative 标记与阶段标签。"""
    out = df.copy()
    out["minutes_to_done"] = np.nan
    out["post_done"] = False
    out["done_anchor_source"] = "missing"

    api = out["done_charging_time"].notna()
    if api.any():
        mtd = (
            out.loc[api, "done_charging_time"] - out.loc[api, "timestamp_utc"]
        ).dt.total_seconds() / 60.0
        out.loc[api, "minutes_to_done"] = mtd.to_numpy()
        out.loc[api, "post_done"] = (mtd.to_numpy() < 0)
        out.loc[api, "done_anchor_source"] = "api"

    # done 缺失会话：离线推断（仅排伪）——对全会话分钟统一赋值
    missing_ids = out.loc[~api, "session_id"].unique()
    for sid in missing_ids:
        sub = out[out["session_id"] == sid]
        d = infer_done(sub, p_on_kw, low_kw, sustain_min)
        if d is None:
            continue
        idx = sub.index
        mtd = (d - sub.loc[idx, "timestamp_utc"]).dt.total_seconds() / 60.0
        out.loc[idx, "minutes_to_done"] = mtd.to_numpy()
        out.loc[idx, "post_done"] = (mtd.to_numpy() < 0)
        out.loc[idx, "done_anchor_source"] = "inferred"

    mtd = out["minutes_to_done"]
    out["phase"] = np.select(
        [
            out["post_done"],
            mtd > core_margin_min,
            mtd > mid_min,
            mtd >= 0,
        ],
        [PHASE_POST, PHASE_CORE, PHASE_MID, PHASE_TAIL],
        default=PHASE_MISSING,
    )
    return out


def phase_for_minutes(mtd: float) -> str:
    """分钟到 done 距离 → 阶段（纯函数，供测试/事件分类）。"""
    if mtd is None or np.isnan(mtd):
        return PHASE_MISSING
    if mtd < 0:
        return PHASE_POST
    if mtd > CORE_MARGIN_MIN:
        return PHASE_CORE
    if mtd > MID_MIN:
        return PHASE_MID
    return PHASE_TAIL


def done_anchored_summary(events: pd.DataFrame) -> dict[str, Any]:
    """事件按 done-relative 阶段汇总（K1.2.1-P1-1 修复）。

    修复：energy_kwh_post_done 只含 post_done 能量，不再把 pre_done_tail 能量
    误记到 post_done 名下（此前 n_post_done=0 却报 1141kWh 的自相矛盾）。
    """
    post = events[events["event_phase"] == PHASE_POST]
    tail = events[events["event_phase"] == PHASE_TAIL]
    mid = events[events["event_phase"] == PHASE_MID]
    core = events[events["event_phase"] == PHASE_CORE]
    near_done = events[events["event_phase"].isin([PHASE_POST, PHASE_TAIL, PHASE_MID])]
    return {
        "n_post_done": int(len(post)),
        "n_pre_done_tail": int(len(tail)),
        "n_pre_done_mid": int(len(mid)),
        "n_core": int(len(core)),
        "share_within_120min_of_done": float(len(near_done)) / max(len(events), 1),
        "energy_kwh_post_done": float(post["gap_energy_kwh"].sum()),
        "energy_kwh_pre_done_tail": float(tail["gap_energy_kwh"].sum()),
        "energy_kwh_pre_done_mid": float(mid["gap_energy_kwh"].sum()),
    }
