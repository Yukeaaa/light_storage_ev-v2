"""D2+D3 test single-exposure runner（用户口径 §16；D3 GO 后才允许跑）。

一次性暴露 test 6,687 正向事件：D2 EV gate（Over/Coverage）+ D3 system gate
（shortfall/unplanned_bess）。判定标准冻结于 configs/e7_fast.yaml test_policy。
test FAIL → M2 收窄到从属，不调参救场；test GO → 直接转专利交底书。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from patent_preexperiment.e7_fast.config import E7FastConfig, load_e7_fast_config
from patent_preexperiment.e7_fast.ev_validation import (
    ControllerMetrics,
    D2Verdict,
    evaluate_ev_gate,
    filter_m2_evaluation_set,
)
from patent_preexperiment.e7_fast.event_replay import replay_all_arms
from patent_preexperiment.e7_fast.system_metrics import D3Verdict, evaluate_system_gate

_D0_EVENTS = (
    Path(__file__).resolve().parents[3]
    / "results" / "raw" / "e7_fast" / "d0" / "d0_pilot_step_events.parquet"
)
_D2_RESULTS = (
    Path(__file__).resolve().parents[3]
    / "results" / "raw" / "e7_fast" / "ev_validation"
)
_D3_RESULTS = (
    Path(__file__).resolve().parents[3]
    / "results" / "raw" / "e7_fast" / "park_replay"
)
_E7_FAST_BASE = (
    Path(__file__).resolve().parents[3]
    / "results" / "raw" / "e7_fast"
)
_REPORTS_BASE = Path(__file__).resolve().parents[3] / "reports"


def run_test_exposure(cfg: E7FastConfig | None = None) -> dict[str, D2Verdict | D3Verdict]:
    """一次性暴露 D2+D3 test，返回两个判定。"""
    cfg = cfg or load_e7_fast_config()
    if not _D0_EVENTS.exists():
        raise FileNotFoundError(f"未找到 D0 事件库 {_D0_EVENTS}")
    events = pd.read_parquet(_D0_EVENTS)
    test_splits = ("test",)

    # D2 test: EV gate (Over/Coverage vs B2)
    per_ctrl, d2_verdict = evaluate_ev_gate(events, cfg, splits=test_splits)
    # D3 test: system gate (S3 vs S2 shortfall/unplanned_bess)
    test_events = filter_m2_evaluation_set(events, cfg, splits=test_splits)
    if test_events.empty:
        from patent_preexperiment.e7_fast.system_metrics import D3Verdict
        d3_verdict = D3Verdict(
            level="FAIL", verdict="NO_TEST_EVENTS",
            comparison_baseline="S2_rolling_q95",
            unexpected_shortfall_reduction_pct=0.0,
            unplanned_bess_reduction_pct=0.0,
            pcc_residual_not_worsened=False,
            s3_flex_significantly_higher_than_s1=False,
            reason="test M2 评价集为空；无法验证时间外推。",
        )
    else:
        replay = replay_all_arms(test_events)
        _per_arm, d3_verdict = evaluate_system_gate(replay, cfg)

    _write_test_summaries(d2_verdict, d3_verdict, per_ctrl)
    _write_test_report(cfg, d2_verdict, d3_verdict, per_ctrl)
    return {"d2_test": d2_verdict, "d3_test": d3_verdict}


def _write_test_summaries(
    d2_v: D2Verdict, d3_v: D3Verdict, per_ctrl: dict[str, ControllerMetrics]
) -> None:
    # D2 test summary
    rows = []
    if per_ctrl:
        for name, cm in per_ctrl.items():
            rows.append({
                "controller": name, "n_events": cm.n_events,
                "over_sum_kw": round(cm.over_sum, 4),
                "over_mean_kw": round(cm.over_mean, 4),
                "under_sum_kw": round(cm.under_sum, 4),
                "hit_rate": round(cm.hit_rate, 4),
                "coverage": round(cm.coverage, 4),
            })
    pd.DataFrame(rows).to_csv(_D2_RESULTS / "d2_test_summary.csv", index=False)

    # D3 test summary
    d3_rows = []
    for arm, am in d3_v.per_arm.items():
        d3_rows.append({
            "arm": arm, "n_events": am.n_events,
            "unexpected_ev_shortfall_sum": round(am.unexpected_ev_shortfall_sum, 2),
            "unplanned_bess_correction_sum": round(am.unplanned_bess_correction_sum, 2),
            "pcc_residual_sum": round(am.pcc_residual_sum, 2),
            "accepted_real_ev_flex_sum": round(am.accepted_real_ev_flex_sum, 2),
        })
    pd.DataFrame(d3_rows).to_csv(_D3_RESULTS / "d3_test_summary.csv", index=False)

    # Combined test verdict
    pd.DataFrame([{
        "d2_test_level": d2_v.level, "d2_test_verdict": d2_v.verdict,
        "d2_over_improvement_pct": round(d2_v.over_improvement_pct, 2),
        "d2_coverage_ratio_pct": round(d2_v.coverage_ratio_pct, 2),
        "d3_test_level": d3_v.level, "d3_test_verdict": d3_v.verdict,
        "d3_shortfall_reduction_pct": round(d3_v.unexpected_shortfall_reduction_pct, 2),
        "d3_unplanned_bess_reduction_pct": round(d3_v.unplanned_bess_reduction_pct, 2),
        "overall": ("TEST_PASS" if d2_v.level == "GO" and d3_v.level == "GO"
                    else "TEST_FAIL_OR_CONDITIONAL"),
    }]).to_csv(_E7_FAST_BASE / "test_exposure_verdict.csv", index=False)


def _write_test_report(
    cfg: E7FastConfig,
    d2_v: D2Verdict,
    d3_v: D3Verdict,
    per_ctrl: dict[str, ControllerMetrics],
) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    L: list[str] = []
    L.append("# E7-FAST D2+D3 Test Single-Exposure 报告\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append(f"> 配置：`{cfg.config_path}`（rule_version={cfg.rule_version}，冻结）")
    L.append("> 依据：用户 D2 冻结口径 §16；test single-exposure，禁止重复\n")

    L.append("## 1. 治理纪律\n")
    L.append("- test 判定标准在跑 test 前冻结（test_policy），与 train+val 同标准。")
    L.append("- single-exposure：只能跑一次，禁止重复；禁止 test FAIL 后调 "
             "Q95/换模型/加 ML/恢复 D3。")
    L.append("- D3 train+val 已 GO（commit b87edc9），才允许暴露 test。\n")

    L.append("## 2. D2 test: EV gate（M2 vs B2 rolling-Q95）\n")
    if per_ctrl:
        L.append("| 方法 | n | Over(Σ) | Over(mean) | Under(Σ) | Hit | Coverage |")
        L.append("|---|---|---:|---:|---:|---:|---:|")
        for name, cm in per_ctrl.items():
            L.append(f"| {name} | {cm.n_events} | {cm.over_sum:.2f} | "
                     f"{cm.over_mean:.4f} | {cm.under_sum:.2f} | "
                     f"{cm.hit_rate:.4f} | {cm.coverage:.4f} |")
        L.append("")
    L.append("| 指标 | 值 | 阈值 |")
    L.append("|---|---|---|")
    L.append(f"| C vs B2 Over improvement | {d2_v.over_improvement_pct:.2f}% | GO>=10% |")
    L.append(f"| C vs B2 CoverageRatio | {d2_v.coverage_ratio_pct:.2f}% | GO>=50% |")
    L.append(f"| 判定 | **{d2_v.level} — {d2_v.verdict}** | — |\n")
    L.append(f"> {d2_v.reason}\n")

    L.append("## 3. D3 test: system gate（S3 vs S2 rolling-Q95）\n")
    if d3_v.per_arm:
        L.append("| arm | ①shortfall | ②unplanned_bess | ③pcc | ④flex |")
        L.append("|---|---:|---:|---:|---:|")
        for arm, am in d3_v.per_arm.items():
            L.append(f"| {arm} | {am.unexpected_ev_shortfall_sum:.2f} | "
                     f"{am.unplanned_bess_correction_sum:.2f} | "
                     f"{am.pcc_residual_sum:.2f} | {am.accepted_real_ev_flex_sum:.2f} |")
        L.append("")
    L.append("| 指标 | 值 | 阈值 |")
    L.append("|---|---|---|")
    L.append(f"| S3 vs S2 shortfall 降 | "
             f"{d3_v.unexpected_shortfall_reduction_pct:.2f}% | GO>=10% |")
    L.append(f"| S3 vs S2 unplanned_bess 降 | "
             f"{d3_v.unplanned_bess_reduction_pct:.2f}% | GO>=10% |")
    L.append(f"| 判定 | **{d3_v.level} — {d3_v.verdict}** | — |\n")
    L.append(f"> {d3_v.reason}\n")

    overall = ("TEST_PASS" if d2_v.level == "GO" and d3_v.level == "GO"
               else "TEST_FAIL_OR_CONDITIONAL")
    L.append("## 4. 总判定\n")
    L.append(f"### **{overall}**\n")
    if overall == "TEST_PASS":
        L.append("- D2+D3 test 均通过。M2 时间外推验证通过。")
        L.append("- **直接转专利交底书**（claim_tree_v3_e7_fast.md + prior-art element map）。")
        L.append("- 不需做 24h 动态回放（除非明确要求）。")
    elif "CONDITIONAL" in (d2_v.level, d3_v.level):
        L.append("- test 条件通过。M2 收窄到从属；主 claim 围绕 M3/M4 + 系统层 shortfall。")
        L.append("- 仍可转交底书，但 M2 主动增加只作条件实施方式。")
    else:
        L.append("- test FAIL。M2 收窄到从属；主 claim 围绕 M3/M4 信息不足保护 "
                 "+ 系统层 shortfall 减少。")
        L.append("- 不调参救场。仍可转交底书，但 claim 范围更窄。")
    L.append("")

    L.append("## 5. 产物文件\n")
    L.append("- `results/raw/e7_fast/ev_validation/d2_test_summary.csv`")
    L.append("- `results/raw/e7_fast/park_replay/d3_test_summary.csv`")
    L.append("- `results/raw/e7_fast/test_exposure_verdict.csv`\n")

    out = _REPORTS_BASE / "E7_FAST_test_exposure.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
