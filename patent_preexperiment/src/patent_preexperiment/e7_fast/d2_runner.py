"""D2 真实 EV 数据验证 runner（review §14-18 / §36 step 6-7 + 用户冻结口径）。

加载 D0 冻结事件库 → 过滤 M2 评价集 → 四控制器纯函数 → 指标(事件总体+session 等权)
→ 按 review §17 Go 门判定 → 负向响应标定 → 报告。先不放 PV/BESS。
train+validation 开发；test 物理过滤，主判定 commit 后单独生成 d2_test_summary.csv。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from patent_preexperiment.e7_fast.config import E7FastConfig, load_e7_fast_config
from patent_preexperiment.e7_fast.ev_validation import (
    CONTROLLERS,
    ControllerMetrics,
    D2Verdict,
    compute_event_scores,
    evaluate_ev_gate,
    negative_event_calibration,
    station_month_diagnostic,
)

_D0_EVENTS = (
    Path(__file__).resolve().parents[3]
    / "results" / "raw" / "e7_fast" / "d0" / "d0_pilot_step_events.parquet"
)
_RESULTS_BASE = (
    Path(__file__).resolve().parents[3]
    / "results" / "raw" / "e7_fast" / "ev_validation"
)
_REPORTS_BASE = Path(__file__).resolve().parents[3] / "reports"


def run_d2(cfg: E7FastConfig | None = None) -> D2Verdict:
    """执行 D2 EV 验证门，写出产物并返回判定。"""
    cfg = cfg or load_e7_fast_config()
    if not _D0_EVENTS.exists():
        raise FileNotFoundError(
            f"未找到 D0 事件库 {_D0_EVENTS}；请先运行 D0（runner.run_d0）。"
        )
    events = pd.read_parquet(_D0_EVENTS)
    per_ctrl, verdict = evaluate_ev_gate(events, cfg)
    neg_calib = negative_event_calibration(events, cfg)

    _RESULTS_BASE.mkdir(parents=True, exist_ok=True)
    _write_event_scores(events, cfg)
    _write_summaries(per_ctrl, verdict)
    _write_station_month(events, cfg)
    _write_controller_table(per_ctrl, neg_calib, verdict)
    _write_report(cfg, per_ctrl, neg_calib, verdict)
    return verdict


def _write_event_scores(events: pd.DataFrame, cfg: E7FastConfig) -> None:
    scores = compute_event_scores(events, cfg)
    if not scores.empty:
        scores.to_parquet(_RESULTS_BASE / "d2_trainval_event_scores.parquet", index=False)


def _write_summaries(
    per_ctrl: dict[str, ControllerMetrics], verdict: D2Verdict
) -> None:
    if not per_ctrl:
        return
    rows = []
    for name, m in per_ctrl.items():
        rows.append({
            "controller": name,
            "n_events": m.n_events,
            "over_sum_kw": round(m.over_sum, 4),
            "over_mean_kw": round(m.over_mean, 4),
            "over_median_kw": round(m.over_median, 4),
            "under_sum_kw": round(m.under_sum, 4),
            "under_mean_kw": round(m.under_mean, 4),
            "under_median_kw": round(m.under_median, 4),
            "hit_rate": round(m.hit_rate, 4),
            "coverage": round(m.coverage, 4),
            "mean_allowed_up_kw": round(m.mean_allowed_up, 4),
            "n_p_support_positive": m.n_p_support_positive,
        })
    pd.DataFrame(rows).to_csv(_RESULTS_BASE / "d2_trainval_summary.csv", index=False)

    # session 等权汇总
    sess_rows = []
    for name in CONTROLLERS:
        so = verdict.session_equal_over.get(name, 0.0)
        sess_rows.append({"controller": name, "session_equal_over_mean_kw": round(so, 4)})
    pd.DataFrame(sess_rows).to_csv(_RESULTS_BASE / "d2_session_equal_summary.csv", index=False)

    pd.DataFrame([{
        "level": verdict.level,
        "verdict": verdict.verdict,
        "strongest_baseline": verdict.strongest_baseline,
        "over_improvement_pct": round(verdict.over_improvement_pct, 2),
        "coverage_ratio_pct": round(verdict.coverage_ratio_pct, 2),
        "session_equal_over_improvement_pct": round(
            verdict.session_equal_over_improvement_pct, 2
        ),
        "session_equal_direction_consistent": verdict.session_equal_direction_consistent,
        "n_events": verdict.extras.get("n_events", 0),
        "n_sessions": verdict.extras.get("n_sessions", 0),
        "n_stations": verdict.extras.get("n_stations", 0),
        "n_months": verdict.extras.get("n_months", 0),
        "n_p_support_positive": verdict.extras.get("n_p_support_positive", 0),
    }]).to_csv(_RESULTS_BASE / "d2_gate_verdict.csv", index=False)


def _write_station_month(events: pd.DataFrame, cfg: E7FastConfig) -> None:
    diag = station_month_diagnostic(events, cfg)
    if not diag.empty:
        diag.to_csv(_RESULTS_BASE / "d2_station_month_diagnostic.csv", index=False)


def _write_controller_table(
    per_ctrl: dict[str, ControllerMetrics],
    neg_calib: dict[str, Any],
    verdict: D2Verdict,
) -> None:
    if not per_ctrl:
        return
    pd.DataFrame([neg_calib]).to_csv(
        _RESULTS_BASE / "d2_negative_calibration.csv", index=False
    )


def _write_report(
    cfg: E7FastConfig,
    per_ctrl: dict[str, ControllerMetrics],
    neg_calib: dict[str, Any],
    verdict: D2Verdict,
) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    gate_cfg = cfg.raw["d2_ev_validation"]["gate"]
    L: list[str] = []
    L.append("# E7-FAST D2 真实 EV 数据验证门报告\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append(f"> 配置：`{cfg.config_path}`（rule_version={cfg.rule_version}，冻结）")
    L.append("> 依据：review §14-18 / §36 step 6-7 + 用户 D2 冻结口径\n")

    L.append("## 1. 实验设计（冻结）\n")
    L.append("- **问题**：`min(pilot, historical-Q95)` 双重限制是否在真实自然 pilot 上调事件上，"
             "比 rolling-Q95 单独使用产生足够大的“少高估、不过度牺牲真实机会”的增量价值？")
    L.append("- **时序锁定**：actual_before=t-1；pilot_after=t 新允许值"
             "（拟执行调整值，非响应证据）；q95_before 严格由 t 之前 actual 构造；"
             "actual_1/3/5min 只作结果，绝不进 Candidate。")
    L.append("- **P_support** = max(actual_5min - actual_before, 0)："
             "真实观察到的实际增加量；**非车辆理论最大能力**。")
    L.append("- **禁止外推**（review §22）：candidate 允许量 <= P_support 视为未超出；"
             "超出 = Over。")
    L.append("- **C = min(B1, B2)**：天然不比 B2 激进；"
             "Over 下降可能因更保守，必须与 Under 同看。")
    L.append("- **评价集**：正向 + info_mode==M2 + q95/actual 有效 + "
             "train+validation（排除 office001/stress）。")
    L.append("- **四控制器**：B0=0 / B1=max(pilot-actual,0) / "
             "B2=max(Q95-actual,0) / C=max(min(pilot,Q95)-actual,0)。\n")

    L.append("## 2. M2 评价集过滤后规模\n")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append(f"| 评价事件数 | {verdict.extras.get('n_events', 0)} |")
    L.append(f"| unique sessions | {verdict.extras.get('n_sessions', 0)} |")
    L.append(f"| stations | {verdict.extras.get('n_stations', 0)} |")
    L.append(f"| months | {verdict.extras.get('n_months', 0)} |")
    L.append(f"| 真实有上调支持(P_support>0)事件数 | "
             f"{verdict.extras.get('n_p_support_positive', 0)} |")
    L.append("\n> D0 正向总数 11702；过滤后见上。若远高于 A 级规模则继续。\n")

    L.append("## 3. 第一屏：四控制器指标（事件总体）\n")
    if not per_ctrl:
        L.append("（无 M2 评价事件，无法计算）\n")
    else:
        L.append("| 方法 | Over(Σ) | Over(mean) | Under(Σ) | Under(mean) | "
                 "Hit rate | Coverage | mean allowed_up |")
        L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for name, m in per_ctrl.items():
            L.append(
                f"| {name} | {m.over_sum:.2f} | {m.over_mean:.4f} | "
                f"{m.under_sum:.2f} | {m.under_mean:.4f} | {m.hit_rate:.4f} | "
                f"{m.coverage:.4f} | {m.mean_allowed_up:.4f} |"
            )
        L.append("")
        L.append("> **Over** 越小越好；**Under** 越小越不保守（必须同看）；")
        L.append("> **Coverage** = Σmin(allowed,support)/Σsupport（功率加权，"
                 "禁止靠每事件放一点虚称高覆盖）。\n")

    L.append("## 4. session 等权汇总（防高频会话支配）\n")
    if per_ctrl:
        L.append("| 方法 | session 等权 Over(mean) |")
        L.append("|---|---:|")
        for name in CONTROLLERS:
            so = verdict.session_equal_over.get(name, 0.0)
            L.append(f"| {name} | {so:.4f} |")
        L.append("")
        L.append(f"> session 等权 Over improvement = "
                 f"{verdict.session_equal_over_improvement_pct:.2f}%；方向"
                 f"{'一致' if verdict.session_equal_direction_consistent else '不一致'}。\n")

    L.append("## 5. 负向 pilot 事件响应标定（review §18；园区回放用）\n")
    if neg_calib.get("n_events", 0) == 0:
        L.append("（无负向事件）\n")
    else:
        L.append("| 指标 | 值 |")
        L.append("|---|---|")
        L.append(f"| 负向事件数 | {neg_calib['n_events']} |")
        L.append(f"| response_gain_5m median | {neg_calib['response_gain_5m_median']:.4f} |")
        L.append(f"| response_gain_5m p25 | {neg_calib['response_gain_5m_p25']:.4f} |")
        L.append(f"| response_gain_5m p75 | {neg_calib['response_gain_5m_p75']:.4f} |")
        L.append(f"| delta_actual_5min median (kW) | "
                 f"{neg_calib['delta_actual_5min_median_kw']:.4f} |")
        L.append(f"| 不响应比例（actual 未下降） | {neg_calib['no_response_ratio']:.4f} |")
    L.append("")

    L.append("## 6. Go 门判定（review §17 + 用户冻结公式）\n")
    go_over = gate_cfg["GO"]["over_improvement_vs_strongest_baseline_pct_min"]
    go_cov = gate_cfg["GO"]["coverage_ratio_pct_min"]
    cond_lo, cond_hi = gate_cfg["CONDITIONAL"]["over_improvement_pct_range"]
    fail_max = gate_cfg["FAIL"]["over_improvement_pct_max"]
    L.append("| 指标 | 值 | 阈值 |")
    L.append("|---|---|---|")
    L.append(f"| 最强 baseline（固定） | {verdict.strongest_baseline} | review §15 |")
    L.append(f"| C vs B2 Over improvement (1-ΣOver_C/ΣOver_B2) | "
             f"{verdict.over_improvement_pct:.2f}% | "
             f"GO>={go_over}% / COND {cond_lo}-{cond_hi}% / FAIL<{fail_max}% |")
    L.append(f"| C vs B2 CoverageRatio (Coverage_C/Coverage_B2) | "
             f"{verdict.coverage_ratio_pct:.2f}% | GO>={go_cov}% |")
    L.append(f"| session 等权 Over improvement | "
             f"{verdict.session_equal_over_improvement_pct:.2f}% | 方向一致 |")
    L.append(f"| 方向一致 | {verdict.session_equal_direction_consistent} | True |\n")

    marker = {"GO": "GO", "CONDITIONAL": "CONDITIONAL",
              "FAIL": "NO-GO / M2 降级"}.get(verdict.level, verdict.level)
    L.append(f"### 判定：**{verdict.level} — {verdict.verdict}** （{marker}）\n")
    L.append(f"> {verdict.reason}\n")
    L.append("> **Under 警示**：若 Over 改善但 Under 损失大，只能描述为"
             "“更保守抑制未经历史支持的功率增加”，不得称“更准确识别车辆能力”。\n")

    L.append("## 7. 红灯检查（review §37）\n")
    red = []
    if verdict.level == "FAIL":
        red.append("M2 只比 rolling Q95 好 <5% 或同效 → M2 降级（红灯 2）")
    if per_ctrl and per_ctrl["C_candidate_m2"].mean_allowed_up <= 1e-9:
        red.append("Candidate 只靠全部禁止上调获胜 → 不构成有效方案（红灯 3）")
    if per_ctrl and not verdict.session_equal_direction_consistent:
        red.append("总体与 session 等权方向不一致 → 降为 Conditional（用户口径 §7）")
    if red:
        for r in red:
            L.append(f"- **{r}**")
    else:
        L.append("- 无红灯触发。")
    L.append("")

    L.append("## 8. 下一步决策（review §36）\n")
    if verdict.level == "GO":
        L.append("- D2 通过（GO）。进入 §36 step 9：真实事件→园区光储充"
                 "短周期嵌入，比较四个 system arm。")
    elif verdict.level == "CONDITIONAL":
        L.append("- D2 条件通过（CONDITIONAL）。M2 主动增加只作从属/窄场景；claim 收窄。")
        L.append("- 仍可进园区回放，但主 claim 围绕 M3/M4 信息不足保护 "
                 "+ M2 作条件实施方式。")
    else:
        L.append("- D2 不通过（FAIL）。**M2 不进核心**，收缩到 M3/M4 信息不足保护。")
        L.append("- 仍可评估 M3/M4 在系统层的独立工程效果（review §38 结果 B）。")
        L.append("- 不调 Q95、不换模型、不继续 ML、不恢复 D3。")
    L.append("")

    L.append("## 9. 产物文件\n")
    L.append("- `results/raw/e7_fast/ev_validation/d2_trainval_event_scores.parquet`"
             "（每事件四控制器得分）")
    L.append("- `results/raw/e7_fast/ev_validation/d2_trainval_summary.csv`"
             "（事件总体汇总）")
    L.append("- `results/raw/e7_fast/ev_validation/d2_session_equal_summary.csv`"
             "（session 等权）")
    L.append("- `results/raw/e7_fast/ev_validation/d2_station_month_diagnostic.csv`"
             "（station×month 诊断）")
    L.append("- `results/raw/e7_fast/ev_validation/d2_negative_calibration.csv`"
             "（负向标定）")
    L.append("- `results/raw/e7_fast/ev_validation/d2_gate_verdict.csv`（门判定）")
    L.append("- `d2_test_summary.csv`：主判定 commit 后单独生成（test 单次暴露）\n")

    out = _REPORTS_BASE / "E7_FAST_EV_gate.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
