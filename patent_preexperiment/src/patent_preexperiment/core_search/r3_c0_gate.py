"""R3-C0：需量窗口机会存在性门（不建控制器，只统计机会）。

问题：真实 1min 负荷里，多少"瞬时超限"是 false alarm（15min 平均不超），
多少"真超限"可以延迟到窗口后段才动作？

窗口分类：
- trigger      : max(1min) > Pcap
- false_alarm  : trigger 且 mean <= Pcap
- violation    : mean > Pcap
- m_unavoidable: 首个累计电量 > Pcap*15min 的分钟（再等就来不及）
- delayable    : violation 且 m_unavoidable >= 8
- unavoidable  : violation 且 m_unavoidable < 8
opportunity = (false_alarm + delayable) / trigger_windows
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.io.paths import get_paths

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r3c0.yaml"


def _load_load_series(path: Path, load_col: str) -> pd.Series:
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["unix_ref"], unit="s", utc=True)
    p_kw = pd.to_numeric(df[load_col], errors="coerce") / 1000.0  # W -> kW
    s = pd.Series(p_kw.to_numpy(), index=ts).dropna()
    # 数据每分钟约 2 行重复时间戳 → 按时间戳聚合去重
    s = s.groupby(s.index).mean()
    return s.sort_index()


def _windowize(load: pd.Series, length_min: int) -> pd.DataFrame:
    """固定时钟对齐的 15min 窗口：每窗口 mean/max 与逐分钟累计能量。"""
    grp = load.groupby(pd.Grouper(freq=f"{length_min}min", origin="epoch"))
    mean = grp.mean()
    maxv = grp.max()
    n = grp.count()
    # 逐分钟累计能量（kWh），用于 m_unavoidable
    cum = load.cumsum() / 60.0  # kWh (kW * min / 60)
    # 每个窗口结束时刻的累计
    window_cum_end = cum.groupby(pd.Grouper(freq=f"{length_min}min", origin="epoch")).last()
    # 窗口开始时刻的累计（= 上一窗口结束）
    window_cum_start = window_cum_end.shift(1).fillna(0.0)

    out = pd.DataFrame({
        "mean_kw": mean,
        "max_kw": maxv,
        "n": n,
        "cum_start_kwh": window_cum_start,
        "cum_end_kwh": window_cum_end,
    }).dropna(subset=["mean_kw"])
    return out[out["n"] == length_min].copy()


def _classify(windows: pd.DataFrame, pcap: float) -> pd.DataFrame:
    w = windows.copy()
    w["trigger"] = w["max_kw"] > pcap
    w["violation"] = w["mean_kw"] > pcap
    w["false_alarm"] = w["trigger"] & ~w["violation"]
    w["m_unavoidable"] = np.nan
    w["delayable"] = False
    w["unavoidable"] = False
    return w


def _m_unavoidable_per_window(
    load: pd.Series, windows: pd.DataFrame, pcap: float, length_min: int
) -> pd.Series:
    """精确计算每个 violation 窗口的 m_unavoidable（相对窗口起点，1-indexed）。"""
    e_cap = pcap * length_min / 60.0  # kWh
    result = pd.Series(np.nan, index=windows.index)
    for idx in windows.index[windows["violation"]]:
        w = load[idx: idx + pd.Timedelta(minutes=length_min)]
        cum = w.cumsum() / 60.0  # kWh
        first = (cum > e_cap).idxmax() if (cum > e_cap).any() else None
        if first is not None:
            result[idx] = float((first - idx).total_seconds() / 60.0) + 1.0
    return result


def run_r3_c0() -> dict[str, Any]:
    cfg = load_yaml(_CONFIG)
    length_min = int(cfg["window"]["length_min"])
    delayable_min = int(cfg["gate"]["delayable_threshold_min"])
    load = _load_load_series(
        Path(get_paths()["building_1min"]) / "edificio_C_pro_power_2019.csv",
        str(cfg["data"]["load_col"]),
    )
    windows = _windowize(load, length_min)

    # 时序 60/20/20，Pcap = train Q90
    n = len(windows)
    n_train = int(n * 0.6)
    train_mean = windows["mean_kw"].iloc[:n_train]
    pcap = float(train_mean.quantile(0.90))
    pcap_q85 = float(train_mean.quantile(0.85))
    pcap_q95 = float(train_mean.quantile(0.95))

    w = _classify(windows, pcap)
    m = _m_unavoidable_per_window(load, w, pcap, length_min)
    w["m_unavoidable"] = m
    w["delayable"] = w["violation"] & (w["m_unavoidable"] >= delayable_min)
    w["unavoidable"] = w["violation"] & (w["m_unavoidable"] < delayable_min)

    # 门判定用 validation 段
    n_val = int(n * 0.2)
    val = w.iloc[n_train:n_train + n_val]
    trigger = int(val["trigger"].sum())
    false_alarm = int(val["false_alarm"].sum())
    delayable = int(val["delayable"].sum())
    unavoidable = int(val["unavoidable"].sum())
    opp = (false_alarm + delayable) / trigger if trigger > 0 else np.nan

    gate = cfg["gate"]
    if not np.isnan(opp):
        if opp < float(gate["stop_max"]):
            verdict = "STOP"
        elif opp >= float(gate["strong_min"]):
            verdict = "GO"
        else:
            verdict = "CONDITIONAL"
    else:
        verdict = "STOP"

    stats: dict[str, Any] = {
        "n_windows_total": int(n),
        "n_train": n_train,
        "n_val": n_val,
        "pcap_q90": pcap,
        "pcap_q85": pcap_q85,
        "pcap_q95": pcap_q95,
        "trigger": trigger,
        "false_alarm": false_alarm,
        "delayable": delayable,
        "unavoidable": unavoidable,
        "opportunity_fraction": float(opp) if not np.isnan(opp) else np.nan,
        "verdict": verdict,
    }

    out_root = _PATENT_ROOT / str(cfg["outputs"]["results_root"])
    out_root.mkdir(parents=True, exist_ok=True)
    w.to_csv(out_root / "r3_c0_windows.csv", index=True)
    pd.Series(stats).to_csv(out_root / "r3_c0_gate_stats.csv", header=["value"])

    _write_report(cfg, stats)
    return stats


def _write_report(cfg: dict[str, Any], stats: dict[str, Any]) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    L: list[str] = []
    L.append("# CORE_SEARCH_R3_C0_GATE：需量窗口机会存在性门\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append("> 配置：configs/core_search_r3c0.yaml（rule_version=core_search_r3c0，冻结）\n")

    L.append("## 1. 目的\n")
    L.append("> 真实 1min 负荷里，多少瞬时超限是 false alarm / 可延迟动作。不建控制器。\n")

    L.append("## 2. 窗口分类（validation 段）\n")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append(f"| 总窗口数 | {stats['n_windows_total']} |")
    L.append(f"| train / val 窗口 | {stats['n_train']} / {stats['n_val']} |")
    L.append(f"| Pcap (train Q90) | {stats['pcap_q90']:.1f} kW |")
    L.append(f"| Pcap Q85 / Q95 | {stats['pcap_q85']:.1f} / {stats['pcap_q95']:.1f} kW |")
    L.append(f"| trigger 窗口(max>Pcap) | {stats['trigger']} |")
    L.append(f"| false alarm(A) | {stats['false_alarm']} |")
    L.append(f"| delayable(B) | {stats['delayable']} |")
    L.append(f"| unavoidable(C) | {stats['unavoidable']} |")
    L.append(f"| opportunity=(A+B)/trigger | {stats['opportunity_fraction']:.3f} |\n")

    L.append("## 3. 门判定\n")
    v = stats["verdict"]
    marker = {"STOP": "**STOP**", "CONDITIONAL": "**CONDITIONAL**", "GO": "**GO**"}
    L.append(f"### 判定：{marker.get(str(v), str(v))}\n")
    L.append(f"> opportunity = {stats['opportunity_fraction']:.3f}\n")
    if str(v) == "GO":
        L.append("- 机会显著(>0.30) → 可进入 R3-C 系统层 B0/B1/B2/C 预注册。\n")
    elif str(v) == "STOP":
        L.append("- 机会不足(<0.10) → R3-C STOP。\n")
    else:
        L.append("- 机会中等 → 需进一步判断，暂不建控制器。\n")

    L.append("## 4. 术语\n")
    L.append("- demand-ceiling scenario，非真实合同需量。\n")

    report_path = _PATENT_ROOT / str(cfg["outputs"]["report"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
