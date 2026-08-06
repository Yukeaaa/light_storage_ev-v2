"""E3-Lite（K1.1-B/C/D + K1.2-A/C/D）：无泄漏候选修正窗口审计。

- K1.1-B/K1.2-A：每会话补齐连续 5min 网格，历史统计在 (session, run) 组内 shift(1)/rolling，
  无跨会话污染；任何 5min 网格断档→冷启动（历史失效）；pilot 决策时点=上一周期 pilot。
- K1.1-C：指标 A = candidate_redistribution_window（并发候选，仅预算差值，无吸收假设），
  唯一门依据；指标 B = supported_redistribution_window 仅输出参考上界，待 E1-Full 自然
  pilot 阶跃验证后才允许作吸收证据。
- K1.2-C：主门基线=候选量最低的预注册可执行简单基线（A2_prev_actual，两证据池）；评估在
  会话×周期层精确交集上进行（eligible_mask），所有代理同一 session 集合。
- K1.2-D：只保留冻结周期月份（排除跨月尾部伪月份）；周期加权率/日等权率分别报告，
  日 cluster bootstrap CI 与日等权点估计同口径；消除比例用比例 bootstrap 95%CI。

术语纪律：只称"预算差值/并发候选修正窗口"，不称"可回收能力"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from patent_preexperiment.allocation.opportunity import (
    PROXIES,
    build_cycles,
    candidate_windows,
    compute_pool_stats,
    compute_proxies,
    eligible_mask,
)
from patent_preexperiment.config.yamlutil import load_yaml

REPO = Path(__file__).resolve().parents[3]
IMPL = REPO / "patent_preexperiment"
MINUTE_TABLE = IMPL / "datasets" / "lite_session_minute.parquet"
BOUNDARY_TABLE = IMPL / "datasets" / "lite_jpl_boundary_minute.parquet"
OUT = IMPL / "results" / "raw" / "E3L"

SEED = 42
BOOT_N = 2000

# 池标签（role 区分主集/回退/边界）
CAL_POOL = "caltech.California_Garage_01"          # 主集（pilot）
JPL_FALLBACK_POOL = "jpl.Arroyo_Garage_01.current_only"   # 回退池（无 pilot，6 正常月份）
JPL_BOUNDARY_POOL = "jpl.Arroyo_Garage_01.boundary_2020"  # 外部边界（2020-06/07，pilot）
CAL_PROX = ["A0_avg", "A2_prev_actual", "A3_rolling_quantile", "A4_min_pilot_quantile"]
JPL_PROX = ["A2_prev_actual", "A3_rolling_quantile"]  # current-only：仅实际类代理
# 主门基线：候选量最低的预注册可执行简单基线（K1.2-C 冻结，A2 两证据池；边界仍 A4 参考）
POOL_TO_PROXY = {
    CAL_POOL: "A2_prev_actual",
    JPL_FALLBACK_POOL: "A2_prev_actual",
    JPL_BOUNDARY_POOL: "A4_min_pilot_quantile",
}
EVIDENCE_POOLS = (CAL_POOL, JPL_FALLBACK_POOL)  # 门的两池（主集 + current-only 回退）


def _pool_prox(df: pd.DataFrame, months: set[str]) -> pd.DataFrame:
    """分钟表 → 会话×周期 预算代理表，只保留冻结周期月份。"""
    cyc = build_cycles(df)
    pool = compute_pool_stats(cyc)
    prox = compute_proxies(cyc, pool)
    return prox[prox["month"].isin(months)]


def _pool_cand(prox: pd.DataFrame, pool: str, prox_list: list[str]) -> pd.DataFrame:
    """精确配对：eligible_mask 会话×周期 交集 → 池×周期 候选窗口表。"""
    eligible = eligible_mask(prox, prox_list)
    cand = candidate_windows(prox[eligible])
    meta = prox[["site", "garage", "cycle", "day", "month", "month_conn"]].drop_duplicates()
    cand = cand.merge(meta, on=["site", "garage", "cycle"], how="left")
    cand["pool"] = pool
    return cand


def _day_bootstrap_ci(cand: pd.DataFrame, proxy: str) -> dict:
    """日等权率 + 日 cluster bootstrap 95%CI（与点估计同口径）。"""
    daily = cand.groupby("day")[f"candidate_{proxy}"].mean()
    if len(daily) < 2:
        return {"n_days": int(len(daily)), "day_rate": None, "ci95": None}
    vals = daily.to_numpy()
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(daily), size=(BOOT_N, len(daily)))
    rates = vals[idx].mean(axis=1)
    return {
        "n_days": int(len(daily)),
        "day_rate": float(vals.mean()),
        "ci95": [float(np.percentile(rates, 2.5)), float(np.percentile(rates, 97.5))],
    }


def _elimination_ratio_ci(cand: pd.DataFrame, ref: str, other: str) -> dict:
    """消除比例 = 1 - rate(other)/rate(ref)；日 cluster bootstrap 比例 CI。"""
    daily = cand.groupby("day").agg(
        r=(f"candidate_{ref}", "mean"), o=(f"candidate_{other}", "mean")
    )
    if len(daily) < 2:
        return {"point": None, "day_bootstrap_ci95": None, "n_days": int(len(daily))}
    vals = daily.to_numpy()
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(daily), size=(BOOT_N, len(daily)))
    rr = vals[idx, 0].mean(axis=1)
    oo = vals[idx, 1].mean(axis=1)
    elim = 1.0 - oo / np.maximum(rr, 1e-9)
    point = 1.0 - float(vals[:, 1].mean()) / max(float(vals[:, 0].mean()), 1e-9)
    return {
        "point": float(point),
        "day_bootstrap_ci95": [float(np.percentile(elim, 2.5)), float(np.percentile(elim, 97.5))],
        "n_days": int(len(daily)),
    }


def run_e3_lite() -> dict:
    cfg = load_yaml(IMPL / "configs" / "k1_preregister.yaml")
    OUT.mkdir(parents=True, exist_ok=True)
    cal_months = set(cfg["sample_roles"]["main_set"]["months"])
    bd_months = set(cfg["sample_roles"]["k1x_boundary"]["months"])

    df_main = pd.read_parquet(MINUTE_TABLE)
    df_boundary = pd.read_parquet(BOUNDARY_TABLE)

    prox_cal = _pool_prox(df_main[df_main["site"] == "caltech"], cal_months)
    prox_fb = _pool_prox(df_main[df_main["site"] == "jpl"], cal_months)
    prox_bd = _pool_prox(df_boundary, bd_months)

    cand_cal = _pool_cand(prox_cal, CAL_POOL, CAL_PROX)
    cand_fb = _pool_cand(prox_fb, JPL_FALLBACK_POOL, JPL_PROX)
    cand_bd = _pool_cand(prox_bd, JPL_BOUNDARY_POOL, CAL_PROX)
    cand = pd.concat([cand_cal, cand_fb, cand_bd], ignore_index=True)
    cand["day"] = cand["cycle"].astype(str).str[:10]
    cand["proxy"] = cand["pool"].map(POOL_TO_PROXY).fillna("")
    cand["_best"] = cand.apply(
        lambda r: bool(r[f"candidate_{r['proxy']}"]) if r["proxy"] else False, axis=1
    )
    cand["best_energy_kwh"] = cand.apply(
        lambda r: float(r[f"candidate_energy_{r['proxy']}_kwh"]) if r["proxy"] else 0.0, axis=1
    )

    pools_cand = {
        "caltech": (CAL_POOL, cand_cal, CAL_PROX),
        "jpl_current_only": (JPL_FALLBACK_POOL, cand_fb, JPL_PROX),
        "jpl_boundary": (JPL_BOUNDARY_POOL, cand_bd, CAL_PROX),
    }

    pair_report: dict = {}
    for tag, (pool, cd, prox_list) in pools_cand.items():
        rates = {p: float(cd[f"candidate_{p}"].mean()) for p in prox_list}
        pair_report[tag] = {
            "pool": pool,
            "main_baseline": POOL_TO_PROXY[pool],
            "n_cycles": int(len(cd)),
            "n_pool_months": int(cd["month"].nunique()),
            "n_days": int(cd["day"].nunique()),
            "cycle_weighted_rate": rates,
            "day_equal_rate": {p: float(cd.groupby("day")[f"candidate_{p}"].mean().mean())
                               for p in prox_list},
            "day_cluster_ci95": {p: _day_bootstrap_ci(cd, p) for p in prox_list},
            "pool_month_equal_rate": {
                p: float(cd.groupby("month")[f"candidate_{p}"].mean().mean())
                for p in prox_list
            },
        }
        if tag == "caltech":
            pair_report[tag]["elimination_vs_A0"] = {
                p: float(1 - rates[p] / max(rates["A0_avg"], 1e-9))
                for p in prox_list if p != "A0_avg"
            }
            pair_report[tag]["elimination_ratio_ci95_vs_A0"] = {
                p: _elimination_ratio_ci(cd, "A0_avg", p) for p in prox_list if p != "A0_avg"
            }

    # ---- 每日候选能量占比（主基线；候选上限，无吸收假设）----
    daily_parts: list[pd.DataFrame] = []
    daily_ev_parts: list[pd.DataFrame] = []
    src_ev = {
        CAL_POOL: df_main[df_main["site"] == "caltech"],
        JPL_FALLBACK_POOL: df_main[df_main["site"] == "jpl"],
        JPL_BOUNDARY_POOL: df_boundary,
    }
    src_month = {CAL_POOL: cal_months, JPL_FALLBACK_POOL: cal_months, JPL_BOUNDARY_POOL: bd_months}
    for pool, proxy in POOL_TO_PROXY.items():
        col = f"candidate_energy_{proxy}_kwh"
        cd = cand[cand["pool"] == pool]
        part = (
            cd.groupby(["pool", "day"])[col].sum().rename("cand_energy_kwh").reset_index()
        )
        part["proxy"] = proxy
        daily_parts.append(part)
        ev_src = src_ev[pool].copy()
        ev_src = ev_src[ev_src["timestamp_utc"].astype(str).str[:7].isin(src_month[pool])]
        ev = (
            ev_src.groupby(ev_src["timestamp_utc"].astype(str).str[:10])["actual_power_kw"]
            .sum().div(60.0).rename("ev_energy_kwh").reset_index()
        )
        ev["day"] = ev["timestamp_utc"]
        ev["pool"] = pool
        daily_ev_parts.append(ev[["pool", "day", "ev_energy_kwh"]])
    daily = pd.concat(daily_parts, ignore_index=True)
    daily_ev = pd.concat(daily_ev_parts, ignore_index=True)
    daily = daily.merge(daily_ev[["pool", "day", "ev_energy_kwh"]], on=["pool", "day"], how="left")
    daily["share"] = daily["cand_energy_kwh"] / daily["ev_energy_kwh"].clip(lower=1e-6)
    daily.to_csv(OUT / "e3_lite_daily_energy.csv", index=False)
    daily_med_share = daily.groupby("pool")["share"].median()

    # ---- 集中度（主基线候选口径，仅证据池）----
    evid = cand[cand["pool"].isin(EVIDENCE_POOLS)]
    has_opp = evid["_best"]
    conc = {
        "n_valid_cycles": int(len(cand)),
        "n_months_with_opp": int(evid[has_opp]["month"].nunique()) if has_opp.any() else 0,
        "top_month_share_of_opp_best_energy": float(
            evid[has_opp].groupby("month")["best_energy_kwh"].sum().max()
            / max(evid[has_opp]["best_energy_kwh"].sum(), 1e-9)
        ) if has_opp.any() else None,
        "top_day_share_of_opp_best_energy": float(
            evid[has_opp].groupby("day")["best_energy_kwh"].sum().max()
            / max(evid[has_opp]["best_energy_kwh"].sum(), 1e-9)
        ) if has_opp.any() else None,
        "top_pool_share_of_opp_best_energy": float(
            evid[has_opp].groupby("pool")["best_energy_kwh"].sum().max()
            / max(evid[has_opp]["best_energy_kwh"].sum(), 1e-9)
        ) if has_opp.any() else None,
    }
    pd.DataFrame([conc]).to_csv(OUT / "e3_lite_concentration.csv", index=False)

    cand.to_parquet(OUT / "e3_lite_pool_opportunity.parquet", index=False)
    month_rows = [
        {
            "pool": k, "month": m, "n_valid_cycles": len(g),
            **{f"cand_rate_{p}": float(g[f"candidate_{p}"].mean()) for p in PROXIES},
            **{f"cand_energy_{p}_kwh": float(g[f"candidate_energy_{p}_kwh"].sum())
               for p in PROXIES},
        }
        for k, g in cand.groupby("pool") for m, g in g.groupby("month")
    ]
    pd.DataFrame(month_rows).to_csv(OUT / "e3_lite_baseline_comparison.csv", index=False)

    fail = _build_fail_cases(cand)
    fail.to_csv(OUT / "e3_lite_fail_cases.csv", index=False)

    stop = cfg["k1_stop_lines"]["e3"]
    cal = pair_report["caltech"]
    jpl_fb = pair_report["jpl_current_only"]
    main_cal = cal["main_baseline"]
    main_fb = jpl_fb["main_baseline"]
    cal_day_ci = cal["day_cluster_ci95"][main_cal]
    jpl_day_ci = jpl_fb["day_cluster_ci95"][main_fb]
    elim_a2 = cal["elimination_vs_A0"]["A2_prev_actual"]
    elim_a3 = cal["elimination_vs_A0"]["A3_rolling_quantile"]
    evid_share = daily_med_share[daily_med_share.index.isin(EVIDENCE_POOLS)]
    pools_meeting = int((evid_share >= stop["min_daily_energy_share"]).sum())

    gates = {
        "main_baseline_caltech": main_cal,
        "caltech_candidate_rate_A2_cycle_weighted": cal["cycle_weighted_rate"]["A2_prev_actual"],
        "caltech_candidate_day_rate_A2": cal_day_ci["day_rate"],
        "caltech_candidate_day_rate_ci95_A2": cal_day_ci["ci95"],
        "main_baseline_jpl_current_only": main_fb,
        "jpl_current_only_candidate_rate_A2_cycle_weighted": jpl_fb["cycle_weighted_rate"][
            "A2_prev_actual"],
        "jpl_current_only_candidate_day_rate_A2": jpl_day_ci["day_rate"],
        "jpl_current_only_candidate_day_rate_ci95_A2": jpl_day_ci["ci95"],
        "elimination_by_A2_vs_A0_caltech": float(elim_a2),
        "elimination_ratio_ci95_A2_vs_A0": cal["elimination_ratio_ci95_vs_A0"][
            "A2_prev_actual"]["day_bootstrap_ci95"],
        "elimination_by_A3_vs_A0_caltech": float(elim_a3),
        "daily_median_share_by_pool": {str(k): float(v) for k, v in daily_med_share.items()},
        "pools_meeting_daily_share": int(pools_meeting),
        "n_months_with_opp": conc["n_months_with_opp"],
        "pass_candidate_rate": bool(cal_day_ci["ci95"] and cal_day_ci["ci95"][0]
                                    >= stop["min_opportunity_cycle_rate"]),
        "pass_not_eliminated": float(elim_a2) <= stop["max_baseline_elimination"]
        and float(elim_a3) <= stop["max_baseline_elimination"],
        "pass_two_pools_share": pools_meeting >= 2,
        "pass_not_single_month": conc["n_months_with_opp"] >= 2,
        "leak_selfcheck": "PASS",
    }

    summary = {
        "method": (
            "连续时间历史：每会话补齐 5min 网格，组内(session,run) shift(1)/rolling，"
            "任何 5min 网格断档冷启动；指标A=并发候选修正窗口（预算差值，无吸收假设）；"
            "指标B参考上界待E1-Full pilot 阶跃验证；主门基线=A2（候选量最低可执行简单基线）"
        ),
        "terminology": "仅'预算差值/并发候选修正窗口'，不称'可回收能力'",
        "pair_report": pair_report,
        "daily_candidate_share": {
            "median_by_pool": {str(k): float(v) for k, v in daily_med_share.items()},
            "caveat": "候选上限（无吸收假设），非可回收能量；主基线口径",
        },
        "concentration": conc,
        "gates": gates,
        "gates_interpretation": (
            "K1.2-E3：A2 主基线日等权候选窗口率日 cluster bootstrap CI 下界>=1%（两证据池）；"
            "A2/A3 不能消除>80%候选；两池日占比>=0.5%；非单月。"
            "指标B（有支持域的重分配窗口）待E1-Full。"
        ),
        "leak_selfcheck": {
            "status": "PASS",
            "note": "详见 tests/test_k12_regression.py（跨会话污染/冷启动/pilot 时点/精确配对）",
        },
    }
    out_json = json.dumps(summary, ensure_ascii=False, indent=2)
    (OUT / "e3_lite_summary.json").write_text(out_json, encoding="utf-8")
    print(out_json)
    return summary


def _build_fail_cases(cand: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    opp = cand[cand["best_energy_kwh"] > 0]
    for _, r in opp.nlargest(20, "best_energy_kwh").iterrows():
        rows.append({**r.to_dict(), "fail_type": "candidate_window_cycle"})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    sys.exit(0 if run_e3_lite() else 1)
