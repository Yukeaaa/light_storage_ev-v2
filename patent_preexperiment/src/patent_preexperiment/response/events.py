"""E1-Lite 状态分段（V2.1 §6.2/§6.3）：在线可用标记 + 离线排伪标记分离。"""

from __future__ import annotations

import numpy as np
import pandas as pd

GAP_ENERGY_PER_MIN = 1 / 60.0  # kWh per (kW * minute)


class GapThresholds:
    def __init__(
        self, p_on_kw: float, delta_r: float, delta_p_kw: float, t_event_min: int,
        initial_exclusion_min: int, tail_exclusion_min: int, pilot_active_min_a: float = 1.0,
    ):
        self.p_on_kw = p_on_kw
        self.delta_r = delta_r
        self.delta_p_kw = delta_p_kw
        self.t_event_min = t_event_min
        self.initial_exclusion_min = initial_exclusion_min
        self.tail_exclusion_min = tail_exclusion_min
        self.pilot_active_min_a = pilot_active_min_a

    @classmethod
    def from_cfg(cls, cfg: dict) -> GapThresholds:
        pt = cfg["primary_threshold"]
        return cls(
            p_on_kw=pt["P_on_kw"],
            delta_r=pt["delta_r"],
            delta_p_kw=pt["delta_p_kw"],
            t_event_min=pt["T_event_min"],
            initial_exclusion_min=pt["initial_exclusion_min"],
            tail_exclusion_min=pt["tail_exclusion_min"],
            pilot_active_min_a=cfg.get("pilot_active_min_a", 1.0),
        )


def classify(df1m: pd.DataFrame, thr: GapThresholds) -> pd.DataFrame:
    """输出每分钟布尔标记；初始/尾段仅用于排除，不进入在线特征。"""
    out = df1m.copy()
    actual = out["actual_power_kw"].astype(float)
    pilot = out["pilot_power_kw"].astype(float)
    g = (pilot - actual).clip(lower=0.0)
    denom = pilot.replace(0.0, np.nan)
    ratio_gap = (g / denom) > thr.delta_r

    out["charging_active"] = (actual >= thr.p_on_kw) & (out["current_a"] > 0)
    out["initial_ramp"] = out["connected_elapsed_min"] < thr.initial_exclusion_min
    out["tail"] = out["minutes_from_end"] <= thr.tail_exclusion_min
    out["quality_ok"] = ~out["gap_flag"]
    out["pilot_active"] = out["pilot_available"] & (out["pilot_a"] >= thr.pilot_active_min_a)
    out["ratio_gap"] = ratio_gap.fillna(False)
    out["abs_gap"] = g > thr.delta_p_kw
    out["gap_candidate"] = (
        out["charging_active"]
        & ~out["initial_ramp"]
        & ~out["tail"]
        & out["quality_ok"]
        & out["pilot_active"]
        & out["ratio_gap"]
        & out["abs_gap"]
    )
    return out


def _runs(mask: pd.Series) -> list[tuple[int, int]]:
    """返回连续 True 段的位置区间 [a,b)。"""
    vals = mask.to_numpy()
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, v in enumerate(vals):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(vals)))
    return runs


def detect_gap_events(
    df1m: pd.DataFrame, thr: GapThresholds, phase_col: str | None = None,
) -> pd.DataFrame:
    """在标记表上切出连续 gap 事件（持续 >= T_event 分钟）。

    phase_col 给定（如 "phase"）时，事件连续段在阶段变化处强制切断，
    各阶段段内重新执行持续 >= T_event 规则（K1.2-B）。事件行携带该阶段。
    """
    labeled = classify(df1m, thr)
    rows: list[dict] = []
    keys = ["session_id"] if phase_col is None else ["session_id", phase_col]
    for _key, sess in labeled.groupby(keys, sort=False):
        phase = sess[phase_col].iloc[0] if phase_col is not None else None
        mask = sess["gap_candidate"]
        for a, b in _runs(mask):
            dur = b - a
            if dur < thr.t_event_min:
                continue
            ev = sess.iloc[a : b]
            g = (ev["pilot_power_kw"] - ev["actual_power_kw"]).clip(lower=0.0)
            row: dict = {
                "session_id": sess["session_id"].iloc[0],
                "site": sess["site"].iloc[0],
                "garage": sess["garage"].iloc[0],
                "station_id": sess["station_id"].iloc[0],
                "start_utc": ev["timestamp_utc"].iloc[0],
                "end_utc": ev["timestamp_utc"].iloc[-1],
                "duration_min": int(dur),
                "max_gap_kw": float(g.max()),
                "median_gap_kw": float(g.median()),
                "p95_gap_kw": float(g.quantile(0.95)),
                "gap_energy_kwh": float(g.sum() * GAP_ENERGY_PER_MIN),
                "working_power_median_kw": float(ev["actual_power_kw"].median()),
                "month": str(ev["timestamp_utc"].iloc[0])[:7],
            }
            if phase_col is not None:
                row["phase"] = phase
            rows.append(row)
    if not rows:
        cols = [
            "session_id", "site", "garage", "station_id", "start_utc", "end_utc",
            "duration_min", "max_gap_kw", "median_gap_kw", "p95_gap_kw", "gap_energy_kwh",
            "working_power_median_kw", "month",
        ]
        if phase_col is not None:
            cols.append("phase")
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)
