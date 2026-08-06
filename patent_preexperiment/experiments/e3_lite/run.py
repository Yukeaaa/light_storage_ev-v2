"""E3-Lite：同逻辑池并发 + A0–A4 预算代理反事实机会审计（V2.1 §7；K1 冻结）。

池 = site+garage（P1 逻辑控制池）。控制周期 = 5 分钟。
有效控制周期 = 池内 ≥2 个活跃充电会话。
机会（保守修正）：∃ 会话低于其预算代理 ≥MARGIN，且 ∃ 另一活跃会话的历史实际上界高于其当前代理
（吸收能力 ≥MARGIN，调整不超出历史观察支持域）。机会能量 = min(总slack, 总可吸收头寸)。
仅输出"预算差值/反事实机会"，不称"可回收能力"（术语纪律）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml

REPO = Path(__file__).resolve().parents[3]
IMPL = REPO / "patent_preexperiment"
MINUTE_TABLE = IMPL / "datasets" / "lite_session_minute.parquet"
OUT = IMPL / "results" / "raw" / "E3L"

CYCLE_MIN = 5
MARGIN_KW = 0.5
ROLL_WINDOW_MIN = 60
ROLL_Q = 0.90


def _build_cycles(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["cycle"] = d["timestamp_utc"].dt.floor(f"{CYCLE_MIN}min")
    d["actual"] = d["actual_power_kw"].astype(float)
    d["pilot"] = d["pilot_power_kw"].astype(float)
    d["day"] = d["timestamp_utc"].dt.date.astype(str)
    d = d.sort_values(["site", "garage", "session_id", "timestamp_utc"])
    g = d.groupby(["site", "garage", "session_id"], sort=False)
    d["actual_rollmax"] = g["actual"].transform(lambda s: s.rolling(ROLL_WINDOW_MIN, min_periods=2).max())
    d["actual_rollq"] = g["actual"].transform(lambda s: s.rolling(ROLL_WINDOW_MIN, min_periods=2).quantile(ROLL_Q))
    d["actual_prev"] = g["actual"].shift(1)
    agg = (
        d.groupby(["site", "garage", "cycle", "session_id"], sort=False)
        .agg(
            actual=("actual", "mean"),
            pilot=("pilot", "mean"),
            pilot_present=("pilot", lambda s: s.notna().mean()),
            actual_rollmax=("actual_rollmax", "max"),
            actual_rollq=("actual_rollq", "max"),
            actual_prev=("actual_prev", "mean"),
            active_share=("actual", lambda s: ((s >= 0.5)).mean()),
            day=("day", "first"),
        )
        .reset_index()
    )
    agg["active"] = agg["active_share"] > 0.5
    return agg[agg["active"]]


def run_e3_lite() -> dict:
    cfg = load_yaml(IMPL / "configs" / "k1_preregister.yaml")
    proxies = cfg["budget_proxies"]
    OUT.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(MINUTE_TABLE)
    df["month"] = df["timestamp_utc"].astype(str).str[:7]
    df["day"] = df["timestamp_utc"].dt.date.astype(str)
    cyc = _build_cycles(df)
    cyc["pool"] = cyc["site"] + "." + cyc["garage"]

    grp = cyc.groupby(["pool", "cycle"], sort=False)
    pool_tot = grp.agg(n_active=("actual", "size")).reset_index()
    pool_tot["pool_pilot"] = cyc.groupby(["pool", "cycle"], sort=False)["pilot"].sum().reset_index(drop=True)
    cyc = cyc.merge(pool_tot, on=["pool", "cycle"], how="left")
    cyc["pool_pilot"] = cyc["pool_pilot"].where(cyc["pool_pilot"].notna(), 0.0)

    c0 = cyc[["pool", "cycle", "day", "n_active"]].drop_duplicates()
    c0["month"] = c0["cycle"].astype(str).str[:7]

    # 每行各代理预算（pilot 缺失时 A0/A1/A4=NaN）
    budget = pd.DataFrame(index=cyc.index)
    budget["A0_avg"] = cyc["pool_pilot"] / cyc["n_active"]
    budget["A1_pilot"] = cyc["pilot"].where(cyc["pilot_present"] > 0.5)
    budget["A2_prev_actual"] = cyc["actual_prev"]
    budget["A3_rolling_quantile"] = cyc["actual_rollq"]
    budget["A4_min_pilot_quantile"] = np.minimum(cyc["pilot"], cyc["actual_rollq"]).where(
        (cyc["pilot_present"] > 0.5) & cyc["actual_rollq"].notna()
    )

    valid = c0[c0["n_active"] >= 2].copy()
    for name in proxies:
        b = budget[name].values
        slack = b - cyc["actual"].values
        headroom = cyc["actual_rollmax"].values - b
        has_budget = np.isfinite(b)
        s = np.where(has_budget, np.clip(slack, 0, None), np.nan)
        h = np.where(has_budget, np.clip(headroom, 0, None), np.nan)
        tmp = cyc.assign(
            n_slack=np.where(has_budget & (slack >= MARGIN_KW), 1, 0),
            n_absorb=np.where(has_budget & (headroom >= MARGIN_KW), 1, 0),
            total_slack=np.nan_to_num(s, nan=0.0),
            total_headroom=np.nan_to_num(h, nan=0.0),
            n_budget=np.where(has_budget, 1, 0),
        ).groupby(["pool", "cycle"], sort=False).agg(
            n_slack=("n_slack", "sum"),
            n_absorb=("n_absorb", "sum"),
            total_slack=("total_slack", "sum"),
            total_headroom=("total_headroom", "sum"),
            n_budget=("n_budget", "sum"),
        ).reset_index()
        valid = valid.merge(
            tmp.rename(
                columns={"n_slack": f"n_slack_{name}", "n_absorb": f"n_absorb_{name}",
                         "total_slack": f"slack_{name}_kwh", "total_headroom": f"headroom_{name}_kwh",
                         "n_budget": f"n_budget_{name}"}
            ),
            on=["pool", "cycle"], how="left",
        )
        valid[f"opportunity_{name}"] = (
            (valid[f"n_slack_{name}"] >= 1) & (valid[f"n_absorb_{name}"] >= 1) & (valid[f"n_budget_{name}"] >= 2)
        )
        valid[f"opp_energy_{name}_kwh"] = (
            np.minimum(valid[f"slack_{name}_kwh"], valid[f"headroom_{name}_kwh"]) * CYCLE_MIN / 60.0
            if valid[f"opportunity_{name}"].any()
            else 0.0
        )
        valid.loc[~valid[f"opportunity_{name}"], f"opp_energy_{name}_kwh"] = 0.0

    pool_cycles = valid
    pool_cycles.to_parquet(OUT / "e3_lite_pool_opportunity.parquet", index=False)

    # ---- 池×月 汇总 ----
    summary_rows: list[dict] = []
    for pool, grp in pool_cycles.groupby("pool"):
        for month, gm in grp.groupby("month"):
            summary_rows.append(
                {
                    "pool": pool, "month": month, "n_valid_cycles": len(gm),
                    **{f"opp_rate_{p}": float(gm[f"opportunity_{p}"].mean()) for p in proxies},
                    **{f"opp_energy_{p}_kwh": float(gm[f"opp_energy_{p}_kwh"].sum()) for p in proxies},
                }
            )
    pool_month = pd.DataFrame(summary_rows)
    pool_month.to_csv(OUT / "e3_lite_baseline_comparison.csv", index=False)

    # 每日修正能量 vs 当日 EV 能量：每池用其最强可用基线（caltech=A4，jpl 无 pilot 用 A3 保守）
    best_by_pool = {
        "caltech.California_Garage_01": "A4_min_pilot_quantile",
        "jpl.Arroyo_Garage_01": "A3_rolling_quantile",
    }
    daily_parts: list[pd.DataFrame] = []
    for pool, proxy in best_by_pool.items():
        col = f"opp_energy_{proxy}_kwh"
        part = (
            pool_cycles[pool_cycles["pool"] == pool]
            .groupby(["pool", "day"])[col]
            .sum()
            .rename("corr_energy_kwh")
            .reset_index()
        )
        part["proxy"] = proxy
        daily_parts.append(part)
    daily = pd.concat(daily_parts, ignore_index=True)
    daily_ev = (
        df.groupby(["site", "garage", "day"])["actual_power_kw"].sum().div(60.0).rename("ev_energy_kwh").reset_index()
    )
    daily_ev["pool"] = daily_ev["site"] + "." + daily_ev["garage"]
    daily = daily.merge(daily_ev[["pool", "day", "ev_energy_kwh"]], on=["pool", "day"], how="left")
    daily["share"] = daily["corr_energy_kwh"] / daily["ev_energy_kwh"].clip(lower=1e-6)
    daily.to_csv(OUT / "e3_lite_daily_energy.csv", index=False)

    # 每池最强可用基线机会能量（统一口径）
    best_col = {}
    for pool, proxy in best_by_pool.items():
        col = f"opp_energy_{proxy}_kwh"
        best_col[pool] = col
    pool_cycles["opp_energy_best_kwh"] = pool_cycles.apply(
        lambda r: r[best_col[r["pool"]]] if r["pool"] in best_col else 0.0, axis=1
    )
    pool_cycles["opportunity_best"] = pool_cycles["opp_energy_best_kwh"] > 0

    # 集中度
    opp_best = pool_cycles["opp_energy_best_kwh"] > 0
    conc = {
        "n_valid_cycles": int(len(pool_cycles)),
        "top_month_share_of_cycles": float(pool_cycles.groupby("month").size().max() / max(len(pool_cycles), 1)),
        "top_day_share_of_opp_best": float(
            pool_cycles[opp_best].groupby("day")["opp_energy_best_kwh"].sum().max()
            / max(pool_cycles[opp_best]["opp_energy_best_kwh"].sum(), 1e-9)
        ) if opp_best.any() else None,
        "top_pool_share_of_opp_best": float(
            pool_cycles[opp_best].groupby("pool")["opp_energy_best_kwh"].sum().max()
            / max(pool_cycles[opp_best]["opp_energy_best_kwh"].sum(), 1e-9)
        ) if opp_best.any() else None,
        "n_months_with_opp": int(pool_cycles[opp_best]["month"].nunique()) if opp_best.any() else 0,
    }
    pd.DataFrame([conc]).to_csv(OUT / "e3_lite_concentration.csv", index=False)

    fail = _build_fail_cases(pool_cycles, proxies)
    fail.to_csv(OUT / "e3_lite_fail_cases.csv", index=False)

    stop = cfg["k1_stop_lines"]["e3"]
    a0, a2, a3, a4 = "A0_avg", "A2_prev_actual", "A3_rolling_quantile", "A4_min_pilot_quantile"

    def _rate(p: str) -> float:
        return float(pool_cycles[f"opportunity_{p}"].mean())

    rate_a0, rate_a4 = _rate(a0), _rate(a4)
    elim_a2 = 1 - _rate(a2) / max(rate_a0, 1e-9)
    elim_a3 = 1 - _rate(a3) / max(rate_a0, 1e-9)
    daily_med_share = daily.groupby("pool")["share"].median()
    pools_meeting = int((daily_med_share >= stop["min_daily_energy_share"]).sum())

    gates = {
        "n_pools": int(pool_cycles["pool"].nunique()),
        "n_valid_cycles": int(len(pool_cycles)),
        "opp_rate_A0_avg": rate_a0,
        "opp_rate_A4_strongest": rate_a4,
        "elimination_by_A2": float(elim_a2),
        "elimination_by_A3": float(elim_a3),
        "daily_median_share_by_pool": {str(k): float(v) for k, v in daily_med_share.items()},
        "pools_meeting_daily_share": int(pools_meeting),
        "n_months_with_opp": conc["n_months_with_opp"],
        "pass_opp_rate": rate_a4 >= stop["min_opportunity_cycle_rate"],
        "pass_not_eliminated": elim_a2 <= stop["max_baseline_elimination"] and elim_a3 <= stop["max_baseline_elimination"],
        "pass_two_pools_share": pools_meeting >= 2,
        "pass_not_single_month": conc["n_months_with_opp"] >= 2,
    }
    summary = {
        "method": "P1 逻辑池反事实机会；A0–A4 预算代理；控制周期=5min；margin=0.5kW；调整不超历史观察支持域",
        "terminology": "仅'预算差值/反事实机会'，不称'可回收能力'",
        "n_valid_cycles": int(len(pool_cycles)),
        "opp_rate_by_proxy": {p: _rate(p) for p in proxies},
        "concentration": conc,
        "gates": gates,
        "caveat": "jpl 无 pilot：A0/A1/A4 在 jpl 池缺失（NaN），该池只用 A2/A3 保守机会，日能量用 A3 口径",
    }
    (OUT / "e3_lite_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def _build_fail_cases(pool_cycles: pd.DataFrame, proxies: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    a4 = "opp_energy_A4_min_pilot_quantile_kwh"
    opp = pool_cycles[pool_cycles[a4] > 0]
    for _, r in opp.nlargest(20, a4).iterrows():
        rows.append({**r.to_dict(), "fail_type": "opportunity_cycle"})
    non = pool_cycles[pool_cycles[a4].astype(bool) == False]  # noqa: E712
    for _, r in non.head(20).iterrows():
        rows.append({**r.to_dict(), "fail_type": "no_opportunity_valid_cycle"})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    sys.exit(0 if run_e3_lite() else 1)
