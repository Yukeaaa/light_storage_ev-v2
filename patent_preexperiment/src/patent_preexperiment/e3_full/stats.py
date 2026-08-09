"""E3-Full 逐 split 机会审计（复用 allocation.opportunity 冻结核心）。

每人口×split 一个逻辑池（E3-M = caltech.California_Garage_01，E3-X =
jpl.Arroyo_Garage_01），完整复用 K1 E3-Lite 冻结管线：
build_cycles（连续 5min 网格 + (session,run) 组内 shift/rolling + 缺桶冷启动）
→ compute_pool_stats → compute_proxies → eligible_mask（会话×周期精确交集）
→ candidate_windows（指标 A = 并发候选修正窗口，预算差值，无吸收假设）。

审查结论28：meta 只合 cycle 纯函数字段（month/day），候选表 [site,garage,cycle]
必须唯一，任何 fan-out 即 STOP。

R1 冻结差异（相对 E3-Lite）：
- 人口=逐 split 硬切分（train/val/test 各自独立统计，不合并）；
- split 内全部正常月份（不再做 K1 的 6 个月窗口挑选），月份浓度单独报告；
- 主基线 A2_prev_actual 两池一致；caltech 代理集 [A0_avg, A2, A3]（A0 作消除率参照、
  A3 作简单基线消除率研究；A1/A4 非门所需故不进 R1），jpl current-only [A2, A3]；
- 审查结论29 P0-4：daily_energy_share 与 K1 同源——从 evaluable days（有 valid
  candidate cycles 的日期）出发 left join EV energy；无 eligible cycles 的日期不以
  share=0 进入 median（non-evaluable ≠ real zero，与 E0 evaluable 汇总层原则一致）；
  另报 n_operating_days / n_evaluable_days / n_non_evaluable_days / coverage。
- 补充 V2.0 §9.5 报告指标：机会持续时间（连续候选 run 中位/p95）、并发会话数
  （候选周期 n_active 中位）——只报告、不参与门判定。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.allocation.opportunity import (
    build_cycles,
    candidate_windows,
    compute_pool_stats,
    compute_proxies,
    eligible_mask,
)

CALTECH_PROXIES = ["A0_avg", "A2_prev_actual", "A3_rolling_quantile"]
JPL_PROXIES = ["A2_prev_actual", "A3_rolling_quantile"]
MAIN_PROXY = "A2_prev_actual"
CYCLE_MIN = 5


def _day_bootstrap_ci(cand: pd.DataFrame, proxy: str, seed: int, n_boot: int) -> dict[str, Any]:
    """日等权率 + 日 cluster bootstrap 95%CI（与点估计同口径）。"""
    daily = cand.groupby("day")[f"candidate_{proxy}"].mean()
    if len(daily) < 2:
        return {"n_days": int(len(daily)), "day_rate": None, "ci95": None}
    vals = daily.to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(daily), size=(n_boot, len(daily)))
    rates = vals[idx].mean(axis=1)
    return {
        "n_days": int(len(daily)),
        "day_rate": float(vals.mean()),
        "ci95": [float(np.percentile(rates, 2.5)), float(np.percentile(rates, 97.5))],
    }


def _elimination_ratio_ci(
    cand: pd.DataFrame, ref: str, other: str, seed: int, n_boot: int
) -> dict[str, Any]:
    """消除比例 = 1 - rate(other)/rate(ref)；日 cluster bootstrap 比例 CI。"""
    daily = cand.groupby("day").agg(
        r=(f"candidate_{ref}", "mean"), o=(f"candidate_{other}", "mean")
    )
    if len(daily) < 2:
        return {"point": None, "day_bootstrap_ci95": None, "n_days": int(len(daily))}
    vals = daily.to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(daily), size=(n_boot, len(daily)))
    rr = vals[idx, 0].mean(axis=1)
    oo = vals[idx, 1].mean(axis=1)
    elim = 1.0 - oo / np.maximum(rr, 1e-9)
    point = 1.0 - float(vals[:, 1].mean()) / max(float(vals[:, 0].mean()), 1e-9)
    return {
        "point": float(point),
        "day_bootstrap_ci95": [float(np.percentile(elim, 2.5)), float(np.percentile(elim, 97.5))],
        "n_days": int(len(daily)),
    }


def _duration_runs(cand: pd.DataFrame, proxy: str) -> dict[str, Any]:
    """机会持续时间：候选周期连续 run（间隔=1 个 5min 周期）→ 时长（min）分布。"""
    sub = cand[cand[f"candidate_{proxy}"]].sort_values("cycle")
    if sub.empty:
        return {"n_runs": 0, "duration_median_min": None, "duration_p95_min": None}
    is_new_run = sub["cycle"].diff().dt.total_seconds().fillna(60 * CYCLE_MIN) > 60 * CYCLE_MIN
    run_id = is_new_run.cumsum()
    durs = sub.groupby(run_id).size() * CYCLE_MIN
    return {
        "n_runs": int(len(durs)),
        "duration_median_min": float(durs.median()),
        "duration_p95_min": float(durs.quantile(0.95)),
        "duration_max_min": float(durs.max()),
    }


def pool_audit(
    minute_df: pd.DataFrame,
    pool_label: str,
    proxies: list[str],
    seed: int,
    n_boot: int,
) -> dict[str, Any]:
    """单个逻辑池×split 的完整机会审计（指标 A 口径）。"""
    cyc = build_cycles(minute_df)
    pool = compute_pool_stats(cyc)
    prox = compute_proxies(cyc, pool)
    elig = eligible_mask(prox, proxies)
    cand = candidate_windows(prox[elig], proxies=proxies)
    meta = prox[["site", "garage", "cycle", "day", "month"]].drop_duplicates()
    if len(meta):
        assert not meta.duplicated(subset=["site", "garage", "cycle"]).any(), (
            "meta fan-out：month/day 是 cycle 纯函数字段，[site,garage,cycle] 必须唯一"
        )
    if len(cand):
        cand = cand.merge(meta, on=["site", "garage", "cycle"], how="left")
        assert not cand.duplicated(subset=["site", "garage", "cycle"]).any(), (
            "candidate table fan-out：禁止会话级属性合入池×周期候选表（审查结论28）"
        )
    cand["day"] = cand["cycle"].astype(str).str[:10]
    cand["pool"] = pool_label
    n_dup_cycles = (
        int(cand.duplicated(subset=["site", "garage", "cycle"]).sum()) if len(cand) else 0
    )

    rates = {p: float(cand[f"candidate_{p}"].mean()) for p in proxies}
    day_ci = {p: _day_bootstrap_ci(cand, p, seed, n_boot) for p in proxies}

    ev = minute_df.copy()
    ev["day"] = ev["timestamp_utc"].astype(str).str[:10]
    ev_day_energy = ev.groupby("day")["actual_power_kw"].sum() / 60.0
    has_opp = cand[f"candidate_{MAIN_PROXY}"]
    # 审查结论29 P0-4：与 K1 同源——evaluable day = 至少有 1 个 candidate=True 的周期
    # （有可评估机会的日期）；无 candidate=True 周期的日期不以 share=0 进入 median
    # （non-evaluable ≠ real zero，与 E0 evaluable 汇总层原则一致）。
    cand_day = (
        cand.loc[has_opp]
        .groupby("day")[f"candidate_energy_{MAIN_PROXY}_kwh"]
        .sum()
    )
    ev_on_evaluable = ev_day_energy.reindex(cand_day.index).clip(lower=1e-6)
    share = cand_day.div(ev_on_evaluable)
    n_operating_days = int((ev_day_energy > 0).sum())
    n_evaluable_days = int(len(cand_day))
    n_non_evaluable_days = max(n_operating_days - n_evaluable_days, 0)
    evaluable_day_coverage = round(n_evaluable_days / max(n_operating_days, 1), 6)

    elimination = {}
    if "A0_avg" in proxies:
        for p in proxies:
            if p != "A0_avg":
                elimination[p] = {
                    "point": float(1 - rates[p] / max(rates["A0_avg"], 1e-9)),
                    "ratio_ci95": _elimination_ratio_ci(cand, "A0_avg", p, seed, n_boot),
                }

    concentration = {
        "n_months_with_opp": int(cand[has_opp]["month"].nunique()) if has_opp.any() else 0,
        "top_month_share_of_opp_energy": float(
            cand[has_opp].groupby("month")[f"candidate_energy_{MAIN_PROXY}_kwh"].sum().max()
            / max(cand[has_opp][f"candidate_energy_{MAIN_PROXY}_kwh"].sum(), 1e-9)
        ) if has_opp.any() else None,
        "top_day_share_of_opp_energy": float(
            cand[has_opp].groupby("day")[f"candidate_energy_{MAIN_PROXY}_kwh"].sum().max()
            / max(cand[has_opp][f"candidate_energy_{MAIN_PROXY}_kwh"].sum(), 1e-9)
        ) if has_opp.any() else None,
        "n_pools": int(cand["pool"].nunique()),
    }

    opp = cand[has_opp]
    return {
        "pool": pool_label,
        "n_sessions": int(minute_df["session_id"].nunique()),
        "n_rows": int(len(minute_df)),
        "n_valid_cycles": int(len(cand)),
        "n_dup_cycles": n_dup_cycles,
        "n_pool_months": int(cand["month"].nunique()) if len(cand) else 0,
        "n_days": int(cand["day"].nunique()) if len(cand) else 0,
        "cycle_weighted_rate": rates,
        "day_equal_rate": {p: float(cand.groupby("day")[f"candidate_{p}"].mean().mean())
                           for p in proxies},
        "day_cluster_ci95": day_ci,
        "elimination_vs_A0": elimination,
        "daily_energy_share_median": round(float(share.median()), 6) if len(share) else None,
        "daily_energy_share_mean": round(float(share.mean()), 6) if len(share) else None,
        "evaluable_days": {
            "n_operating_days": n_operating_days,
            "n_evaluable_days": n_evaluable_days,
            "n_non_evaluable_days": n_non_evaluable_days,
            "evaluable_day_coverage": evaluable_day_coverage,
        },
        "candidate_energy_total_kwh": round(
            float(cand[f"candidate_energy_{MAIN_PROXY}_kwh"].sum()), 6
        ) if len(cand) else 0.0,
        "concentration": concentration,
        "opportunity_duration_min": _duration_runs(cand, MAIN_PROXY),
        "concurrency": {
            "candidate_cycles": int(len(opp)),
            "median_n_active": float(opp["n_active"].median()) if len(opp) else None,
        },
        "_cand": cand,
    }


def audit_to_serializable(audit: dict[str, Any]) -> dict[str, Any]:
    """去掉 _cand 内部表，产出 JSON 可序列化字典。"""
    return {k: v for k, v in audit.items() if k != "_cand"}
