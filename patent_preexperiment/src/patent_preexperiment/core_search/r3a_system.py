"""R3-A：动态 BESS 备用系统层（DEV gate）。

核心 KPI：相同 PCC/缺额风险（target coverage 0.95）下，锁定的 BESS 能量减少多少。
四臂：B0 global fixed Q95 / B1 hour-of-day Q95 / B2 rolling Q95 / C hour-base × regime。
比较口径：locked_reserve_kwh_at_95 = Q95(|e|/R) * sum(R) * dt（同可靠性下锁定量）。
纪律：DEV 4 站只作 mechanism set；holdout 6 站单次 replication 才作最终 GO。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.io.paths import get_paths

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r3a.yaml"


def _load_net_error(
    site: int, emsx_dir: Path, load_col: str, pv_col: str, lag_steps: int
) -> pd.DataFrame:
    f = emsx_dir / f"{site}.csv.gz"
    if not f.exists():
        raise FileNotFoundError(f"缺少 EMSx site 文件：{f}")
    df = pd.read_csv(f, sep=";", compression="gzip").copy()
    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    net_actual = df["actual_consumption"] - df["actual_pv"]
    net_fc = df[load_col] - df[pv_col]
    e = (net_actual.shift(-lag_steps) - net_fc).rename("e")
    out = pd.DataFrame({"e": e, "hour": ts.dt.hour, "ts": ts})
    return out


def _q95(x: pd.Series) -> float:
    return float(x.abs().quantile(0.95))


def _policy_B0(e_train: pd.Series) -> float:
    return _q95(e_train)


def _policy_B1(e_train: pd.Series, hour_train: pd.Series) -> dict[int, float]:
    q = e_train.abs().groupby(hour_train).quantile(0.95)
    return {cast(int, k): float(v) for k, v in q.items()}


def _policy_B2(e_full: pd.Series, window: int) -> pd.Series:
    return e_full.abs().shift(1).rolling(window, min_periods=max(2, window // 2)).quantile(0.95)


def _policy_C(
    e_full: pd.Series, hour_full: pd.Series, base_map: dict[int, float],
    low_thr: float, high_thr: float, f_low: float, f_normal: float, regime_steps: int,
) -> pd.Series:
    base = hour_full.map(base_map)
    sig = e_full.abs().shift(1).rolling(regime_steps, min_periods=2).std()
    regime = np.select([sig <= low_thr, sig >= high_thr], [f_low, 1.0], default=f_normal)
    return cast(pd.Series, base * regime)


def _evaluate(R: pd.Series, e: pd.Series, dt: float) -> dict[str, float]:
    m = R.notna() & e.notna() & (R > 0)
    Rv = R[m].astype(float)
    ev = e[m].astype(float)
    if Rv.empty:
        return {"locked_kwh_at_95": np.nan, "scale": np.nan, "coverage": np.nan,
                "shortfall_kwh": np.nan, "n": 0.0}
    ratio = ev.abs() / Rv
    scale = float(ratio.quantile(0.95))
    locked = scale * float(Rv.sum()) * dt
    coverage = float((ev.abs() <= Rv).mean())
    shortfall = float((ev.abs() - Rv).clip(lower=0.0).sum()) * dt
    return {
        "locked_kwh_at_95": locked,
        "scale": scale,
        "coverage": coverage,
        "shortfall_kwh": shortfall,
        "n": float(Rv.shape[0]),
    }


def _run_site(site: int, cfg: dict[str, Any], emsx_dir: Path) -> dict[str, Any]:
    h = cfg["horizon"]
    df = _load_net_error(site, emsx_dir, str(h["load_col"]), str(h["pv_col"]), int(h["lag_steps"]))
    df = df.dropna(subset=["e"]).reset_index(drop=True)
    n = df.shape[0]
    n_train = int(n * 0.6)
    n_val = int(n * 0.2)
    dt = float(cfg["metrics"]["dt_h"])
    w_b2 = int(cfg["windows"]["B2_rolling_steps"])
    w_c = int(cfg["windows"]["C_regime_steps"])
    c_cfg = cfg["candidate_C"]
    factors = c_cfg["release_factors"]

    e = df["e"]
    hour = df["hour"]
    e_train, e_val = e.iloc[:n_train], e.iloc[n_train:n_train + n_val]
    hour_train, hour_val = hour.iloc[:n_train], hour.iloc[n_train:n_train + n_val]
    e_full = e.iloc[:n_train + n_val]
    hour_full = hour.iloc[:n_train + n_val]

    # B0 / B1（train 拟合）
    b0 = _policy_B0(e_train)
    b1_map = _policy_B1(e_train, hour_train)

    # B2（causal rolling，全序列后取 val）
    r_b2_full = _policy_B2(e_full, w_b2)
    r_b2 = r_b2_full.iloc[n_train:].reset_index(drop=True)

    # C（hour base × regime，regime 阈值 train 拟合）
    sig_full = e_full.abs().shift(1).rolling(w_c, min_periods=2).std()
    sig_train = sig_full.iloc[:n_train]
    low_thr = float(sig_train.quantile(1 / 3))
    high_thr = float(sig_train.quantile(2 / 3))
    r_c_full = _policy_C(
        e_full, hour_full, b1_map, low_thr, high_thr,
        float(factors["low"]), float(factors["normal"]), w_c,
    )
    r_c = r_c_full.iloc[n_train:].reset_index(drop=True)

    # 各臂 reserve 序列（val 段，与 e_val 对齐）
    e_val_reset = e_val.reset_index(drop=True)
    hour_val_reset = hour_val.reset_index(drop=True)
    r_b0 = pd.Series(b0, index=e_val_reset.index)
    r_b1 = hour_val_reset.map(b1_map)

    res = {
        "B0": _evaluate(r_b0, e_val_reset, dt),
        "B1": _evaluate(r_b1, e_val_reset, dt),
        "B2": _evaluate(r_b2, e_val_reset, dt),
        "C": _evaluate(r_c, e_val_reset, dt),
    }
    return {"site": site, "n_train": n_train, "n_val": n_val, "arms": res}


def run_r3a_dev() -> dict[str, Any]:
    cfg = load_yaml(_CONFIG)
    emsx_dir = Path(get_paths()["emsx"])
    sites = [int(s) for s in cfg["sites"]["dev"]]

    per_site = {s: _run_site(s, cfg, emsx_dir) for s in sites}

    # 聚合：median across sites 的 locked_kwh_at_95
    arms = ["B0", "B1", "B2", "C"]
    agg: dict[str, dict[str, float]] = {}
    for a in arms:
        vals = [per_site[s]["arms"][a]["locked_kwh_at_95"] for s in sites]
        vals = [v for v in vals if not np.isnan(v)]
        covs = [per_site[s]["arms"][a]["coverage"] for s in sites]
        agg[a] = {
            "locked_kwh_at_95_median": float(np.median(vals)) if vals else np.nan,
            "locked_kwh_at_95_mean": float(np.mean(vals)) if vals else np.nan,
            "coverage_median": float(np.median(covs)),
        }

    # strongest baseline = B1/B2 中 locked 更小者
    b1_med = agg["B1"]["locked_kwh_at_95_median"]
    b2_med = agg["B2"]["locked_kwh_at_95_median"]
    b1_is_strongest = not np.isnan(b1_med) and (np.isnan(b2_med) or b1_med <= b2_med)
    strongest_name = "B1" if b1_is_strongest else "B2"
    strongest_val = agg[strongest_name]["locked_kwh_at_95_median"]
    c_val = agg["C"]["locked_kwh_at_95_median"]

    reduction = (strongest_val - c_val) / strongest_val if strongest_val > 0 else np.nan

    gate = cfg["gate"]
    stop_frac = float(str(gate["dev_stop"]).split("<=")[-1].replace("%", "")) / 100
    if not np.isnan(reduction) and reduction >= float(gate["worth_pct"][0]):
        verdict = "GO"
    elif not np.isnan(reduction) and reduction <= stop_frac:
        verdict = "STOP"
    else:
        verdict = "CONDITIONAL"

    stats: dict[str, Any] = {
        "sites": sites,
        "verdict": verdict,
        "strongest_baseline": strongest_name,
        "strongest_locked_kwh": strongest_val,
        "c_locked_kwh": c_val,
        "reduction_pct": float(reduction * 100) if not np.isnan(reduction) else np.nan,
        "per_arm": agg,
        "per_site": per_site,
    }

    out_root = _PATENT_ROOT / str(cfg["outputs"]["results_root"])
    out_root.mkdir(parents=True, exist_ok=True)
    _write_report(cfg, stats)
    return stats


def _write_report(cfg: dict[str, Any], stats: dict[str, Any]) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    L: list[str] = []
    L.append("# CORE_SEARCH_R3A_DEV_GATE：动态 BESS 备用系统层（DEV）\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append("> 配置：configs/core_search_r3a.yaml（rule_version=core_search_r3a，冻结）\n")

    L.append("## 1. 目的\n")
    L.append("> 相同 PCC/缺额风险(0.95 coverage)下，谁锁定的 BESS 能量更少。\n")

    L.append("## 2. 各臂 locked_reserve_kwh_at_95（跨站中位）\n")
    L.append("| arm | locked_kwh_at_95 | coverage(原始) |")
    L.append("|---|---|---|")
    for a, v in stats["per_arm"].items():
        L.append(f"| {a} | {v['locked_kwh_at_95_median']:.1f} | {v['coverage_median']:.3f} |")
    L.append("")

    L.append("## 3. 各站各臂 locked_kwh_at_95\n")
    sites = stats["sites"]
    L.append("| site | " + " | ".join(["B0", "B1", "B2", "C"]) + " |")
    L.append("|" + "---|" * (len(sites) + 1))
    for s in sites:
        ps = stats["per_site"][s]
        vals = [f"{ps['arms'][a]['locked_kwh_at_95']:.1f}" for a in ["B0", "B1", "B2", "C"]]
        L.append(f"| {s} | " + " | ".join(vals) + " |")
    L.append("")

    L.append("## 4. 门判定\n")
    v = stats["verdict"]
    marker = {"GO": "**GO**", "STOP": "**STOP**", "CONDITIONAL": "**CONDITIONAL**"}
    L.append(f"### 判定：{marker.get(str(v), str(v))}\n")
    L.append(
        f"- strongest baseline：{stats['strongest_baseline']}"
        f"（locked {stats['strongest_locked_kwh']:.1f}）"
    )
    L.append(f"- C locked：{stats['c_locked_kwh']:.1f}")
    L.append(f"- C 相对 strongest 下降：{stats['reduction_pct']:.1f}%\n")
    if str(v) == "GO":
        L.append(
            "- C 相对 strongest simple baseline 下降 ≥15% → 可下载 6 个 holdout 站"
            "做单次 replication。\n"
        )
    elif str(v) == "STOP":
        L.append("- C 相对 strongest 下降 ≤10% → R3-A STOP，不消费 holdout。\n")
    else:
        L.append("- 下降处于 10~15% 灰区 → 仅诊断，不消费 holdout。\n")

    L.append("## 5. 纪律\n")
    L.append("- DEV 4 站只作 mechanism set，最终 CORE GO 必须在 6 holdout 站复现。")
    L.append("- 不把 fixed Q95(B0) 作为唯一 baseline；最强 baseline = B1/B2。\n")

    report_path = _PATENT_ROOT / str(cfg["outputs"]["report_dev"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
