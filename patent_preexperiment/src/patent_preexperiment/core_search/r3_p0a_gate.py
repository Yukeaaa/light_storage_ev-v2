"""R3-P0-A：真实 forecast-error / reserve-opportunity 数据门（Round 3 第一道杀伤门）。

回答：
1. 净负荷 forecast error 正/负误差是否明显非对称？
2. 固定 Q95 reserve 有多少时间根本用不到（idle fraction）？
3. reserve requirement 是否随状态(小时)变化足够大（hour-Q95 spread）？

数据：EMSx 真实 actual_consumption / actual_pv + load_XX / pv_XX 历史 forecast。
error_h[t] = (actual_consumption[t+h] - actual_pv[t+h]) - (load_{h}[t] - pv_{h}[t])。
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
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r3_p0a.yaml"


def _load_site(site: int, emsx_dir: Path) -> pd.DataFrame:
    f = emsx_dir / f"{site}.csv.gz"
    if not f.exists():
        raise FileNotFoundError(f"缺少 EMSx site 文件：{f}")
    df = pd.read_csv(f, sep=";", compression="gzip").copy()
    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _forecast_error(df: pd.DataFrame, load_col: str, pv_col: str, lag_steps: int) -> pd.Series:
    net_actual = df["actual_consumption"] - df["actual_pv"]
    net_fc = df[load_col] - df[pv_col]
    err = net_actual.shift(-lag_steps) - net_fc
    return err


def _site_stats(df: pd.DataFrame, horizons: dict[str, Any], reserve_q: float) -> dict[str, Any]:
    hour = df["ts"].dt.hour
    out: dict[str, Any] = {"n_steps": int(df.shape[0])}
    for name, h in horizons.items():
        err = _forecast_error(df, str(h["load_col"]), str(h["pv_col"]), int(h["lag_steps"]))
        err = err.dropna()
        hr = hour.iloc[: len(err)]
        q95 = float(err.abs().quantile(reserve_q))
        pos = err[err > 0]
        neg = err[err < 0]
        hour_q = err.abs().groupby(hr).quantile(reserve_q)
        spread = float(hour_q.max() / hour_q.min()) if hour_q.min() > 0 else np.nan
        idle = float((err.abs() < 0.5 * q95).mean())
        asym = (
            float(pos.quantile(reserve_q) / neg.abs().quantile(reserve_q))
            if len(pos) > 0 and len(neg) > 0 and neg.abs().quantile(reserve_q) > 0
            else np.nan
        )
        out[name] = {
            "q95_abs": q95,
            "mean": float(err.mean()),
            "std": float(err.std()),
            "p_pos": float((err > 0).mean()),
            "asym_pos_neg_q95": asym,
            "hour_q95_min": float(hour_q.min()),
            "hour_q95_max": float(hour_q.max()),
            "hour_q95_spread": spread,
            "idle_fraction": idle,
        }
    return out


def run_r3_p0a() -> dict[str, object]:
    cfg = load_yaml(_CONFIG)
    emsx_dir = Path(get_paths()["emsx"])
    sites = [int(s) for s in cfg["data"]["sites"]]
    horizons = cfg["horizons"]
    reserve_q = float(cfg["metrics"]["reserve_quantile"])

    rows: dict[int, dict[str, Any]] = {}
    for site in sites:
        df = _load_site(site, emsx_dir)
        rows[site] = _site_stats(df, horizons, reserve_q)

    # 门判定（以 15min 主口径）
    gate = cfg["gate"]
    ratio_min = float(gate["reserve_variation_ratio_min"])
    idle_min = float(gate["idle_fraction_min"])
    per_site_go = {}
    for site, st in rows.items():
        r15 = st["15min"]
        per_site_go[site] = bool(
            (not np.isnan(r15["hour_q95_spread"]) and r15["hour_q95_spread"] >= ratio_min)
            and (not np.isnan(r15["idle_fraction"]) and r15["idle_fraction"] >= idle_min)
        )
    n_go = sum(per_site_go.values())
    verdict = "GO" if n_go >= len(sites) * 0.5 else "NO_GO"

    stats: dict[str, Any] = {
        "sites": sites,
        "verdict": verdict,
        "n_sites_go": n_go,
        "n_sites": len(sites),
        "per_site": rows,
    }

    out_root = _PATENT_ROOT / str(cfg["outputs"]["results_root"])
    out_root.mkdir(parents=True, exist_ok=True)
    pd.Series({k: str(v) for k, v in per_site_go.items()}).to_csv(
        out_root / "r3_p0a_per_site_go.csv", header=["go"]
    )
    _write_report(cfg, stats)
    return stats


def _write_report(cfg: dict[str, Any], stats: dict[str, Any]) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    L: list[str] = []
    L.append("# CORE_SEARCH_R3_P0A_GATE：真实 forecast-error / reserve-opportunity 数据门\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append("> 配置：configs/core_search_r3_p0a.yaml（rule_version=core_search_r3_p0a，冻结）\n")

    L.append("## 1. 目的\n")
    L.append("> 固定 Q95 备用是否长期过度保守？reserve requirement 是否随状态变化足够大？\n")

    L.append("## 2. 净负荷 forecast error（kWh/15min，Q95 备用口径）\n")
    L.append("| site | 前瞻 | Q95\\|err\\| | 均值 | std | P(pos) | 非对称(正Q95/\\|负Q95\\|) | "
             "小时Q95 min/max | spread | idle |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for site, st in stats["per_site"].items():
        for h in ["15min", "30min", "60min"]:
            r = st[h]
            L.append(
                f"| {site} | {h} | {r['q95_abs']:.1f} | {r['mean']:.2f} | {r['std']:.1f} | "
                f"{r['p_pos']:.2f} | {r['asym_pos_neg_q95']:.2f} | "
                f"{r['hour_q95_min']:.1f}/{r['hour_q95_max']:.1f} | "
                f"{r['hour_q95_spread']:.2f} | {r['idle_fraction']:.2f} |"
            )
    L.append("")

    L.append("## 3. 三个关键问题\n")
    L.append(
        "- 正/负误差是否明显非对称？→ 看 `非对称` 列（≈1.0 为对称；R3-B 方向分离需更强证据）。"
    )
    L.append("- 固定 Q95 有多少时间用不到？→ `idle` = |error| < 0.5×Q95 的时间占比。")
    L.append("- reserve 是否随状态变化足够大？→ `小时Q95 spread` = 小时级 Q95 的 max/min。\n")

    L.append("## 4. 门判定\n")
    v = stats["verdict"]
    marker = {"GO": "**GO**", "NO_GO": "**NO-GO**"}.get(str(v), str(v))
    L.append(f"### 判定：{marker}\n")
    L.append(f"- 站点通过门数：{stats['n_sites_go']} / {stats['n_sites']}\n")
    if str(v) == "GO":
        L.append("- reserve requirement 随小时变化大且固定备用大量闲置 → 动态备用有肉，")
        L.append("  可进入 R3-A/R3-B 系统层预注册。\n")
    else:
        L.append("- reserve 几乎不随状态变化 → 动态备用无增量，关闭 R3-A/B。\n")

    report_path = _PATENT_ROOT / str(cfg["outputs"]["report"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
