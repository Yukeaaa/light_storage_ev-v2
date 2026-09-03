"""CORE-SEARCH Decision #06 for Round 4 data gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_R4C_STATS = _PATENT_ROOT / "results/raw/core_search/r4_c0/r4_c0_gate_stats.csv"
_R4A_REGISTRY = _PATENT_ROOT / "data_registry/iontech_aachen_registry.json"
_REPORT = _PATENT_ROOT / "reports/core_search/CORE_SEARCH_DECISION_06_R4_DATA_GATE.md"


def choose_r4_route(r4c: dict[str, Any], r4a: dict[str, Any]) -> dict[str, str]:
    """Frozen priority order: R4-C GO, else R4-A Level A, else STOP/hold."""
    r4c_verdict = str(r4c.get("verdict", "STOP"))
    r4a_level = str(r4a.get("data_level", "DATA_PENDING"))
    if r4c_verdict == "GO":
        return {"decision": "R4-C_MAIN", "reason": "R4-C0 GO has priority over R4-A"}
    if r4a_level == "A":
        return {"decision": "R4-A_MAIN", "reason": "R4-C not GO and R4-A data level A"}
    if r4a_level == "B":
        return {
            "decision": "R4-A_TRACKING_HOLD",
            "reason": "R4-A level B supports tracking-capability only, not automatic system bench",
        }
    return {
        "decision": "ROUND4_STOP_OR_DATA_PENDING",
        "reason": "R4-C not GO and R4-A lacks Level A/B data",
    }


def run_decision_06() -> dict[str, Any]:
    r4c = _read_stats(_R4C_STATS)
    r4a = json.loads(_R4A_REGISTRY.read_text(encoding="utf-8"))
    decision = choose_r4_route(r4c, r4a)
    result = {"r4c": r4c, "r4a": r4a, "decision": decision}
    _write_report(result)
    return result


def _read_stats(path: Path) -> dict[str, Any]:
    df = pd.read_csv(path, index_col=0)
    raw = df.iloc[:, 0].to_dict()
    return {str(k): _coerce(v) for k, v in raw.items()}


def _coerce(value: object) -> object:
    if not isinstance(value, str):
        return value
    if value in {"True", "False"}:
        return value == "True"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _write_report(result: dict[str, Any]) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    r4c = result["r4c"]
    r4a = result["r4a"]
    decision = result["decision"]
    lines: list[str] = []
    lines.append("# CORE_SEARCH_DECISION_06_R4_DATA_GATE — Round 4 路线选择\n")
    lines.append(f"> 生成时间（UTC）：{ts}")
    lines.append("> 依据：CORE_SEARCH_R4_C0_GATE.md + CORE_SEARCH_R4_A0_DATA_AUDIT.md")
    lines.append("> 决策纪律：两条线完成数据门后只保留 1 条主线；不靠 ML、子集或极端事件救活。\n")
    lines.append("## 1. 冻结决策规则\n")
    lines.append("1. R4-C 若存在多站、重复、系统相关量级的真实可用容量损失 → R4-C 主线。")
    lines.append("2. 若 R4-C 量纲弱，但 R4-A = LEVEL A → R4-A 主线。")
    lines.append("3. 若 R4-A = LEVEL B → 只允许 tracking shortfall 量级判断，不自动进入系统开发。")
    lines.append("4. 两边均弱 → Round 4 STOP，不靠 ML / 子集 / 极端事件救活。\n")
    lines.append("## 2. R4-C0 摘要\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---:|")
    for key in [
        "verdict", "event_count", "station_count", "top2_event_share",
        "loss_fraction_l1_p50", "loss_fraction_l1_event_share_ge_15pct",
        "active_fault_event_share", "multi_station_disabled_minutes",
    ]:
        lines.append(f"| {key} | {r4c.get(key)} |")
    lines.append("\n## 3. R4-A0 摘要\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| data_level | **{r4a.get('data_level')}** |")
    lines.append(f"| local_files_found | {r4a.get('local_files_found')} |")
    lines.append(f"| time_semantics_status | {r4a.get('time_semantics_status')} |\n")
    lines.append("## 4. 判定\n")
    lines.append(f"### **{decision['decision']}**\n")
    lines.append(f"> {decision['reason']}\n")
    if decision["decision"] == "R4-C_MAIN":
        lines.append(
            "下一步只做 R4-C1 system propagation gate：fixed nominal capacity accounting "
            "vs availability-aware accounting。"
        )
    elif decision["decision"] == "R4-A_MAIN":
        lines.append(
            "下一步只做 R4-A1 physical capability existence gate；"
            "仍不做 EMS/system bench。"
        )
    else:
        lines.append("不进入系统层；先补数据或关闭 Round 4。")
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text("\n".join(lines), encoding="utf-8")
