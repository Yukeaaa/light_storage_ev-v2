"""D3 园区光储充短周期嵌入 runner（review §19-31 / §36 step 9 + 用户 D3 冻结口径）。

D3-U 主实验：复用 D2 M2 正向真实事件（train+val），每事件构造 PV 富余园区场景，
比较 S0/S1/S2/S3 四 arm 的 EV 执行缺口/事后 BESS 临时补偿/PCC 残差。
test 物理过滤（用户口径 §16）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from patent_preexperiment.e7_fast.config import E7FastConfig, load_e7_fast_config
from patent_preexperiment.e7_fast.ev_validation import filter_m2_evaluation_set
from patent_preexperiment.e7_fast.event_replay import replay_all_arms
from patent_preexperiment.e7_fast.system_metrics import (
    ArmSystemMetrics,
    D3Verdict,
    evaluate_system_gate,
)

_D0_EVENTS = (
    Path(__file__).resolve().parents[3]
    / "results" / "raw" / "e7_fast" / "d0" / "d0_pilot_step_events.parquet"
)
_RESULTS_BASE = (
    Path(__file__).resolve().parents[3]
    / "results" / "raw" / "e7_fast" / "park_replay"
)
_REPORTS_BASE = Path(__file__).resolve().parents[3] / "reports"


def run_d3(cfg: E7FastConfig | None = None) -> D3Verdict:
    """执行 D3-U 系统门，写出产物并返回判定。"""
    cfg = cfg or load_e7_fast_config()
    if not _D0_EVENTS.exists():
        raise FileNotFoundError(
            f"未找到 D0 事件库 {_D0_EVENTS}；请先运行 D0。"
        )
    events = pd.read_parquet(_D0_EVENTS)
    # 复用 D2 M2 评价集过滤（正向 + M2 + q95/actual 有效 + train+val + 排除 external）
    eval_events = filter_m2_evaluation_set(events, cfg)

    replay = replay_all_arms(eval_events)
    per_arm, verdict = evaluate_system_gate(replay, cfg)

    _RESULTS_BASE.mkdir(parents=True, exist_ok=True)
    _write_replay(replay)
    _write_summaries(per_arm, verdict)
    _write_report(cfg, per_arm, verdict)
    return verdict


def _write_replay(replay: pd.DataFrame) -> None:
    if not replay.empty:
        replay.to_parquet(_RESULTS_BASE / "d3_u_trainval_replay.parquet", index=False)


def _write_summaries(
    per_arm: dict[str, ArmSystemMetrics], verdict: D3Verdict
) -> None:
    if not per_arm:
        return
    rows = []
    for arm, m in per_arm.items():
        rows.append({
            "arm": arm,
            "n_events": m.n_events,
            "unexpected_ev_shortfall_sum": round(m.unexpected_ev_shortfall_sum, 2),
            "unplanned_bess_correction_sum": round(m.unplanned_bess_correction_sum, 2),
            "pcc_residual_sum": round(m.pcc_residual_sum, 2),
            "accepted_real_ev_flex_sum": round(m.accepted_real_ev_flex_sum, 2),
            "conservatism_sum": round(m.conservatism_sum, 2),
            "total_bess_activity_sum": round(m.total_bess_activity_sum, 2),
        })
    pd.DataFrame(rows).to_csv(_RESULTS_BASE / "d3_u_system_summary.csv", index=False)
    pd.DataFrame([{
        "level": verdict.level,
        "verdict": verdict.verdict,
        "comparison_baseline": verdict.comparison_baseline,
        "unexpected_shortfall_reduction_pct": round(
            verdict.unexpected_shortfall_reduction_pct, 2
        ),
        "unplanned_bess_reduction_pct": round(verdict.unplanned_bess_reduction_pct, 2),
        "pcc_residual_not_worsened": verdict.pcc_residual_not_worsened,
        "s3_flex_higher_than_s1": verdict.s3_flex_significantly_higher_than_s1,
        "n_events": verdict.extras.get("n_events", 0),
    }]).to_csv(_RESULTS_BASE / "d3_gate_verdict.csv", index=False)


def _write_report(
    cfg: E7FastConfig,
    per_arm: dict[str, ArmSystemMetrics],
    verdict: D3Verdict,
) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    gate_cfg = cfg.raw["d3_park_system"]["system_gate"]
    go_sf = gate_cfg["GO"]["unexpected_ev_shortfall_reduction_pct_min"]
    go_bess = gate_cfg["GO"]["unplanned_bess_correction_reduction_pct_min"]
    cond_lo, cond_hi = gate_cfg["CONDITIONAL"]["reduction_pct_range"]
    fail_max = gate_cfg["NO_GO"]["s3_vs_s2_reduction_pct_max"]
    L: list[str] = []
    L.append("# E7-FAST D3 园区系统验证门报告\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append(f"> 配置：`{cfg.config_path}`（rule_version={cfg.rule_version}，冻结）")
    L.append("> 依据：review §19-31 / §36 step 9 + 用户 D3 冻结口径\n")

    L.append("## 1. 实验设计（冻结）\n")
    L.append("- **D3 真正要证明**：当 `min(pilot,Q95)` 限制接入园区光储充后，能否减少"
             "“EMS 已安排给 EV、但 EV 后续实际未完成”的功率缺口，"
             "从而减少事后 BESS 临时补偿和/或 PCC 功率偏差。")
    L.append("- **关键区分**（用户口径 §5）：planned_bess（事前正常协调）≠ "
             "unplanned_bess_correction（事后控制失败补偿）。BESS_compensation 必须是后者。")
    L.append("- **5 个核心量**：park_requested / ev_accepted / ev_observed_support / "
             "ev_realized / planned_bess / unexpected_shortfall / unplanned_bess / pcc_residual。")
    L.append("- **园区需求** = delta_pilot_kw（独立于 S2/S3）；PV 富余 = delta_pilot_kw；"
             "基础负荷 500kW 固定（验证功率平衡传播，非负荷预测）。")
    L.append("- **BESS 主场景**：P_BESS_max=0.5×actual_before，SOC=50%，10-90%，eta=0.95，2h。")
    L.append("- **四 arm**：S0=乐观 / S1=禁止增加 / S2=rolling-Q95 / S3=M2 双重限制。"
             "不新增第五个。")
    L.append("- **D3-U 主杀伤门**（PV 富余/上调）；test 物理过滤未看。\n")

    L.append("## 2. 第一屏：四 arm 系统指标（D3-U，事件总体求和）\n")
    if not per_arm:
        L.append("（无 M2 评价事件，无法计算）\n")
    else:
        L.append("| arm | ①unexpected_shortfall | ②unplanned_bess | ③pcc_residual | "
                 "④accepted_flex | ⑤conservatism | ⑥total_bess(诊断) |")
        L.append("|---|---:|---:|---:|---:|---:|---:|")
        for arm, m in per_arm.items():
            L.append(
                f"| {arm} | {m.unexpected_ev_shortfall_sum:.2f} | "
                f"{m.unplanned_bess_correction_sum:.2f} | {m.pcc_residual_sum:.2f} | "
                f"{m.accepted_real_ev_flex_sum:.2f} | {m.conservatism_sum:.2f} | "
                f"{m.total_bess_activity_sum:.2f} |"
            )
        L.append("")
        L.append("> ①②③ 为 GO 门核心（越小越好）；④ 防止靠禁止取胜（越大越好）；"
                 "⑤ 实际有能力但没用掉（越小越好）；⑥ 只诊断，不入 GO 门"
                 "（Candidate 更谨慎可能 planned_bess 更高，这是正常 trade-off）。\n")

    L.append("## 3. 系统 Go 门判定（S3 vs S2 rolling-Q95；用户口径 §15）\n")
    L.append("| 指标 | S3 | S2 | 改善 | 阈值 |")
    L.append("|---|---|---|---|---|")
    L.append(
        f"| ① unexpected_shortfall | {verdict.extras.get('s3_shortfall',0):.2f} | "
        f"{verdict.extras.get('s2_shortfall',0):.2f} | "
        f"{verdict.unexpected_shortfall_reduction_pct:.2f}% | "
        f"GO>={go_sf}% / COND {cond_lo}-{cond_hi}% / FAIL<{fail_max}% |"
    )
    L.append(
        f"| ② unplanned_bess_correction | {verdict.extras.get('s3_bess',0):.2f} | "
        f"{verdict.extras.get('s2_bess',0):.2f} | "
        f"{verdict.unplanned_bess_reduction_pct:.2f}% | GO>={go_bess}% |"
    )
    L.append(f"| ③ pcc_residual 未恶化 | — | — | "
             f"{verdict.pcc_residual_not_worsened} | True |")
    L.append(f"| ④ S3 flex > S1×1.1 | — | — | "
             f"{verdict.s3_flex_significantly_higher_than_s1} | True |\n")

    marker = {"GO": "GO", "CONDITIONAL": "CONDITIONAL",
              "FAIL": "NO-GO / 停止 performance 扩展"}.get(verdict.level, verdict.level)
    L.append(f"### 判定：**{verdict.level} — {verdict.verdict}** （{marker}）\n")
    L.append(f"> {verdict.reason}\n")
    L.append("> **诚实记录**：Candidate 更保守 → planned_bess 可能更高，"
             "total_bess_activity 不入门；只比 unplanned_bess_correction（事后临时补偿）。\n")

    L.append("## 4. 红灯检查（review §37）\n")
    red = []
    if verdict.level == "FAIL":
        red.append("S3 与 S2 <5% 或系统优势只靠极端参数 → 停止 performance 扩展（红灯）")
    if (per_arm and per_arm["S3_our_scheme"].accepted_real_ev_flex_sum
            <= per_arm["S1_conservative"].accepted_real_ev_flex_sum):
        red.append("S3 只靠禁止上调取胜 → 不构成有效方案（红灯 3）")
    if red:
        for r in red:
            L.append(f"- **{r}**")
    else:
        L.append("- 无红灯触发。")
    L.append("")

    L.append("## 5. 下一步决策\n")
    if verdict.level == "GO":
        L.append("- D3 通过（GO）。一次性暴露 D2 test 验证时间外推 → "
                 "通过后决定是否做完整 24h 动态回放。")
        L.append("- 专利方向（用户口径 §18）：园区根据光/储/负荷/电网状态产生 EV 调整需求后，"
                 "根据充电桩允许信息与车辆历史实际响应共同限制 EV 上调量，"
                 "减少已安排但未完成的功率调整量，降低由此引起的储能临时补偿和/或 PCC 偏差。")
    elif verdict.level == "CONDITIONAL":
        L.append("- D3 条件通过。M2 只作条件实施方式；claim 收窄到 PV 富余/pilot-rich 场景。")
        L.append("- 仍可暴露 D2 test 验证，但主 claim 围绕 M3/M4 信息不足保护 + M2 条件实施。")
    else:
        L.append("- D3 不通过。**停止 performance 扩展**，不再开第二轮优化。")
        L.append("- 不调 Q95、不加 ML、不恢复 D3。")
        L.append("- 当前 D1+D2 不强行申请；评估 M3/M4 信息不足保护的独立工程效果。")
    L.append("")

    L.append("## 6. 产物文件\n")
    L.append("- `results/raw/e7_fast/park_replay/d3_u_trainval_replay.parquet`"
             "（每事件每 arm 8 核心量）")
    L.append("- `results/raw/e7_fast/park_replay/d3_u_system_summary.csv`（arm 汇总）")
    L.append("- `results/raw/e7_fast/park_replay/d3_gate_verdict.csv`（门判定）\n")

    out = _REPORTS_BASE / "E7_FAST_system_gate.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
