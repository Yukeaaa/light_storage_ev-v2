"""E7-FAST D0 runner：数据充分性门执行入口（review §4-7 / §36 step 2-4）。

流程：加载 E0 冻结 1-min 会话表（按 site 分批控内存）→ attach_info_class →
D0-1 信息覆盖审计 → D0-2 自然 pilot step 事件库 → 充分性门判定 → 报告 + 证据台账。
阈值全部来自 configs/e7_fast.yaml（冻结）；不在代码硬编码。
"""

from __future__ import annotations

import glob
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from patent_preexperiment.e7_fast.config import E7FastConfig, load_e7_fast_config
from patent_preexperiment.e7_fast.data_sufficiency import (
    D0Result,
    GateVerdict,
    compute_info_coverage,
    evaluate_sufficiency_gate,
)
from patent_preexperiment.e7_fast.info_class import attach_info_class
from patent_preexperiment.e7_fast.pilot_steps import extract_pilot_step_events

_DATA_BASE = Path(__file__).resolve().parents[3] / "datasets" / "session_response_1min"
_RESULTS_BASE = Path(__file__).resolve().parents[3] / "results" / "raw" / "e7_fast"
_REPORTS_BASE = Path(__file__).resolve().parents[3] / "reports"

_LOAD_COLUMNS = [
    "session_id", "station_id", "site", "garage", "split", "field_mode",
    "timestamp_utc", "connected_elapsed_min", "done_charging_time",
    "actual_power_kw", "pilot_a", "pilot_power_kw", "pilot_available",
    "severe_gap_before", "gap_before_min",
]


def load_session_1min_site(base: Path, site: str, columns: list[str]) -> pd.DataFrame:
    """加载某 site 的全部分区 1-min parquet（只读所需列）。"""
    pattern = str(base / f"site={site}" / "**" / "*.parquet")
    files = sorted(glob.glob(pattern, recursive=True))
    if not files:
        raise FileNotFoundError(f"未找到 site={site} 的 1-min 分区：{pattern}")
    parts = [pd.read_parquet(f, columns=columns) for f in files]
    return pd.concat(parts, ignore_index=True)


def run_d0(cfg: E7FastConfig | None = None, *, sites: list[str] | None = None) -> D0Result:
    """执行 D0 数据充分性门，返回 D0Result 并写出产物。"""
    cfg = cfg or load_e7_fast_config()
    sites = sites or ["caltech", "jpl", "office001"]

    detail_parts: list[pd.DataFrame] = []
    summary_parts: list[pd.DataFrame] = []
    event_parts: list[pd.DataFrame] = []

    for site in sites:
        df = load_session_1min_site(_DATA_BASE, site, _LOAD_COLUMNS)
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        df["done_charging_time"] = pd.to_datetime(
            df["done_charging_time"], errors="coerce", utc=True
        )
        df_info = attach_info_class(df, cfg)
        detail, summary = compute_info_coverage(df_info)
        detail_parts.append(detail)
        summary_parts.append(summary)
        events = extract_pilot_step_events(df_info, cfg)
        event_parts.append(events)
        del df, df_info

    info_detail = pd.concat(detail_parts, ignore_index=True) if detail_parts else pd.DataFrame()
    info_summary = pd.concat(summary_parts, ignore_index=True) if summary_parts else pd.DataFrame()
    all_events = pd.concat([e for e in event_parts if not e.empty], ignore_index=True) if any(
        not e.empty for e in event_parts
    ) else pd.DataFrame(columns=["direction"])

    verdict = evaluate_sufficiency_gate(all_events, cfg)

    # --- 写出产物 ---
    _RESULTS_BASE.mkdir(parents=True, exist_ok=True)
    info_detail.to_csv(_RESULTS_BASE / "d0" / "d0_info_mode_coverage.csv", index=False)
    info_summary.to_csv(_RESULTS_BASE / "d0" / "d0_info_mode_summary.csv", index=False)
    all_events.to_parquet(_RESULTS_BASE / "d0" / "d0_pilot_step_events.parquet", index=False)
    _write_evidence_registry(cfg, verdict, info_summary, all_events)
    _write_report(cfg, verdict, info_summary, all_events)

    return D0Result(
        info_coverage_detail=info_detail,
        info_coverage_summary=info_summary,
        events=all_events,
        verdict=verdict,
    )


def _write_evidence_registry(
    cfg: E7FastConfig,
    verdict: GateVerdict,
    info_summary: pd.DataFrame,
    events: pd.DataFrame,
) -> None:
    rows = [
        {"item": "config_path", "value": cfg.config_path, "evidence": "FROZEN"},
        {"item": "rule_version", "value": cfg.rule_version, "evidence": "FROZEN"},
        {"item": "gate_level", "value": verdict.level, "evidence": "D0"},
        {"item": "gate_verdict", "value": verdict.verdict, "evidence": "D0"},
        {"item": "positive_events_train_val", "value": verdict.positive_events,
         "evidence": "D0"},
        {"item": "positive_sessions_train_val", "value": verdict.positive_sessions,
         "evidence": "D0"},
        {"item": "positive_stations_train_val", "value": verdict.positive_stations,
         "evidence": "D0"},
        {"item": "positive_months_train_val", "value": verdict.positive_months,
         "evidence": "D0"},
        {"item": "negative_events_train_val", "value": verdict.negative_events,
         "evidence": "D0"},
        {"item": "negative_sufficient", "value": verdict.negative_sufficient,
         "evidence": "D0"},
        {"item": "test_positive_events", "value": verdict.test_positive_events,
         "evidence": "D0"},
        {"item": "external_positive_events", "value": verdict.external_positive_events,
         "evidence": "D0"},
    ]
    for info_mode in sorted(info_summary["info_mode"].unique()) if not info_summary.empty else []:
        sub = info_summary[info_summary["info_mode"] == info_mode]
        rows.append({
            "item": f"coverage_{info_mode}_cycles",
            "value": int(sub["cycle_count"].sum()),
            "evidence": "D0-1",
        })
    pd.DataFrame(rows).to_csv(_RESULTS_BASE / "d0" / "d0_evidence_registry.csv", index=False)


def _write_report(
    cfg: E7FastConfig,
    verdict: GateVerdict,
    info_summary: pd.DataFrame,
    events: pd.DataFrame,
) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []
    lines.append("# E7-FAST D0 数据充分性门报告\n")
    lines.append(f"> 生成时间（UTC）：{ts}")
    lines.append(f"> 配置：`{cfg.config_path}`（rule_version={cfg.rule_version}，冻结）")
    lines.append("> 依据：review/工商业园区光储充快速闭环验证.md §4-7 / §36 step 2-4\n")

    lines.append("## 1. 冻结纪律\n")
    lines.append("- 阈值/规则在查看任何事件计数前冻结于 `configs/e7_fast.yaml`。")
    lines.append("- gate 主判集 = train+validation（拟合集）；test 报告 single-exposure 可用量；"
                 "office001 external 单列不计入 gate。")
    lines.append("- 不修改 frozen P2/P2.1；只读复用 phase3_p2.d1 / phase3_p2.boundary。\n")

    lines.append("## 2. D0-1 信息类别覆盖审计\n")
    if info_summary.empty:
        lines.append("（无数据）\n")
    else:
        lines.append("### 按 site × info_mode × split 汇总\n")
        lines.append(
            "| site | info_mode | split | cycle_count | session_count | "
            "station_count | month_count | share_of_active_min |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for _, r in info_summary.iterrows():
            lines.append(
                f"| {r['site']} | {r['info_mode']} | {r['split']} | "
                f"{int(r['cycle_count'])} | {int(r['session_count'])} | "
                f"{int(r['station_count'])} | {int(r['month_count'])} | "
                f"{r['share_of_active_min']} |"
            )
        lines.append("")
        lines.append("> 关注：M2_pilot_actual（pilot+actual+history 充分）"
                     "是否覆盖足够多 cycle/session/station/month；")
        lines.append("> M3_current_only（actual+history，无 pilot）"
                     "是否广泛存在（current-only 主数据现实）。\n")

    lines.append("## 3. D0-2 自然 pilot step 事件库\n")
    if events.empty:
        lines.append("（未提取到任何事件）\n")
    else:
        lines.append("### 按 direction × site × split 事件计数\n")
        lines.append("| direction | site | split | events | sessions | stations | months |")
        lines.append("|---|---|---|---|---|---|---|")
        for (d, s, sp), g in events.groupby(["direction", "site", "split"], observed=True):
            lines.append(
                f"| {d} | {s} | {sp} | {len(g)} | {g['session_id'].nunique()} | "
                f"{g['station_id'].nunique()} | {g['month'].nunique()} |"
            )
        lines.append("")

    lines.append("## 4. 数据充分性门判定（review §7 三级门）\n")
    lines.append("**gate 主判集（train+validation，排除 office001/stress）**\n")
    lines.append("| 指标 | 值 | 阈值 |")
    lines.append("|---|---|---|")
    pg = cfg.d0.positive_gate
    ng = cfg.d0.negative_gate
    lines.append(f"| 正向上调事件 | {verdict.positive_events} | "
                 f"A>={pg.a_events} / B {pg.b_low}-{pg.b_high} / C<{pg.c_max+1} |")
    lines.append(f"| 正向 unique sessions | {verdict.positive_sessions} | A>={pg.a_sessions} |")
    lines.append(f"| 正向 stations | {verdict.positive_stations} | A>={pg.a_stations} |")
    lines.append(f"| 正向 months | {verdict.positive_months} | A>={pg.a_months} |")
    lines.append(f"| 负向事件 | {verdict.negative_events} | >={ng.events_min} |")
    lines.append(f"| 负向 sessions | {verdict.negative_sessions} | >={ng.sessions_min} |")
    lines.append(f"| 负向 stations | {verdict.negative_stations} | >={ng.stations_min} |")
    lines.append(f"| 负向充分(neg_sufficient) | {verdict.negative_sufficient} | True |")
    lines.append(f"| test 正向事件（single-exposure 可用量，不入 gate） | "
                 f"{verdict.test_positive_events} | — |")
    lines.append(f"| external(office001) 正向事件（不入 gate） | "
                 f"{verdict.external_positive_events} | — |\n")

    verdict_marker = (
        "GO" if verdict.level == "A_level"
        else ("CONDITIONAL" if verdict.level == "B_level" else "NO-GO / 收缩")
    )
    lines.append(f"### 判定：**{verdict.level} — {verdict.verdict}**"
                 f" （{verdict_marker}）\n")
    lines.append(f"> {verdict.reason}\n")

    lines.append("## 5. 红灯检查（review §37）\n")
    red_lights = []
    if verdict.positive_events < 30:
        red_lights.append("正 pilot step 几乎没有 → 删除主动增加主张（review §37 红灯 1）")
    if not verdict.negative_sufficient:
        red_lights.append("负 pilot 事件不足 → 园区回放标定可靠性受限")
    if red_lights:
        for rl in red_lights:
            lines.append(f"- **{rl}**")
    else:
        lines.append("- 无红灯触发。")
    lines.append("")

    lines.append("## 6. 下一步决策（review §36）\n")
    if verdict.level == "A_level":
        lines.append("- D0 通过（A 级）。进入 §36 step 6：补 M2 数值上限 → "
                     "step 7 真实 EV 事件比较（pilot-only / rolling-Q95 / Candidate）。")
    elif verdict.level == "B_level":
        lines.append("- D0 条件通过（B 级）。M2 主动增加只能作条件实施方式/从属；"
                     "仍可进入 EV 验证但 claim 收窄。")
    else:
        lines.append("- D0 不通过（C 级）。**立即收缩 claim**："
                     "独立权利要求不主张基于历史主动增加 EV 功率；")
        lines.append("  只保留明确 capability 时增加 / 信息不足时限制增加 / 降低或保持。不救数据。")
        lines.append("- 仍可评估 M3/M4 “信息不足时禁止无证据增加” 在系统层的"
                     "独立工程效果（review §38 结果 B）。")
    lines.append("")

    lines.append("## 7. 产物文件\n")
    lines.append("- `results/raw/e7_fast/d0/d0_info_mode_coverage.csv`（D0-1 明细）")
    lines.append("- `results/raw/e7_fast/d0/d0_info_mode_summary.csv`（D0-1 汇总）")
    lines.append("- `results/raw/e7_fast/d0/d0_pilot_step_events.parquet`（D0-2 事件库）")
    lines.append("- `results/raw/e7_fast/d0/d0_evidence_registry.csv`（证据台账）\n")

    out_path = Path(cfg.d0.report_path)
    if not out_path.is_absolute():
        out_path = _REPORTS_BASE / out_path.name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
