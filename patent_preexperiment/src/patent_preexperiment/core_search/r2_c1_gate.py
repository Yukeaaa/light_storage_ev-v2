"""R2-C1：SERVICE-TARGET VALIDITY + OPPORTUNITY GATE（R2-C 正式阶段第一门，不建 Candidate）。

回答：
1. userInput（kWhRequested / requestedDeparture，via modifiedAt≤t 的最新一条）是否可信作为服务目标；
2. 哪些量可称"服务完成度/服务风险"，哪些只能叫 proxy；
3. 真实 session 中是否存在足够多"此刻削 A 而非 B 会产生不同后续服务结果"的决策机会。

红线：delivered/requested 只能称"请求电量完成比"，不称"服务损失"。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.core_search.r2_c_data_gate import _load_api_metadata, _mapping_path

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r2c1.yaml"


def _extract_session_targets(api: pd.DataFrame) -> pd.DataFrame:
    """每 session 提取连接窗口 + 最新/首条 userInput 的服务目标。"""
    rows: list[dict[str, object]] = []
    for _, r in api.iterrows():
        ui = r.get("userInputs")
        first = last = None
        n_ui = 0
        if isinstance(ui, list) and ui:
            n_ui = len(ui)
            for u in ui:
                if isinstance(u, dict):
                    if first is None:
                        first = u
                    last = u
        rows.append({
            "sessionID": r["sessionID"],
            "site": r.get("site"),
            "connectionTime": r.get("connectionTime"),
            "disconnectTime": r.get("disconnectTime"),
            "doneChargingTime": r.get("doneChargingTime"),
            "kWhDelivered": r.get("kWhDelivered"),
            "n_userInputs": n_ui,
            "kWhRequested_last": (last or {}).get("kWhRequested"),
            "requestedDeparture_last": (last or {}).get("requestedDeparture"),
            "minutesAvailable_last": (last or {}).get("minutesAvailable"),
            "modifiedAt_last": (last or {}).get("modifiedAt"),
            "kWhRequested_first": (first or {}).get("kWhRequested"),
        })
    return pd.DataFrame(rows)


def _physical_realizability(sess: pd.DataFrame, rated_kw: float) -> float:
    conn = pd.to_datetime(sess["connectionTime"], errors="coerce", utc=True)
    disc = pd.to_datetime(sess["disconnectTime"], errors="coerce", utc=True)
    dur_h = (disc - conn).dt.total_seconds() / 3600.0
    max_ach = rated_kw * dur_h
    kreq = pd.to_numeric(sess["kWhRequested_last"], errors="coerce")
    ok = (kreq <= max_ach * 1.1).fillna(False)
    return float(ok.mean()) if not ok.empty else np.nan


def _opportunity_bins(
    sess: pd.DataFrame, min_concurrent: int, divergence_min_kwh: float
) -> int:
    """按小时 bin 统计"并发会话 + kWhRequested 分歧"的决策机会数。"""
    conn = pd.to_datetime(sess["connectionTime"], errors="coerce", utc=True)
    disc = pd.to_datetime(sess["disconnectTime"], errors="coerce", utc=True)
    kreq = pd.to_numeric(sess["kWhRequested_last"], errors="coerce")
    valid = conn.notna() & disc.notna() & kreq.notna()
    conn = conn[valid]
    disc = disc[valid]
    kreq_arr = kreq[valid].to_numpy(dtype="float64")

    if conn.empty:
        return 0
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    conn_h = (conn - epoch).dt.total_seconds().to_numpy() / 3600.0
    disc_h = (disc - epoch).dt.total_seconds().to_numpy() / 3600.0

    start = conn.min().floor("1h")
    end = disc.max().ceil("1h")
    bins = pd.date_range(start, end, freq="1h", tz="UTC")
    bin_h = (bins - epoch).total_seconds().to_numpy() / 3600.0

    count = 0
    for i in range(len(bin_h) - 1):
        t0, t1 = bin_h[i], bin_h[i + 1]
        mask = (conn_h < t1) & (disc_h >= t0)
        n = int(mask.sum())
        if n < min_concurrent:
            continue
        sub = kreq_arr[mask]
        iqr = float(np.percentile(sub, 75) - np.percentile(sub, 25))
        if iqr >= divergence_min_kwh:
            count += 1
    return count


def run_r2_c1(
    rated_power_kw: float = 7.2,
    *,
    validity: dict[str, Any] | None = None,
    opportunity: dict[str, Any] | None = None,
) -> dict[str, object]:
    cfg = load_yaml(_CONFIG)
    validity = validity or dict(cfg["validity_gate"])
    opportunity = opportunity or dict(cfg["opportunity_gate"])

    mapping = pd.read_csv(_mapping_path())
    matched = set(mapping[mapping["match_status"] == "matched"]["sessionID"].astype(str))
    api = _load_api_metadata()
    sess = _extract_session_targets(api)
    sess["sessionID"] = sess["sessionID"].astype(str)
    sess = sess[sess["sessionID"].isin(matched)].copy()

    n_matched = len(matched)
    sess_with_ui = sess[sess["kWhRequested_last"].notna()].copy()
    coverage = float(sess_with_ui.shape[0] / n_matched) if n_matched else 0.0

    # 请求电量完成比
    kd = pd.to_numeric(sess_with_ui["kWhDelivered"], errors="coerce")
    kr = pd.to_numeric(sess_with_ui["kWhRequested_last"], errors="coerce")
    ratio = (kd / kr.replace(0, np.nan)).clip(0.0, 2.0).dropna()

    # departure 偏差
    rd = pd.to_datetime(sess_with_ui["requestedDeparture_last"], errors="coerce", utc=True)
    dc = pd.to_datetime(sess_with_ui["disconnectTime"], errors="coerce", utc=True)
    depart_bias_h = (dc - rd).dt.total_seconds() / 3600.0

    # 会话时长（用于 depart informative 判定）
    conn = pd.to_datetime(sess_with_ui["connectionTime"], errors="coerce", utc=True)
    dur_h = (dc - conn).dt.total_seconds() / 3600.0

    realizable = _physical_realizability(sess_with_ui, rated_power_kw)
    opp_bins = _opportunity_bins(
        sess_with_ui,
        int(opportunity["min_concurrent_sessions"]),
        float(opportunity["kwh_requested_divergence_min_kwh"]),
    )

    ratio_median = float(ratio.median()) if not ratio.empty else np.nan
    ratio_iqr = float(ratio.quantile(0.75) - ratio.quantile(0.25)) if not ratio.empty else np.nan
    depart_abs_med = float(depart_bias_h.abs().median())
    session_dur_med = float(dur_h.median())

    # 判定
    validity_go = (
        coverage >= float(validity["min_userinput_coverage"])
        and (not np.isnan(ratio_iqr) and ratio_iqr >= float(validity["ratio_iqr_min"]))
        and (not np.isnan(realizable) and realizable >= float(validity["physical_realizable_min"]))
    )
    depart_informative = depart_abs_med < session_dur_med / 2.0
    if validity.get("depart_informative", True):
        validity_go = validity_go and depart_informative
    opportunity_go = opp_bins >= int(opportunity["opportunity_bins_min"])
    verdict = "GO" if (validity_go and opportunity_go) else "NO_GO"

    stats: dict[str, object] = {
        "n_matched": n_matched,
        "n_with_userinput": int(sess_with_ui.shape[0]),
        "userinput_coverage": coverage,
        "ratio_median": ratio_median,
        "ratio_iqr": ratio_iqr,
        "ratio_p10": float(ratio.quantile(0.10)) if not ratio.empty else np.nan,
        "ratio_p90": float(ratio.quantile(0.90)) if not ratio.empty else np.nan,
        "ratio_under_half": float((ratio < 0.5).mean()) if not ratio.empty else np.nan,
        "depart_bias_median_h": float(depart_bias_h.median()),
        "depart_bias_abs_median_h": depart_abs_med,
        "depart_bias_abs_p90_h": float(depart_bias_h.abs().quantile(0.9)),
        "session_duration_median_h": session_dur_med,
        "physical_realizable_fraction": realizable,
        "n_multiple_userinputs": int(sess_with_ui[sess_with_ui["n_userInputs"] > 1].shape[0]),
        "opportunity_bins": opp_bins,
        "verdict": verdict,
        "validity_go": validity_go,
        "opportunity_go": opportunity_go,
        "depart_informative": depart_informative,
    }

    out_root = _PATENT_ROOT / str(cfg["outputs"]["results_root"])
    out_root.mkdir(parents=True, exist_ok=True)
    sess_with_ui.to_csv(out_root / "session_targets_matched.csv", index=False)
    pd.Series(stats).to_csv(out_root / "r2_c1_gate_stats.csv", header=["value"])

    _write_report(cfg, stats)
    return stats


def _f(stats: dict[str, object], key: str, digits: int) -> str:
    v = stats.get(key)
    return f"{v:.{digits}f}" if isinstance(v, float) and not np.isnan(v) else str(v)


def _write_report(cfg: dict[str, Any], stats: dict[str, object]) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    L: list[str] = []
    L.append("# CORE_SEARCH_R2_C1_GATE：服务目标有效性与决策机会门\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append("> 配置：configs/core_search_r2c1.yaml（rule_version=core_search_r2c1，冻结）\n")

    L.append("## 1. 目的\n")
    L.append("> 只回答：userInput 是否可信作为服务目标、哪些量是服务完成度/proxy、")
    L.append("> 是否存在足够多服务选择决策机会。不建 Candidate、不报收益。\n")

    L.append("## 2. 服务目标有效性\n")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append(f"| matched 会话数 | {stats.get('n_matched')} |")
    L.append(f"| 有 userInput 的会话数 | {stats.get('n_with_userinput')} |")
    L.append(f"| userInput 覆盖 | {_f(stats, 'userinput_coverage', 3)} |")
    L.append(f"| 请求电量完成比(delivered/requested) 中位 | {_f(stats, 'ratio_median', 3)} |")
    L.append(f"| 完成比 IQR | {_f(stats, 'ratio_iqr', 3)} |")
    L.append(
        f"| 完成比 p10 / p90 | {_f(stats, 'ratio_p10', 3)} / {_f(stats, 'ratio_p90', 3)} |"
    )
    L.append(f"| 完成比 <0.5 占比 | {_f(stats, 'ratio_under_half', 3)} |")
    L.append(
        f"| 物理可实现占比(kWhRequested≤7.2kW×时长×1.1) "
        f"| {_f(stats, 'physical_realizable_fraction', 3)} |"
    )
    L.append(f"| 多 userInput 会话数 | {stats.get('n_multiple_userinputs')} |\n")

    L.append("## 3. departure 偏差（requestedDeparture 是 proxy 而非硬目标）\n")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append(
        f"| disconnect − requestedDeparture 中位（小时） "
        f"| {_f(stats, 'depart_bias_median_h', 2)} |"
    )
    L.append(f"| 偏差绝对值中位（小时） | {_f(stats, 'depart_bias_abs_median_h', 2)} |")
    L.append(f"| 偏差绝对值 p90（小时） | {_f(stats, 'depart_bias_abs_p90_h', 2)} |")
    L.append(f"| 会话时长中位（小时） | {_f(stats, 'session_duration_median_h', 2)} |")
    L.append(f"| 偏差<时长/2（有信息量） | {stats.get('depart_informative')} |\n")

    L.append("## 4. 决策机会（小时 bin × 并发会话 × kWhRequested 分歧）\n")
    L.append(
        f"- 决策机会 bin 数（并发≥2 且 kWhRequested IQR≥5kWh）："
        f"{stats.get('opportunity_bins')}\n"
    )

    L.append("## 5. 门判定\n")
    v = stats.get("verdict")
    marker = {"GO": "**GO**", "NO_GO": "**NO-GO**"}.get(str(v), str(v))
    L.append(f"### 判定：{marker}\n")
    L.append(f"- validity_go: {stats.get('validity_go')}")
    L.append(f"- opportunity_go: {stats.get('opportunity_go')}\n")
    if str(v) == "GO":
        L.append(
            "- userInput 可信度与决策机会均满足 → 可进入 R2-C2 五臂正式 allocation experiment。\n"
        )
    else:
        L.append("- 服务目标或决策机会不足 → 需换评价量或补数据，不进入 R2-C2。\n")

    L.append("## 6. 术语纪律\n")
    L.append("- delivered/requested 仅称\"请求电量完成比\"，不得称\"服务损失\"。")
    L.append("- requestedDeparture 是 proxy（偏差中位明显），不得作为硬服务目标。")
    L.append("- 不把自然事件额外功率下降归因为控制造成的服务损失。\n")

    report_path = _PATENT_ROOT / str(cfg["outputs"]["report"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
