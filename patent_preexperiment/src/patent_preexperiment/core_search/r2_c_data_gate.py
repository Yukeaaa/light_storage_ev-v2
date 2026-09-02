"""R2-C DATA + IDENTIFIABILITY GATE：数据可行性与服务代价可辨识性检查。

本阶段不建 policy、不训练模型、不报告收益。只回答：
1. 有多少 matched session 能构造 online-safe 特征（含 userInput modifiedAt≤t 的时序 guard）；
2. 离线 outcome（disconnect / doneCharging / final kWhDelivered）覆盖；
3. userInputs 字段级质量（requestedDeparture vs disconnect、kWhRequested vs delivered、中途修改）；
4. 服务代价能否定义不依赖不可观测反事实的可信评价量。

红线：disconnect/doneCharging/kWhDelivered/future actual/pilot 只能作离线标签；
userInput 必须逐条校验 modifiedAt ≤ 决策时刻，禁止把自然事件额外功率下降解释为控制造成的服务损失。
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.r2_config import R2Config, load_r2_config
from patent_preexperiment.io.paths import get_paths

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_ACN_PROJECT = Path(get_paths()["acn_project"])
_ACN_FULL = Path(get_paths()["acn_full"])
_MAPPING = _ACN_PROJECT / "manifests" / "static_api_mapping.csv"
_METADATA_ROOT = _ACN_FULL / "metadata"


def _load_api_metadata() -> pd.DataFrame:
    """加载全部 API 会话元数据（每行一个 session）。"""
    rows: list[dict[str, object]] = []
    for f in sorted(_METADATA_ROOT.glob("**/*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows.append({
                    "sessionID": d.get("sessionID"),
                    "site": d.get("siteID"),
                    "connectionTime": d.get("connectionTime"),
                    "disconnectTime": d.get("disconnectTime"),
                    "doneChargingTime": d.get("doneChargingTime"),
                    "kWhDelivered": d.get("kWhDelivered"),
                    "userInputs": d.get("userInputs"),
                })
    return pd.DataFrame(rows)


def _userinput_stats(api: pd.DataFrame) -> pd.DataFrame:
    """userInputs 字段级覆盖与质量（每 session 取最后一条 userInput）。"""
    rows: list[dict[str, object]] = []
    n_with_ui = 0
    n_modified = 0
    n_multiple = 0
    for _, r in api.iterrows():
        ui = r["userInputs"]
        if not isinstance(ui, list) or not ui:
            continue
        n_with_ui += 1
        if len(ui) > 1:
            n_multiple += 1
        last = ui[-1]
        if not isinstance(last, dict):
            continue
        if last.get("modifiedAt") is not None:
            n_modified += 1
        rows.append({
            "sessionID": r["sessionID"],
            "kWhRequested": last.get("kWhRequested"),
            "minutesAvailable": last.get("minutesAvailable"),
            "requestedDeparture": last.get("requestedDeparture"),
            "modifiedAt": last.get("modifiedAt"),
            "n_userInputs": len(ui),
            "disconnectTime": r["disconnectTime"],
            "doneChargingTime": r["doneChargingTime"],
            "kWhDelivered": r["kWhDelivered"],
        })
    return pd.DataFrame(rows)


def run_r2_c_data_gate(cfg: R2Config | None = None) -> dict[str, object]:
    cfg = cfg or load_r2_config()
    mapping = pd.read_csv(_MAPPING)
    matched = mapping[mapping["match_status"] == "matched"].copy()
    api = _load_api_metadata()
    ui = _userinput_stats(api)

    # 与 matched 对齐（严格会话验证只用 matched）
    matched_ids = set(matched["sessionID"].astype(str))
    ui_matched = ui[ui["sessionID"].astype(str).isin(matched_ids)]
    api_matched = api[api["sessionID"].astype(str).isin(matched_ids)]

    stats: dict[str, object] = {
        "matched_sessions": int(matched.shape[0]),
        "api_sessions_loaded": int(api.shape[0]),
        "matched_with_userinputs": int(ui_matched.shape[0]),
        "userinput_coverage_matched": (
            float(ui_matched.shape[0] / matched.shape[0])
            if matched.shape[0]
            else 0.0
        ),
        "matched_with_offline_outcome": int(api_matched["kWhDelivered"].notna().sum()),
    }

    # 字段级覆盖（在 userInputs 会话内）
    if not ui_matched.empty:
        stats["modifiedAt_coverage"] = float(ui_matched["modifiedAt"].notna().mean())
        stats["kWhRequested_coverage"] = float(ui_matched["kWhRequested"].notna().mean())
        stats["minutesAvailable_coverage"] = float(
            ui_matched["minutesAvailable"].notna().mean()
        )
        stats["requestedDeparture_coverage"] = float(
            ui_matched["requestedDeparture"].notna().mean()
        )
        stats["n_multiple_userinputs"] = int(
            ui_matched[ui_matched["n_userInputs"] > 1].shape[0]
        )
        # requestedDeparture vs actual disconnect 偏差（小时）
        rd = pd.to_datetime(ui_matched["requestedDeparture"], errors="coerce", utc=True)
        dc = pd.to_datetime(ui_matched["disconnectTime"], errors="coerce", utc=True)
        both = rd.notna() & dc.notna()
        dev = (dc - rd).dt.total_seconds() / 3600.0
        stats["requested_departure_n"] = int(both.sum())
        if both.sum() > 0:
            stats["departure_deviation_hours_median"] = float(dev[both].abs().median())
            stats["departure_deviation_hours_p90"] = float(dev[both].abs().quantile(0.9))
        # kWhRequested vs final kWhDelivered
        kr = pd.to_numeric(ui_matched["kWhRequested"], errors="coerce")
        kd = pd.to_numeric(ui_matched["kWhDelivered"], errors="coerce")
        both_k = kr.notna() & kd.notna()
        stats["kwh_requested_delivered_n"] = int(both_k.sum())
        if both_k.sum() > 0:
            ratio = (kd[both_k] / kr[both_k].replace(0, np.nan)).dropna()
            stats["delivered_to_requested_median"] = (
                float(ratio.median()) if not ratio.empty else np.nan
            )
    else:
        stats["modifiedAt_coverage"] = np.nan

    # 写产物
    out_root = _PATENT_ROOT / cfg.r2_c_results_root
    out_root.mkdir(parents=True, exist_ok=True)
    ui_matched.to_csv(out_root / "userinput_matched.csv", index=False)
    pd.Series(stats).to_csv(out_root / "r2_c_data_gate_stats.csv", header=["value"])

    _write_report(cfg, stats)
    return stats


def _write_report(cfg: R2Config, stats: dict[str, object]) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    L: list[str] = []
    L.append("# CORE_SEARCH_R2_C_DATA_GATE：数据可行性与服务代价可辨识性\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append(f"> 配置：configs/core_search_r2.yaml（rule_version={cfg.rule_version}，冻结）\n")

    L.append("## 1. 目的\n")
    L.append("> 只回答：现有观察数据能否构造 online-safe 特征 + 离线 outcome，")
    L.append("> 以及能否定义不依赖不可观测反事实的可信服务代价评价量。不建 policy、不报收益。\n")

    L.append("## 2. 数据覆盖\n")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    for k in [
        "matched_sessions", "api_sessions_loaded", "matched_with_userinputs",
        "userinput_coverage_matched", "matched_with_offline_outcome",
    ]:
        L.append(f"| {k} | {stats.get(k)} |")
    L.append("")

    L.append("## 3. userInputs 字段级覆盖（matched 内）\n")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    for k in [
        "modifiedAt_coverage", "kWhRequested_coverage", "minutesAvailable_coverage",
        "requestedDeparture_coverage", "n_multiple_userinputs",
    ]:
        v = stats.get(k)
        if isinstance(v, float) and not np.isnan(v):
            L.append(f"| {k} | {v:.3f} |")
        else:
            L.append(f"| {k} | {v} |")
    L.append("")

    L.append("## 4. 服务代价可辨识性（离线标签，绝不入 policy）\n")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append(
        f"| requestedDeparture 与实际 disconnect 偏差样本数 "
        f"| {stats.get('requested_departure_n')} |"
    )
    L.append(f"| 偏差绝对值中位（小时） | {stats.get('departure_deviation_hours_median')} |")
    L.append(f"| 偏差绝对值 p90（小时） | {stats.get('departure_deviation_hours_p90')} |")
    L.append(
        f"| kWhRequested 与 kWhDelivered 样本数 | {stats.get('kwh_requested_delivered_n')} |"
    )
    L.append(f"| delivered/requested 中位 | {stats.get('delivered_to_requested_median')} |\n")

    L.append("## 5. online/offline 分离（红线）\n")
    L.append(
        "- online-safe：connection age / current actual / current pilot / "
        "actual+ pilot history / 累计 delivered energy 到 t / "
        "userInput 仅当 modifiedAt ≤ t（逐样本 guard）。"
    )
    L.append(
        "- offline-only：disconnectTime / doneChargingTime / final kWhDelivered / "
        "future actual / future pilot。"
    )
    L.append("- 禁止：把自然事件中的额外功率下降直接解释为控制造成的服务损失。\n")

    L.append("## 6. 结论（DATA_GATE）\n")
    matched_with_ui = stats.get("matched_with_userinputs", 0)
    mod_cov = stats.get("modifiedAt_coverage", np.nan)
    if isinstance(matched_with_ui, int) and matched_with_ui >= 5000 and (
        isinstance(mod_cov, float) and not np.isnan(mod_cov) and mod_cov >= 0.5
    ):
        L.append(
            "- **DATA_GATE_GO**：matched 样本与 userInput/modifiedAt 覆盖"
            "足以进入 R2-C 正式实验设计。\n"
        )
    else:
        L.append("- **DATA_GATE_NO-GO**：样本或字段覆盖不足，需补数据或换评价量。\n")

    report_path = _PATENT_ROOT / cfg.r2_c_report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
