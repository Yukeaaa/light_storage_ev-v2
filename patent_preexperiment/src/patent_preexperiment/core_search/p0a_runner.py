"""P0-A runner：真实 EV 响应时间谱执行入口（review §五；CORE-PATENT SEARCH 第一道零成本数据门）。

流程：读取 E7-FAST D0 已提取的 pilot_step_events.parquet（复用，不重新提取）→
binding/non-binding 分类 → response_fraction(1/3/5min) → 分层汇总 →
session repeatability → 门判定 → 写产物 + 报告。

gate 主判集 = train+validation（排除 external=office001 / stress）；
test 报告 single-exposure 可用量，不入 gate。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.config import CoreSearchConfig, load_core_search_config
from patent_preexperiment.core_search.p0a_response import (
    P0AGateVerdict,
    add_strata,
    classify_binding,
    compute_response_fraction,
    compute_session_repeatability,
    evaluate_p0a_gate,
    summarize_by_station,
    summarize_response,
)

_PATENT_ROOT = Path(__file__).resolve().parents[3]  # patent_preexperiment 实现区
_E7FAST_EVENTS = (
    _PATENT_ROOT / "results" / "raw" / "e7_fast" / "d0"
    / "d0_pilot_step_events.parquet"
)

_STRATA_DIMS = [
    "site", "station_id", "month", "session_phase",
    "actual_before_bin", "step_magnitude_bin", "previous_pilot_bin",
]


def run_p0a(
    cfg: CoreSearchConfig | None = None,
    *,
    events_path: str | Path | None = None,
) -> tuple[P0AGateVerdict, pd.DataFrame]:
    """执行 P0-A，返回 (verdict, binding_events) 并写出产物。"""
    cfg = cfg or load_core_search_config()
    ev_path = Path(events_path) if events_path else _E7FAST_EVENTS
    if not ev_path.exists():
        raise FileNotFoundError(
            f"未找到 E7-FAST D0 事件库：{ev_path}。请先运行 e7_fast D0（run_d0）。"
        )

    events = pd.read_parquet(ev_path)
    events = classify_binding(events, cfg.p0_a.binding)
    events = compute_response_fraction(events, cfg.p0_a.response)
    events = add_strata(events)

    # gate 主判集：train+validation（排除 external/stress）
    trainval = events[events["split"].isin(["train", "validation"])].copy()
    binding_trainval = trainval[trainval["binding"] == "binding"].copy()

    # 汇总
    lags = cfg.p0_a.response.lag_min
    response_summary = summarize_response(binding_trainval, lags)
    station_summary = summarize_by_station(binding_trainval, lag=3)
    repeatability, rep_corr = compute_session_repeatability(binding_trainval, lag=3)

    # 分层汇总（每层 binding 事件数 + response_fraction_3m median）
    strata_summary = _summarize_strata(binding_trainval)

    # 门判定
    verdict = evaluate_p0a_gate(binding_trainval, rep_corr, cfg.p0_a)

    # 写产物
    out_root = _PATENT_ROOT / cfg.p0_a.results_root
    out_root.mkdir(parents=True, exist_ok=True)
    # 全量 binding 事件（含 test/external/stress，标记供后续用）
    events[events["binding"] == "binding"].to_parquet(
        out_root / "binding_events.parquet", index=False
    )
    response_summary.to_csv(out_root / "response_1_3_5m_summary.csv", index=False)
    station_summary.to_csv(out_root / "station_response_summary.csv", index=False)
    repeatability.to_csv(out_root / "session_repeatability.csv", index=False)
    strata_summary.to_csv(out_root / "strata_binding_summary.csv", index=False)

    # 报告
    _write_report(
        cfg, verdict, events, binding_trainval, response_summary,
        station_summary, repeatability, rep_corr, strata_summary,
    )
    return verdict, events[events["binding"] == "binding"].copy()


def _summarize_strata(binding_tv: pd.DataFrame) -> pd.DataFrame:
    """按各分层维度汇总 binding 事件数 + response_fraction_3m median。"""
    if binding_tv.empty:
        return pd.DataFrame(columns=["dimension", "value", "events", "sessions", "rf_3m_median"])
    rf_col = "response_fraction_3m"
    rows: list[dict[str, object]] = []
    for dim in _STRATA_DIMS:
        if dim not in binding_tv.columns:
            continue
        for val, g in binding_tv.groupby(dim, observed=True):
            s = g[rf_col].dropna() if rf_col in g.columns else pd.Series(dtype=float)
            rows.append({
                "dimension": dim,
                "value": str(val),
                "events": int(g.shape[0]),
                "sessions": int(g["session_id"].nunique()),
                "rf_3m_median": float(s.median()) if not s.empty else np.nan,
            })
    return pd.DataFrame(rows)


def _write_report(
    cfg: CoreSearchConfig,
    verdict: P0AGateVerdict,
    all_events: pd.DataFrame,
    binding_tv: pd.DataFrame,
    response_summary: pd.DataFrame,
    station_summary: pd.DataFrame,
    repeatability: pd.DataFrame,
    rep_corr: float,
    strata_summary: pd.DataFrame,
) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    L: list[str] = []
    L.append("# CORE_P0_A：真实 EV 响应时间谱\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append(f"> 配置：`{cfg.config_path}`（rule_version={cfg.rule_version}，冻结）")
    L.append("> 依据：review/CORE-PATENT SEARCH：系统级核心专利筛选阶段.md §五")
    L.append(
        "> 数据来源：results/raw/e7_fast/d0/d0_pilot_step_events.parquet"
        "（E7-FAST D0 复用，DERIVED_REAL）\n"
    )

    L.append("## 1. 目的\n")
    L.append("> EV 到底是不是一种具有可利用时间动态的柔性资源？")
    L.append("> 严格区分 binding / non-binding 事件，对 binding 事件计算"
             " 1/3/5min response_fraction。\n")

    L.append("## 2. binding / non-binding 分类\n")
    tol = cfg.p0_a.binding.tolerance_kw
    L.append(f"- tolerance = {tol} kW")
    L.append(f"- binding decrease: pilot_after < actual_before − {tol}")
    L.append(f"- binding increase: pilot_after > actual_before + {tol}\n")

    total = all_events.shape[0]
    bind_total = int((all_events["binding"] == "binding").sum())
    L.append("### 全量事件分类（含 test/external/stress）\n")
    L.append("| direction | binding | events |")
    L.append("|---|---|---|")
    for (d, b), g in all_events.groupby(["direction", "binding"], observed=True):
        L.append(f"| {d} | {b} | {len(g)} |")
    L.append(f"| **合计** | | {total} |")
    L.append(f"| **binding 占比** | | {bind_total}/{total} = {bind_total/total*100:.1f}% |\n")

    L.append("### gate 主判集（train+validation，排除 external/stress）\n")
    L.append("| direction | binding | events | sessions | stations | months |")
    L.append("|---|---|---|---|---|---|")
    for d in ["up", "down"]:
        sub = binding_tv[binding_tv["direction"] == d]
        L.append(
            f"| {d} | binding | {len(sub)} | {sub['session_id'].nunique()} | "
            f"{sub['station_id'].nunique()} | {sub['month'].nunique()} |"
        )
    L.append("")

    L.append("## 3. response_fraction 汇总（binding 事件，train+validation）\n")
    L.append("- down: r = (actual_before − actual_lag) / (actual_before − pilot_after)")
    L.append("- up: r = (actual_lag − actual_before) / (pilot_after − actual_before)")
    L.append(f"- clip [{cfg.p0_a.response.fraction_clip_low}, "
             f"{cfg.p0_a.response.fraction_clip_high}]\n")
    if not response_summary.empty:
        L.append("| direction | lag_min | median | p25 | p75 | mean | std | count |")
        L.append("|---|---|---|---|---|---|---|---|")
        for _, r in response_summary.iterrows():
            L.append(
                f"| {r['direction']} | {int(r['lag_min'])} | {r['median']:.4f} | "
                f"{r['p25']:.4f} | {r['p75']:.4f} | {r['mean']:.4f} | {r['std']:.4f} | "
                f"{int(r['count'])} |"
            )
        L.append("")
        L.append("> **关键诊断**：1/3/5min median 是否不同 → 是否有可利用的时间动态。")
        L.append("> 若 1min median ≈ 1.0 且 std 很小 → 1min 内确定性完全响应"
                 " → BESS先接EV接力 无意义。\n")

    L.append("## 4. 车辆间响应异质性（station 级）\n")
    if not station_summary.empty:
        L.append(f"- station 数：{len(station_summary)}")
        L.append(f"- response_fraction_3m median 的 IQR（站间异质性）："
                 f"{verdict.heterogeneity_iqr:.4f}")
        L.append(f"- 判据：IQR > {cfg.p0_a.gate.heterogeneity_iqr_threshold} → 存在稳定异质性\n")

    L.append("## 5. session repeatability（同 session first → later）\n")
    L.append(f"- 有 >=2 binding 事件的 session 数：{len(repeatability)}")
    L.append(f"- first vs later response_fraction_3m Pearson corr：{rep_corr:.4f}"
             if not np.isnan(rep_corr) else "- corr：N/A（样本不足）")
    L.append(f"- 判据：|corr| > {cfg.p0_a.gate.repeatability_corr_threshold}"
             " → 最近响应对下次有信息价值\n")

    L.append("## 6. 分层汇总（binding 事件，train+validation）\n")
    if not strata_summary.empty:
        for dim in _STRATA_DIMS:
            sub = strata_summary[strata_summary["dimension"] == dim]
            if sub.empty:
                continue
            L.append(f"### 按 {dim}\n")
            L.append("| value | events | sessions | rf_3m_median |")
            L.append("|---|---|---|---|")
            for _, r in sub.sort_values("events", ascending=False).head(15).iterrows():
                med = f"{r['rf_3m_median']:.4f}" if not pd.isna(r["rf_3m_median"]) else "—"
                L.append(f"| {r['value']} | {int(r['events'])} | {int(r['sessions'])} | {med} |")
            L.append("")

    L.append("## 7. 门判定\n")
    marker = {"GO": "**GO**", "CONDITIONAL": "**CONDITIONAL**", "NO_GO": "**NO-GO**"}
    L.append(f"### 判定：{marker.get(verdict.verdict, verdict.verdict)}\n")
    L.append(f"> {verdict.reason}\n")
    L.append("| 指标 | 值 | 阈值 |")
    L.append("|---|---|---|")
    gate = cfg.p0_a.gate
    L.append(f"| binding up 事件 (train+val) | {verdict.binding_up_events} "
             f"| >={gate.usable_events_min} |")
    L.append(f"| binding down 事件 (train+val) | {verdict.binding_down_events} "
             f"| >={gate.usable_events_min} |")
    L.append(f"| binding up sessions | {verdict.binding_up_sessions} "
             f"| >={gate.unique_sessions_min} |")
    L.append(f"| binding down sessions | {verdict.binding_down_sessions} "
             f"| >={gate.unique_sessions_min} |")
    L.append(f"| binding up stations | {verdict.binding_up_stations} "
             f"| >={gate.stations_min} |")
    L.append(f"| binding down stations | {verdict.binding_down_stations} "
             f"| >={gate.stations_min} |")
    L.append(f"| binding up months | {verdict.binding_up_months} "
             f"| >={gate.months_min} |")
    L.append(f"| binding down months | {verdict.binding_down_months} "
             f"| >={gate.months_min} |")
    L.append(f"| rf_1m median up | {verdict.rf_1m_median_up:.4f} "
             f"| NO_GO if >{gate.no_go_1m_full_response_median} |")
    L.append(f"| rf_1m median down | {verdict.rf_1m_median_down:.4f} "
             f"| NO_GO if >{gate.no_go_1m_full_response_median} |")
    L.append(f"| rf_1m std up | {verdict.rf_1m_std_up:.4f} "
             f"| NO_GO if <{gate.no_go_1m_full_response_std} |")
    L.append(f"| rf_1m std down | {verdict.rf_1m_std_down:.4f} "
             f"| NO_GO if <{gate.no_go_1m_full_response_std} |")
    L.append(f"| rf_3m median up | {verdict.rf_3m_median_up:.4f} | — |")
    L.append(f"| rf_3m median down | {verdict.rf_3m_median_down:.4f} | — |")
    L.append(f"| rf_5m median up | {verdict.rf_5m_median_up:.4f} | — |")
    L.append(f"| rf_5m median down | {verdict.rf_5m_median_down:.4f} | — |")
    L.append(f"| 时间动态不同 | {verdict.time_dynamic_diff} | True |")
    L.append(f"| 异质性 IQR | {verdict.heterogeneity_iqr:.4f} "
             f"| >{gate.heterogeneity_iqr_threshold} |")
    L.append(f"| repeatability corr | {verdict.repeatability_corr:.4f} "
             f"| |corr|>{gate.repeatability_corr_threshold} |")
    L.append(f"| binding 充分 | {verdict.binding_sufficient} | True |")
    L.append(f"| 1min 确定性响应 | {verdict.no_go_deterministic_1m} | False |\n")

    L.append("## 8. Decision #1 含义\n")
    if verdict.verdict == "GO":
        L.append("- EV 具有可利用时间动态 → CORE-A（BESS-EV 接力）可启动。")
        L.append("- 配合 P0-B 量纲门，两门都过则正式启动 A/B/C。\n")
    elif verdict.verdict == "CONDITIONAL":
        L.append("- 时间动态信号弱，CORE-A 需谨慎；以 P0-B 量纲门为主要决策依据。\n")
    else:
        if verdict.no_go_deterministic_1m:
            L.append("- binding 后 1min 确定性完全响应 → **BESS先接EV慢慢接力 方向直接降级**。")
            L.append("- CORE-A 不启动；CORE-B/C 视 P0-B 量纲门决定。\n")
        else:
            L.append("- binding 事件不充分 → 需检查数据或调整方向。\n")

    L.append("## 9. 产物文件\n")
    L.append("- `results/raw/core_search/p0_a/binding_events.parquet`（全量 binding 事件）")
    L.append("- `results/raw/core_search/p0_a/response_1_3_5m_summary.csv`（1/3/5min 响应汇总）")
    L.append("- `results/raw/core_search/p0_a/station_response_summary.csv`（站级异质性）")
    L.append("- `results/raw/core_search/p0_a/session_repeatability.csv`（session 一致性）")
    L.append("- `results/raw/core_search/p0_a/strata_binding_summary.csv`（分层汇总）\n")

    report_path = _PATENT_ROOT / cfg.p0_a.report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
