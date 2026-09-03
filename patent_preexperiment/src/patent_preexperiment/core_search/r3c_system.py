"""R3-C：需量窗口预算控制系统层（四臂 + 共享 BESS 物理模型 + 连续 replay）。

核心 KPI：相同 demand-cap violation 下，BESS throughput/peak 减少多少。
四臂共享同一 BESS 模型、SOC、recharge 规则、P/E；连续 replay（窗口间 SOC 不重置）。
Candidate C = latest-safe feasibility boundary：剩余预算 × BESS 后续 Pmax/SOC/Eavail 联合边界，
只在到达边界时以最低必要功率介入。
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
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r3c.yaml"


def load_net_load(path: Path, load_col: str, pv_col: str) -> pd.Series:
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["unix_ref"], unit="s", utc=True)
    load = pd.to_numeric(df[load_col], errors="coerce") / 1000.0
    pv = pd.to_numeric(df[pv_col], errors="coerce") / 1000.0
    net = (load - pv).clip(lower=0.0)
    s = pd.Series(net.to_numpy(), index=ts).dropna()
    return s.groupby(s.index).mean().sort_index()


def _window_means(net: pd.Series, window_min: int) -> pd.Series:
    return net.groupby(pd.Grouper(freq=f"{window_min}min", origin="epoch")).mean().dropna()


def _bess_sizing(net: pd.Series, pcap: float, window_min: int) -> tuple[float, float]:
    excess = (net - pcap).clip(lower=0.0)
    pmax = float(excess.quantile(0.99))  # Q99 超限功率
    e_excess = excess.groupby(pd.Grouper(freq=f"{window_min}min", origin="epoch")).sum() / 60.0
    emax = float(e_excess.quantile(0.95))  # Q95 窗口超限电量
    return max(pmax, 1.0), max(emax, 1.0)


def _dispatch(
    arm: str, p_net: float, m: int, e_used: float, e_cap: float, r: int,
    soc: float, pmax: float, emax: float, soc_min: float, soc_max: float, eta_dis: float,
) -> float:
    """返回放电功率 d（kW）。"""
    pcap = e_cap * 4.0  # Pcap (kW) from E_cap (kWh) and 15min
    if arm == "B0":
        return max(p_net - pcap, 0.0)
    if arm in ("B1", "B2"):
        allowed_avg = (e_cap - e_used) * 60.0 / r if r > 0 else pcap
        return max(p_net - allowed_avg, 0.0)
    if arm == "C":
        # 若本分钟与未来均不放电（persistence），最终缺口
        deficit = max(e_used + p_net * r / 60.0 - e_cap, 0.0)
        # BESS 未来（本分钟之后）还能提供的最大补偿电量
        e_avail = max((soc - soc_min * emax) * eta_dis, 0.0)
        e_future = min(e_avail, pmax * (r - 1) / 60.0)
        d_energy = max(deficit - e_future, 0.0)
        return min(d_energy * 60.0, pmax)
    raise ValueError(f"unknown arm {arm}")


def _simulate(
    net: pd.Series, pcap: float, pmax: float, emax: float, arm: str, cfg: dict[str, Any]
) -> dict[str, float]:
    b = cfg["bess"]
    soc_min = float(b["soc_min"])
    soc_max = float(b["soc_max"])
    soc_init = float(b["soc_init"])
    eta_ch = float(b["eta_charge"])
    eta_dis = float(b["eta_discharge"])
    window_min = int(cfg["demand"]["window_min"])
    e_cap = pcap * window_min / 60.0
    dt_h = 1.0 / 60.0

    soc = soc_init * emax
    e_used = 0.0
    prev_window = None
    m = 1
    throughput = 0.0
    peak = 0.0
    actions = 0.0
    violation_kwh = 0.0
    violation_count = 0.0
    final_avgs: list[float] = []

    for ts, p_net in net.items():
        window = cast(pd.Timestamp, ts).floor(f"{window_min}min")
        if prev_window is None:
            prev_window = window
            m = 1
        elif window != prev_window:
            final_avg = e_used * (60.0 / window_min)
            final_avgs.append(final_avg)
            if final_avg > pcap:
                violation_count += 1
                violation_kwh += (final_avg - pcap) * window_min / 60.0
            prev_window = window
            e_used = 0.0
            m = 1
        else:
            m += 1
        r = window_min - m + 1

        d = _dispatch(arm, p_net, m, e_used, e_cap, r, soc, pmax, emax, soc_min, soc_max, eta_dis)
        # BESS 物理约束截断
        d = min(d, pmax)
        d = min(d, max((soc - soc_min * emax) * eta_dis * 60.0, 0.0))
        d = max(d, 0.0)

        c = 0.0
        if d == 0.0 and p_net < pcap and soc < soc_max * emax:
            c = min(pmax, pcap - p_net, (soc_max * emax - soc) * 60.0 * eta_ch)
            # 不使当前窗口累计超预算
            room = (e_cap - e_used - p_net * dt_h) / dt_h
            c = min(c, max(room, 0.0))
            c = max(c, 0.0)

        grid = p_net - d + c
        e_used += grid * dt_h
        soc += (c * eta_ch - d / eta_dis) * dt_h
        throughput += d * dt_h
        peak = max(peak, d)
        actions += 1.0 if d > 0.0 else 0.0

    if prev_window is not None:
        final_avg = e_used * (60.0 / window_min)
        final_avgs.append(final_avg)
        if final_avg > pcap:
            violation_count += 1
            violation_kwh += (final_avg - pcap) * window_min / 60.0

    return {
        "throughput_kwh": throughput,
        "peak_kw": peak,
        "actions": actions,
        "violation_kwh": violation_kwh,
        "violation_count": violation_count,
    }


def run_r3c() -> dict[str, Any]:
    cfg = load_yaml(_CONFIG)
    window_min = int(cfg["demand"]["window_min"])
    net = load_net_load(
        Path(get_paths()["building_1min"]) / "edificio_C_pro_power_2019.csv",
        str(cfg["data"]["load_col"]),
        str(cfg["data"]["pv_col"]),
    )
    means = _window_means(net, window_min)
    n = len(means)
    n_train = int(n * 0.6)
    n_val = int(n * 0.2)
    train_means = means.iloc[:n_train]
    pcap = float(train_means.quantile(0.90))

    # BESS sizing 用 train 段净负荷
    train_net = net.iloc[: n_train * window_min]
    pmax, emax = _bess_sizing(train_net, pcap, window_min)

    val_start = means.index[n_train]
    val_net = net[net.index >= val_start].iloc[: n_val * window_min]

    arms = ["B0", "B1", "B2", "C"]
    results = {a: _simulate(val_net, pcap, pmax, emax, a, cfg) for a in arms}

    # strongest baseline = B1/B2 中 throughput 更小者
    b1 = results["B1"]["throughput_kwh"]
    b2 = results["B2"]["throughput_kwh"]
    strongest = "B1" if b1 <= b2 else "B2"
    sv = results[strongest]
    cv = results["C"]

    if sv["throughput_kwh"] > 0:
        reduction = (sv["throughput_kwh"] - cv["throughput_kwh"]) / sv["throughput_kwh"]
    else:
        reduction = np.nan
    violation_ok = cv["violation_kwh"] <= sv["violation_kwh"] * 1.02

    gate = cfg["gate"]
    if (not np.isnan(reduction)) and reduction >= float(gate["worth_pct"][0]) and violation_ok:
        verdict = "GO"
    elif (not np.isnan(reduction)) and reduction <= float(gate["engineering_pct"][0]):
        verdict = "STOP"
    else:
        verdict = "CONDITIONAL"

    stats: dict[str, Any] = {
        "pcap": pcap,
        "pmax": pmax,
        "emax": emax,
        "n_train": n_train,
        "n_val": n_val,
        "strongest": strongest,
        "reduction_pct": float(reduction * 100) if not np.isnan(reduction) else np.nan,
        "violation_ok": violation_ok,
        "verdict": verdict,
        "results": results,
    }

    out_root = _PATENT_ROOT / str(cfg["outputs"]["results_root"])
    out_root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).T.to_csv(out_root / "r3c_arm_results.csv")
    _write_report(cfg, stats)
    return stats


def _write_report(cfg: dict[str, Any], stats: dict[str, Any]) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    L: list[str] = []
    L.append("# CORE_SEARCH_R3C_GATE：需量窗口预算控制系统层\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append("> 配置：configs/core_search_r3c.yaml（rule_version=core_search_r3c，冻结）\n")

    L.append("## 1. 场景\n")
    L.append(f"- Pcap (train Q90)：{stats['pcap']:.1f} kW")
    L.append(f"- BESS：Pmax {stats['pmax']:.1f} kW / Emax {stats['emax']:.1f} kWh\n")

    L.append("## 2. 各臂结果（validation 段）\n")
    L.append("| arm | throughput_kwh | peak_kw | actions | violation_kwh | violation_count |")
    L.append("|---|---|---|---|---|---|")
    for a, r in stats["results"].items():
        L.append(
            f"| {a} | {r['throughput_kwh']:.1f} | {r['peak_kw']:.1f} | {int(r['actions'])} | "
            f"{r['violation_kwh']:.1f} | {int(r['violation_count'])} |"
        )
    L.append("")

    L.append("## 3. 门判定\n")
    v = stats["verdict"]
    marker = {"GO": "**GO**", "STOP": "**STOP**", "CONDITIONAL": "**CONDITIONAL**"}
    L.append(f"### 判定：{marker.get(str(v), str(v))}\n")
    L.append(f"- strongest baseline：{stats['strongest']}")
    L.append(f"- C 相对 strongest throughput 下降：{stats['reduction_pct']:.1f}%")
    L.append(f"- violation 不劣化：{stats['violation_ok']}\n")

    report_path = _PATENT_ROOT / str(cfg["outputs"]["report"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
