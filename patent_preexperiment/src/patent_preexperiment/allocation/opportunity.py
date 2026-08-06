"""E3-Lite 无泄漏机会审计核心（K1.1-B/C/D）。

- 先聚合 5min 周期 → 全部历史统计执行 shift(1)：决策时刻只可见已结束周期。
- 指标 A（candidate_redistribution_window）：∃ 会话预算差值≥margin，且同池 ≥2 活跃会话。
  仅"并发候选修正窗口"，不含吸收假设（K1 唯一可用口径）。
- 指标 B（supported_redistribution_window）：需 E1-Full 自然 pilot 阶跃验证，此处仅输出参考上界，
  不构成门依据。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CYCLE_MIN = 5
MARGIN_KW = 0.5
ROLL_CYCLES = 12  # 60 分钟 / 5 分钟
ROLL_Q = 0.90
ACTIVE_KW = 0.5  # 会话在该周期活跃：实际功率均值 ≥0.5 kW
PILOT_PRESENT_MIN = 0.5  # 周期内 pilot 非空占比下限

PROXIES = ["A0_avg", "A1_pilot", "A2_prev_actual", "A3_rolling_quantile", "A4_min_pilot_quantile"]


def build_cycles(df: pd.DataFrame) -> pd.DataFrame:
    """分钟表 → 5min 周期表，历史统计全部滞后一期（无当前周期信息泄漏）。"""
    d = df.copy()
    d["actual"] = d["actual_power_kw"].astype(float)
    d["pilot"] = d["pilot_power_kw"].astype(float)
    d["_pilot_ok"] = d["pilot"].notna().astype(float)
    d["_active_ok"] = (d["actual"] >= ACTIVE_KW).astype(float)
    d["cycle"] = d["timestamp_utc"].dt.floor(f"{CYCLE_MIN}min")
    d["day"] = d["timestamp_utc"].dt.date.astype(str)
    d["month"] = d["timestamp_utc"].astype(str).str[:7]

    cyc = (
        d.groupby(["site", "garage", "session_id", "cycle"], sort=False)
        .agg(
            actual=("actual", "mean"),
            pilot=("pilot", "mean"),
            pilot_present=("_pilot_ok", "mean"),
            active_share=("_active_ok", "mean"),
            day=("day", "first"),
            month=("month", "first"),
        )
        .reset_index()
    )
    cyc["active"] = cyc["active_share"] > 0.5
    cyc = cyc[cyc["active"]].copy()
    cyc = cyc.sort_values(["site", "garage", "session_id", "cycle"])
    g = cyc.groupby(["site", "garage", "session_id"], sort=False)
    cyc["actual_prev"] = g["actual"].shift(1)
    cyc["actual_rollmax"] = g["actual"].shift(1).rolling(ROLL_CYCLES, min_periods=2).max()
    cyc["actual_rollq"] = g["actual"].shift(1).rolling(ROLL_CYCLES, min_periods=2).quantile(ROLL_Q)
    return cyc


def compute_pool_stats(cyc: pd.DataFrame) -> pd.DataFrame:
    """池×周期 级统计：活跃会话数、池 pilot 和、池 pilot 覆盖。"""
    pool = cyc.groupby(["site", "garage", "cycle"], sort=False).agg(
        n_active=("session_id", "size"),
        pool_pilot=("pilot", "sum"),
        pool_pilot_present=("pilot_present", "mean"),
    ).reset_index()
    return pool


def compute_proxies(cyc: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
    """每会话×周期 预算代理。A0/A1/A4 依赖 pilot（pilot 缺失→NaN）。"""
    cyc = cyc.merge(pool, on=["site", "garage", "cycle"], how="left")
    pilot_cover = cyc["pool_pilot_present"] >= PILOT_PRESENT_MIN
    cyc["A0_avg"] = (cyc["pool_pilot"] / cyc["n_active"]).where(pilot_cover)
    cyc["A1_pilot"] = cyc["pilot"].where(cyc["pilot_present"] > PILOT_PRESENT_MIN)
    cyc["A2_prev_actual"] = cyc["actual_prev"]
    cyc["A3_rolling_quantile"] = cyc["actual_rollq"]
    cyc["A4_min_pilot_quantile"] = np.minimum(cyc["pilot"], cyc["actual_rollq"]).where(
        (cyc["pilot_present"] > PILOT_PRESENT_MIN) & cyc["actual_rollq"].notna()
    )
    return cyc


def candidate_windows(cyc: pd.DataFrame, proxies: list[str] | None = None) -> pd.DataFrame:
    """每池×周期 指标 A：并发候选修正窗口（n_slack≥1 且 n_active≥2）。

    输出每代理：n_slack / candidate / candidate_energy_kwh（=预算差值，无吸收假设）。
    另输出 supported_ref_energy_kwh（历史支持域上界参考，未验证，不构成门依据）。
    """
    proxies = proxies or PROXIES
    rows: list[pd.DataFrame] = []
    for name in proxies:
        b = cyc[name].to_numpy()
        has = np.isfinite(b)
        slack = np.where(has, np.clip(b - cyc["actual"].to_numpy(), 0, None), np.nan)
        headroom = np.where(has, np.clip(cyc["actual_rollmax"].to_numpy() - b, 0, None), np.nan)
        tmp = cyc.assign(
            n_slack=np.where(has & (slack >= MARGIN_KW), 1, 0),
            total_slack=np.nan_to_num(slack, nan=0.0),
            total_headroom=np.nan_to_num(headroom, nan=0.0),
            n_budget=np.where(has, 1, 0),
        ).groupby(["site", "garage", "cycle"], sort=False).agg(
            n_slack=("n_slack", "sum"),
            total_slack=("total_slack", "sum"),
            total_headroom=("total_headroom", "sum"),
            n_budget=("n_budget", "sum"),
        ).reset_index()
        tmp["candidate"] = (tmp["n_slack"] >= 1) & (tmp["n_budget"] >= 2)
        tmp["candidate_energy_kwh"] = tmp["total_slack"] * CYCLE_MIN / 60.0
        tmp["candidate_energy_kwh"] = tmp["candidate_energy_kwh"].where(tmp["candidate"], 0.0)
        tmp["supported_ref_energy_kwh"] = (
            np.minimum(tmp["total_slack"], tmp["total_headroom"]) * CYCLE_MIN / 60.0
        ).where(tmp["candidate"], 0.0)
        tmp = tmp.rename(
            columns={
                "n_slack": f"n_slack_{name}",
                "total_slack": f"slack_{name}_kwh",
                "total_headroom": f"headroom_{name}_kwh",
                "n_budget": f"n_budget_{name}",
                "candidate": f"candidate_{name}",
                "candidate_energy_kwh": f"candidate_energy_{name}_kwh",
                "supported_ref_energy_kwh": f"supported_ref_energy_{name}_kwh",
            }
        )
        rows.append(tmp)
    out = rows[0]
    for r in rows[1:]:
        out = out.merge(r, on=["site", "garage", "cycle"], how="outer")
    return out


def available_mask(cand: pd.DataFrame, pool: str, prox_list: list[str]) -> pd.Series:
    """配对比较的 eligible mask：同一比较组内所有代理都可计算的完全相同周期。"""
    m = cand["pool"] == pool
    for p in prox_list:
        m = m & cand[f"n_budget_{p}"].ge(1)
    return m


def build_cycle_table(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """分钟表 → 合并后的 池×周期 候选窗口表 + 会话×周期 预算代理表。"""
    cyc = build_cycles(df)
    pool = compute_pool_stats(cyc)
    prox = compute_proxies(cyc, pool)
    cyc_level = candidate_windows(prox)
    cyc_level["pool"] = cyc_level["site"] + "." + cyc_level["garage"]
    month_map = prox[["site", "garage", "cycle", "month"]].drop_duplicates()
    cyc_level = cyc_level.merge(month_map, on=["site", "garage", "cycle"], how="left")
    return cyc_level, prox
