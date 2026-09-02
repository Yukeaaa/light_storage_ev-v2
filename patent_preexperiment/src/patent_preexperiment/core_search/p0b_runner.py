"""P0-B runner：EV 群真实短时柔性规模执行入口（review §六；第二道零成本数据门）。

流程：读取 ACN 真实 5min 控制池 → 计算各档柔性口径 →
下调侧用 P0-A binding down 的 5min response_fraction median 校准 →
按 site/hour/concurrency 汇总 → 量纲门判定 → 写产物 + 报告。

r_down 校准默认从 P0-A 产物 `response_1_3_5m_summary.csv` 读取（显式数据依赖 P0-A → P0-B）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.config import CoreSearchConfig, load_core_search_config
from patent_preexperiment.core_search.p0b_flex import (
    P0BGateVerdict,
    compute_pool_flexibility,
    evaluate_p0b_gate,
    summarize_by_concurrency,
    summarize_by_hour,
    summarize_flex_scale,
)

_PATENT_ROOT = Path(__file__).resolve().parents[3]  # patent_preexperiment 实现区
_POOL_5MIN = (
    _PATENT_ROOT / "datasets" / "pool_state_5min" / "pool_state_5min.parquet"
)
_P0A_SUMMARY = (
    _PATENT_ROOT / "results" / "raw" / "core_search" / "p0_a"
    / "response_1_3_5m_summary.csv"
)


def load_r_down_calibration(summary_path: str | Path | None = None) -> float:
    """从 P0-A 响应汇总读取 binding down 的 5min response_fraction median。"""
    p = Path(summary_path) if summary_path else _P0A_SUMMARY
    if not p.exists():
        raise FileNotFoundError(
            f"未找到 P0-A 响应汇总：{p}。请先运行 P0-A（run_p0a）。"
        )
    summ = pd.read_csv(p)
    row = summ[(summ["direction"] == "down") & (summ["lag_min"] == 5)]
    if row.empty:
        raise ValueError("P0-A 响应汇总缺少 direction=down, lag_min=5 行")
    med = float(row["median"].iloc[0])
    if np.isnan(med):
        raise ValueError("P0-A binding down 5min median 为 NaN")
    return med


def run_p0b(
    cfg: CoreSearchConfig | None = None,
    *,
    r_down: float | None = None,
    pool_path: str | Path | None = None,
) -> tuple[P0BGateVerdict, pd.DataFrame]:
    """执行 P0-B，返回 (verdict, flex_pool_5min) 并写出产物。"""
    cfg = cfg or load_core_search_config()
    p = Path(pool_path) if pool_path else _POOL_5MIN
    if not p.exists():
        raise FileNotFoundError(f"未找到 5min 控制池：{p}")

    r_down = r_down if r_down is not None else load_r_down_calibration()
    pool = pd.read_parquet(p)
    flex = compute_pool_flexibility(pool, r_down)

    summary = summarize_flex_scale(flex)
    by_hour = summarize_by_hour(flex)
    by_concurrency = summarize_by_concurrency(flex)

    verdict = evaluate_p0b_gate(summary, cfg.p0_b, r_down)

    out_root = _PATENT_ROOT / cfg.p0_b.results_root
    out_root.mkdir(parents=True, exist_ok=True)
    flex.to_parquet(out_root / "flex_pool_5min.parquet", index=False)
    summary.to_csv(out_root / "flexibility_distribution.csv", index=False)
    by_hour.to_csv(out_root / "flexibility_by_hour.csv", index=False)
    by_concurrency.to_csv(out_root / "flexibility_by_concurrency.csv", index=False)

    _write_report(cfg, verdict, summary, by_hour, by_concurrency, r_down)
    return verdict, flex


def _write_report(
    cfg: CoreSearchConfig,
    verdict: P0BGateVerdict,
    summary: pd.DataFrame,
    by_hour: pd.DataFrame,
    by_concurrency: pd.DataFrame,
    r_down: float,
) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    g = cfg.p0_b.gate
    L: list[str] = []
    L.append("# CORE_P0_B：EV 群真实短时柔性规模\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append(f"> 配置：`{cfg.config_path}`（rule_version={cfg.rule_version}，冻结）")
    L.append("> 依据：review/CORE-PATENT SEARCH：系统级核心专利筛选阶段.md §六")
    L.append("> 数据来源：datasets/pool_state_5min/pool_state_5min.parquet（ACN 真实 5min 控制池）")
    L.append(f"> 下调校准：P0-A binding down 5min response_fraction median = {r_down:.4f}\n")

    L.append("## 1. 目的\n")
    L.append("> EV 是否真的足以改变 BESS 尺寸/运行？判断柔性功率与 100–200kW BESS 是否同量级。\n")

    L.append("## 2. 柔性口径\n")
    L.append("- F0 乐观上调：pilot headroom = max(P_pilot_total − P_actual_total, 0)")
    L.append("- F3 conservative 上调：0（没有足够证据不允许增加）")
    L.append(f"- 下调（可靠）：P_actual × r_down，r_down = {r_down:.4f}")
    L.append(
        "- 说明：F1 rolling-Q95 / F2 M2 需会话级历史，本版（量纲门）不展开；"
        "15min 池当前缺失，仅 5min。\n"
    )

    L.append("## 3. 各独立控制池量纲汇总\n")
    if not summary.empty:
        cols = [
            "site", "garage", "periods", "pilot_coverage_mean",
            "ev_peak_kw", "ev_p95_kw", "ev_p50_kw",
            "flex_up_f0_peak_kw", "flex_down_reliable_peak_kw",
            "flex_down_reliable_p95_kw", "flex_down_reliable_p50_kw",
            "flex_to_ev_peak_ratio",
        ]
        L.append("| " + " | ".join(cols) + " |")
        L.append("|" + "|".join(["---"] * len(cols)) + "|")
        for _, r in summary.iterrows():
            L.append(
                f"| {r['site']} | {r['garage']} | {int(r['periods'])} | "
                f"{r['pilot_coverage_mean']:.3f} | {r['ev_peak_kw']:.1f} | "
                f"{r['ev_p95_kw']:.1f} | {r['ev_p50_kw']:.1f} | "
                f"{r['flex_up_f0_peak_kw']:.1f} | {r['flex_down_reliable_peak_kw']:.1f} | "
                f"{r['flex_down_reliable_p95_kw']:.1f} | {r['flex_down_reliable_p50_kw']:.1f} | "
                f"{r['flex_to_ev_peak_ratio']:.3f} |"
            )
        L.append("")
        L.append("> 每个 site 对应一个独立 garage 控制池，池之间不可加总。\n")

    L.append("## 4. 按小时（p95）\n")
    if not by_hour.empty:
        L.append("| hour | periods | ev_p95_kw | down_reliable_p95_kw |")
        L.append("|---|---|---|---|")
        for _, r in by_hour.iterrows():
            L.append(
                f"| {int(r['hour'])} | {int(r['periods'])} | {r['ev_p95_kw']:.1f} | "
                f"{r['down_reliable_p95_kw']:.1f} |"
            )
        L.append("")

    L.append("## 5. 按并发活动会话数（p95）\n")
    if not by_concurrency.empty:
        L.append("| concurrency_bin | periods | ev_p95_kw | down_reliable_p95_kw |")
        L.append("|---|---|---|---|")
        for _, r in by_concurrency.iterrows():
            L.append(
                f"| {r['concurrency_bin']} | {int(r['periods'])} | {r['ev_p95_kw']:.1f} | "
                f"{r['down_reliable_p95_kw']:.1f} |"
            )
        L.append("")

    L.append("## 6. 门判定\n")
    marker = {"GO": "**GO**", "NO_GO": "**NO-GO**"}
    L.append(f"### 判定：{marker.get(verdict.verdict, verdict.verdict)}\n")
    L.append(f"> {verdict.reason}\n")
    L.append("| 指标 | 值 | 阈值 |")
    L.append("|---|---|---|")
    L.append(f"| EV 峰值功率（最大池） | {verdict.ev_peak_kw:.1f} kW | — |")
    L.append(f"| EV p95 功率（最大池） | {verdict.ev_p95_kw:.1f} kW | — |")
    L.append(f"| 乐观上调柔性峰值 F0 | {verdict.flex_up_f0_peak_kw:.1f} kW | — |")
    L.append(
        f"| 可靠下调柔性峰值 | {verdict.flex_down_reliable_peak_kw:.1f} kW | "
        f">={g.go_reliable_flex_peak_min_kw:.0f} |"
    )
    L.append(
        f"| 可靠下调柔性 p95 | {verdict.flex_down_reliable_p95_kw:.1f} kW | — |"
    )
    L.append(
        f"| 柔性/EV 峰值比 | {verdict.flex_to_ev_peak_ratio:.3f} | — |"
    )
    L.append(
        f"| BESS 量级比较 | {g.bess_comparison_kw_low:.0f}–"
        f"{g.bess_comparison_kw_high:.0f} kW | — |\n"
    )

    L.append("## 7. Decision #1 含义\n")
    if verdict.verdict == "GO":
        L.append("- EV 柔性与 BESS 同量级 → CORE-A/B/C 均可启动（配合 P0-A GO）。\n")
    else:
        L.append("- EV 柔性量纲不足 → CORE-B（最小 BESS sizing）/CORE-C（动态 reserve）不启动。")
        L.append("- CORE-A（BESS-EV 快慢接力）依赖时间动态而非量纲，可单独评估，")
        L.append("  但其 BESS 节省上限受 EV 柔性峰值约束，需谨慎。\n")

    L.append("## 8. 产物文件\n")
    L.append("- `results/raw/core_search/p0_b/flex_pool_5min.parquet`（逐周期柔性）")
    L.append("- `results/raw/core_search/p0_b/flexibility_distribution.csv`（分池量纲）")
    L.append("- `results/raw/core_search/p0_b/flexibility_by_hour.csv`（按小时）")
    L.append("- `results/raw/core_search/p0_b/flexibility_by_concurrency.csv`（按并发）\n")
    L.append("> 注：flex_pool_15min.parquet 因 15min 池缺失未产出。\n")

    report_path = _PATENT_ROOT / cfg.p0_b.report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
