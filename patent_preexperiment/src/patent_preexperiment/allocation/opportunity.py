"""E3-Lite 无泄漏机会审计核心（K1.1-B/C/D + K1.2-A/C 连续时间历史与精确配对）。

K1.2 修正（审查结论2）：
- 每会话补齐连续 5 分钟网格；非活跃但连接的周期计入历史（不再先删活跃）。
- shift(1)/rolling 全部在 (session, run) 组内完成，杜绝跨会话污染；
  run 在任何 5min 网格断档处断开（缺失桶即冷启动、历史失效；等效'>5min 缺口'规则）。
- 预算代理只使用 <= 上一周期信息：A0 用池上一周期 pilot/活跃数，A1 用 pilot_prev，
  A2 用 actual_prev（严格上一连续 5min 周期），A3 用上一滚动分位，A4 = min(pilot_prev, 滚动分位)。
- 当前活跃(active)只作评价标签（候选条件 n_active>=2），不进入预算代理。
- 指标 A（candidate_redistribution_window）：∃ 会话预算差值≥margin 且同池 ≥2 活跃会话，
  仅"并发候选修正窗口"，不含吸收假设（K1 唯一门依据）。
- 指标 B（supported_redistribution_window）：需 E1-Full 自然 pilot 阶跃验证，此处仅输出参考上界。
- 精确配对：eligible_mask 在 会话×周期 层求代理交集，所有代理在完全相同会话集合上评估。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CYCLE_MIN = 5
MARGIN_KW = 0.5
ROLL_CYCLES = 12  # 60 分钟 / 5 分钟
ROLL_Q = 0.90
ACTIVE_KW = 0.5  # 会话在该周期活跃：实际功率均值 ≥0.5 kW
PILOT_PRESENT_MIN = 0.5  # 池上一周期 pilot 非空占比下限
# 冷启动规则：任何 5min 网格断档（缺失桶）即历史失效（等效 >5min 缺口，严格口径）

PROXIES = ["A0_avg", "A1_pilot", "A2_prev_actual", "A3_rolling_quantile", "A4_min_pilot_quantile"]


def _pad_grid(cyc: pd.DataFrame) -> pd.DataFrame:
    """每会话补齐连续 5 分钟网格（缺口桶 actual 为 NaN）。"""
    cyc = cyc.sort_values(["site", "garage", "session_id", "cycle"])
    mm = cyc.groupby(["site", "garage", "session_id"])["cycle"].agg(["min", "max"]).reset_index()
    n_steps = ((mm["max"] - mm["min"]).dt.total_seconds() / 60.0 / CYCLE_MIN).astype(int) + 1
    reps = mm.loc[
        mm.index.repeat(n_steps), ["site", "garage", "session_id", "min"]
    ].reset_index(drop=True)
    reps["_k"] = reps.groupby(["site", "garage", "session_id"]).cumcount()
    reps["cycle"] = reps["min"] + pd.to_timedelta(reps["_k"] * CYCLE_MIN, unit="min")
    grid = reps[["site", "garage", "session_id", "cycle"]]
    out = grid.merge(cyc, on=["site", "garage", "session_id", "cycle"], how="left")
    out = out.sort_values(["site", "garage", "session_id", "cycle"])
    return out


def build_cycles(df: pd.DataFrame) -> pd.DataFrame:
    """分钟表 → 5min 周期表（连续网格，历史全部滞后一期，无当前周期信息泄漏）。

    输出含 active（当前活跃，评价标签）、actual_prev/pilot_prev/active_prev 与
    actual_rollmax/actual_rollq（上一窗口），全部在 (session, run) 组内计算。
    """
    d = df.copy()
    d["actual"] = d["actual_power_kw"].astype(float)
    d["pilot"] = d["pilot_power_kw"].astype(float)
    d["_pilot_ok"] = d["pilot"].notna().astype(float)
    d["_active_ok"] = (d["actual"] >= ACTIVE_KW).astype(float)
    d["cycle"] = d["timestamp_utc"].dt.floor(f"{CYCLE_MIN}min")
    d["month"] = d["cycle"].astype(str).str[:7]
    d["month_conn"] = d.groupby("session_id")["timestamp_utc"].transform("min").astype(str).str[:7]

    cyc = (
        d.groupby(["site", "garage", "session_id", "cycle"], sort=False)
        .agg(
            actual=("actual", "mean"),
            pilot=("pilot", "mean"),
            pilot_present=("_pilot_ok", "mean"),
            active_share=("_active_ok", "mean"),
            month=("month", "first"),
            month_conn=("month_conn", "first"),
        )
        .reset_index()
    )
    cyc["day"] = cyc["cycle"].astype(str).str[:10]
    padded = _pad_grid(cyc)
    padded["active"] = padded["active_share"].gt(0.5).fillna(False)
    padded["_gap"] = padded["actual"].isna()

    sess_key = ["site", "garage", "session_id"]
    padded["_prev_missing"] = padded.groupby(sess_key, sort=False)["_gap"].shift(1)
    padded["_break"] = padded["_prev_missing"].fillna(True) | padded["_gap"]
    padded["_run"] = padded.groupby(sess_key, sort=False)["_break"].cumsum()

    run_key = sess_key + ["_run"]
    padded["actual_prev"] = padded.groupby(run_key, sort=False)["actual"].shift(1)
    padded["pilot_prev"] = padded.groupby(run_key, sort=False)["pilot"].shift(1)
    padded["active_prev"] = padded.groupby(run_key, sort=False)["active"].shift(1)
    padded["pilot_prev_present"] = padded.groupby(run_key, sort=False)["pilot"].transform(
        lambda s: s.shift(1).notna()
    )
    padded["actual_rollmax"] = padded.groupby(run_key, sort=False)["actual"].transform(
        lambda s: s.shift(1).rolling(ROLL_CYCLES, min_periods=2).max()
    )
    padded["actual_rollq"] = padded.groupby(run_key, sort=False)["actual"].transform(
        lambda s: s.shift(1).rolling(ROLL_CYCLES, min_periods=2).quantile(ROLL_Q)
    )

    out = padded[padded["actual"].notna()].copy()
    out = out.drop(columns=["_gap", "_prev_missing", "_break", "_run"])
    return out


def compute_pool_stats(cyc: pd.DataFrame) -> pd.DataFrame:
    """池×周期 级统计（全部只用上一周期信息 + 当前活跃评价标签）。"""
    pool = cyc.groupby(["site", "garage", "cycle"], sort=False).agg(
        n_active=("active", "sum"),
        n_connected=("session_id", "size"),
        n_active_prev=("active_prev", "sum"),
        pool_pilot_prev=("pilot_prev", "sum"),
        pool_pilot_prev_present=("pilot_prev_present", "mean"),
    ).reset_index()
    return pool


def compute_proxies(cyc: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
    """每会话×周期 预算代理（只使用 <= 上一周期信息）。"""
    cyc = cyc.merge(pool, on=["site", "garage", "cycle"], how="left")
    pilot_cover = cyc["pool_pilot_prev_present"] >= PILOT_PRESENT_MIN
    cyc["A0_avg"] = (cyc["pool_pilot_prev"] / cyc["n_active_prev"].clip(lower=1)).where(pilot_cover)
    cyc["A1_pilot"] = cyc["pilot_prev"]
    cyc["A2_prev_actual"] = cyc["actual_prev"]
    cyc["A3_rolling_quantile"] = cyc["actual_rollq"]
    has_pilot_prev = cyc["pilot_prev_present"].fillna(False)
    a4 = np.minimum(cyc["pilot_prev"], cyc["actual_rollq"])
    a4 = pd.Series(a4, index=cyc.index)
    cyc["A4_min_pilot_quantile"] = a4.where(
        has_pilot_prev & cyc["actual_rollq"].notna()
    )
    for p in PROXIES:
        cyc[p] = cyc[p].astype("float64")
    return cyc


def eligible_mask(prox: pd.DataFrame, prox_list: list[str]) -> pd.Series:
    """会话×周期 层精确交集：所有比较代理在该 (site,garage,cycle,session_id) 都可计算。"""
    m = pd.Series(True, index=prox.index)
    for p in prox_list:
        m = m & prox[p].notna()
    return m


def candidate_windows(cyc: pd.DataFrame, proxies: list[str] | None = None) -> pd.DataFrame:
    """每池×周期 指标 A：并发候选修正窗口（n_slack≥1 且 n_active≥2）。

    输入应为已按 eligible_mask 过滤的 会话×周期 表（保证所有代理同一会话集合）。
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
            n_active=("active", "sum"),
        ).reset_index()
        tmp["candidate"] = (tmp["n_slack"] >= 1) & (tmp["n_active"] >= 2)
        tmp["candidate_energy_kwh"] = tmp["total_slack"] * CYCLE_MIN / 60.0
        tmp["candidate_energy_kwh"] = tmp["candidate_energy_kwh"].where(tmp["candidate"], 0.0)
        sup = np.minimum(tmp["total_slack"], tmp["total_headroom"]) * CYCLE_MIN / 60.0
        tmp["supported_ref_energy_kwh"] = (
            pd.Series(sup, index=tmp.index).where(tmp["candidate"], 0.0)
        )
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
        out = out.merge(r.drop(columns=["n_active"]), on=["site", "garage", "cycle"], how="outer")
    return out


def available_mask(cand: pd.DataFrame, pool: str, prox_list: list[str]) -> pd.Series:
    """池×周期 级 eligible mask（兼容接口：所有代理在给定池上均可计算）。"""
    m = cand["pool"] == pool
    for p in prox_list:
        m = m & cand[f"n_budget_{p}"].ge(1)
    return m


def build_cycle_table(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """分钟表 → (池×周期 候选窗口表, 会话×周期 预算代理表)。无 eligible 限制（默认全集）。"""
    cyc = build_cycles(df)
    pool = compute_pool_stats(cyc)
    prox = compute_proxies(cyc, pool)
    cyc_level = candidate_windows(prox)
    cyc_level["pool"] = cyc_level["site"] + "." + cyc_level["garage"]
    meta = prox[["site", "garage", "cycle", "month", "month_conn"]].drop_duplicates()
    cyc_level = cyc_level.merge(meta, on=["site", "garage", "cycle"], how="left")
    return cyc_level, prox
