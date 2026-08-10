"""P1 Step 0 — train/validation-only feasibility audit（Phase 3 v1.0.2 §1.5）。

范围纪律（协议 §1.5 / Review 53① / Review 55）：
- **只读 office001 train + validation**；test 的 E1 event label / event count 在正式 test
  前不可读取；本模块在加载后**物理 drop test 会话行**，再进入任何 E1 计算，并有
  fail-closed 断言：若 test 会话行存活到 E1 检测前，直接 RuntimeError。
- 报告项：matched 会话数（仅 population audit，不入门）、measured_pilot 覆盖占比、
  train+validation pretest E1 事件数（同一套冻结 E1 定义 = K1 阈值 + core_run_segment）、
  站点/月份覆盖、population / field_mode 分布。
- 判定（协议 §1.6 Success ① + Review 55）：pilot 覆盖 >=50% 且 pretest E1 >=50 →
  feasible；20–50 → conditional_feasibility；<20 或 pilot 覆盖不足 → backup_path(UCSD)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pyarrow.dataset as ds

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.response.done import PHASE_CORE
from patent_preexperiment.response.e1_stats import process
from patent_preexperiment.response.events import GapThresholds

P1_SITE = "office001"
_FIELD_MODE_MEASURED_PILOT = "measured_pilot"

_MINUTE_COLUMNS = [
    "session_id",
    "station_id",
    "site",
    "garage",
    "field_mode",
    "match_status",
    "timestamp_utc",
    "actual_power_kw",
    "pilot_power_kw",
    "current_a",
    "pilot_a",
    "pilot_available",
    "connected_elapsed_min",
    "gap_flag",
    "disconnect_time",
    "done_charging_time",
]


def _load_train_val_minutes(
    minute_root: Path,
    registry: pd.DataFrame,
) -> pd.DataFrame:
    """加载 office001 matched 1-min 行，join P1 split，物理剔除 test 会话行。"""
    train_val_ids = set(
        registry.loc[registry["split"].isin(["train", "validation"]), "session_id"]
    )
    test_ids = set(registry.loc[registry["split"] == "test", "session_id"])
    if not train_val_ids:
        raise ValueError("P1 Step 0 失败：train+validation 会话集为空")
    if not test_ids:
        raise ValueError("P1 Step 0 失败：test 会话集为空（split 冻结异常）")

    dataset = ds.dataset(str(minute_root))
    table = dataset.to_table(
        filter=(ds.field("site") == P1_SITE)
        & (ds.field("match_status") == "matched"),
        columns=_MINUTE_COLUMNS,
    )
    df = cast(pd.DataFrame, table.to_pandas())
    df = df[df["session_id"].isin(train_val_ids)].reset_index(drop=True)

    overlap = set(df["session_id"]) & test_ids
    if overlap:
        raise RuntimeError(
            "P1 Step 0 fail-closed：test 会话行泄漏进 train/validation 加载面："
            f"n={len(overlap)}；test 的 E1 outcome 禁止在正式 test 前读取"
        )
    if df.empty:
        raise ValueError("P1 Step 0 失败：train+validation 分钟表为空")
    return df


def _pretest_e1_events(
    df: pd.DataFrame,
    thr: GapThresholds,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """同一套冻结 E1 定义：gap 事件检测 + done 阶段切断 + core_run_segment 事件数。"""
    df = df.copy()
    df["minutes_from_end"] = (
        (df["disconnect_time"] - df["timestamp_utc"]).dt.total_seconds() / 60.0
    )
    labeled, events, session_summary = process(df, thr)
    core = events[events["event_phase"] == PHASE_CORE]
    return labeled, core, session_summary


def run_step0(
    impl_root: Path,
    cfg_path: str | Path | None = None,
) -> dict[str, Any]:
    cfg = load_yaml(cfg_path or (impl_root / "configs" / "p1.yaml"))
    k1_cfg = load_yaml(impl_root / "configs" / "k1_preregister.yaml")
    thr = GapThresholds.from_cfg(k1_cfg)

    registry = pd.read_parquet(
        impl_root / "data_registry" / "p1_office001_split_registry.parquet"
    )
    train_val = registry[registry["split"].isin(["train", "validation"])].copy()
    n_matched = int(len(registry))
    n_train_val = int(len(train_val))
    n_stress = int((registry["split"] == "stress").sum())

    pilot_coverage = float(
        (train_val["field_mode"] == _FIELD_MODE_MEASURED_PILOT).mean()
    )
    n_pilot_sessions = int((train_val["field_mode"] == _FIELD_MODE_MEASURED_PILOT).sum())

    minutes = _load_train_val_minutes(impl_root / "datasets" / "session_response_1min", registry)
    labeled, core_events, session_summary = _pretest_e1_events(minutes, thr)

    n_pretest_e1_events = int(len(core_events))
    n_e1_event_sessions = int(core_events["session_id"].nunique())
    n_minute_rows = int(len(labeled))

    n_stations = int(train_val["station"].nunique())
    months = sorted(train_val["connection_time"].dt.strftime("%Y-%m").unique().tolist())
    n_months = len(months)

    field_mode_dist = train_val["field_mode"].value_counts().to_dict()

    line = cfg["step0"]["feasibility"]
    pilot_ok = pilot_coverage >= line["pilot_coverage_min"]
    ev_go = line["pretest_e1_events"]["go"]
    ev_cond = line["pretest_e1_events"]["conditional"]
    if pilot_ok and n_pretest_e1_events >= ev_go:
        verdict = "feasible"
    elif pilot_ok and n_pretest_e1_events >= ev_cond:
        verdict = "conditional_feasibility"
    else:
        verdict = "backup_path"

    summary = {
        "experiment_id": cfg["experiment_id"],
        "protocol_version": cfg["protocol_version"],
        "scope": "P1 Step 0 feasibility audit（train+validation only，test E1 未读取）",
        "site": P1_SITE,
        "population": "office001 matched（L1_strict_matched）",
        "population_audit": {
            "matched_sessions_total": n_matched,
            "stress_sessions_excluded": n_stress,
            "train_validation_sessions": n_train_val,
            "note": "matched 会话数仅作 population audit，不参与 Go/No-Go（v1.0.1②）",
        },
        "field_mode": {
            "distribution": field_mode_dist,
            "measured_pilot_sessions": n_pilot_sessions,
        },
        "coverage": {
            "measured_pilot_coverage": round(pilot_coverage, 4),
            "pilot_coverage_min": line["pilot_coverage_min"],
            "pilot_coverage_pass": pilot_ok,
            "n_stations": n_stations,
            "n_months": n_months,
            "months": months,
            "minute_rows_loaded": n_minute_rows,
        },
        "pretest_e1": {
            "definition": "E1 core_run_segment 事件（K1 冻结阈值 + done 阶段切断，与 A5/E1 同源）",
            "threshold": {
                "P_on_kw": thr.p_on_kw,
                "delta_r": thr.delta_r,
                "delta_p_kw": thr.delta_p_kw,
                "T_event_min": thr.t_event_min,
                "initial_exclusion_min": thr.initial_exclusion_min,
                "tail_exclusion_min": thr.tail_exclusion_min,
            },
            "n_pretest_e1_events": n_pretest_e1_events,
            "n_e1_event_sessions": n_e1_event_sessions,
            "go_line": ev_go,
            "conditional_line": ev_cond,
        },
        "feasibility_verdict": verdict,
        "verdict_text": cfg["step0"]["verdicts"].get(verdict, ""),
        "test_isolation": {
            "test_e1_event_count": None,
            "test_e1_label": None,
            "test_minute_rows_loaded": 0,
            "note": "test 会话行在 E1 计算前物理剔除；test 的 E1 label/count 未读取（v1.0.1①）",
        },
        "protocol": "Patent Definition Phase 3 v1.0.2（minimum_evidence_preregistration.md §1）",
    }
    return summary


def write_step0_report(
    impl_root: Path,
    summary: dict[str, Any],
    report_path: Path | None = None,
) -> Path:
    lines: list[str] = [
        "# P1 Step 0 — office001 数据可行性审计",
        "",
        f"- protocol：{summary['protocol_version']}",
        f"- scope：{summary['scope']}",
        "",
        "## 判定",
        "",
        f"- **feasibility_verdict：`{summary['feasibility_verdict']}`**",
        f"- {summary['verdict_text']}",
        "",
        "## Population audit（不入门）",
        "",
        f"- matched 会话总数：{summary['population_audit']['matched_sessions_total']}",
        f"- stress 会话（异常月，仅敏感性）："
        f"{summary['population_audit']['stress_sessions_excluded']}",
        f"- train+validation 会话：{summary['population_audit']['train_validation_sessions']}",
        f"- 注：{summary['population_audit']['note']}",
        "",
        "## 覆盖率",
        "",
        f"- measured_pilot 会话覆盖：{summary['coverage']['measured_pilot_coverage']:.1%}"
        f"（冻结线 ≥{summary['coverage']['pilot_coverage_min']:.0%}；"
        f"pass={summary['coverage']['pilot_coverage_pass']}）",
        f"- 站点数：{summary['coverage']['n_stations']}；月份数：{summary['coverage']['n_months']}",
        f"- 月份：{', '.join(summary['coverage']['months'])}",
        f"- 加载分钟行数：{summary['coverage']['minute_rows_loaded']:,}",
        "",
        "## 字段模式分布（train+validation 会话级）",
        "",
    ]
    for k, v in summary["field_mode"]["distribution"].items():
        lines.append(f"- {k}：{v}")
    lines += [
        "",
        "## Pretest E1（train+validation，同一套冻结 E1 定义）",
        "",
        f"- 阈值：{summary['pretest_e1']['threshold']}",
        f"- **n_pretest_e1_events：{summary['pretest_e1']['n_pretest_e1_events']}**"
        f"（go ≥{summary['pretest_e1']['go_line']} / conditional"
        f" ≥{summary['pretest_e1']['conditional_line']}）",
        f"- n_e1_event_sessions：{summary['pretest_e1']['n_e1_event_sessions']}",
        "",
        "## Test 隔离声明",
        "",
        f"- test E1 event count：{summary['test_isolation']['test_e1_event_count']}"
        f"（未读取）",
        f"- test minute rows loaded：{summary['test_isolation']['test_minute_rows_loaded']}",
        f"- {summary['test_isolation']['note']}",
        "",
    ]
    out = report_path or (impl_root / "reports" / "P1_Step0_feasibility_audit.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def write_step0_evidence(
    impl_root: Path,
    summary: dict[str, Any],
) -> Path:
    out = impl_root / "data_registry" / "p1_step0_feasibility.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
