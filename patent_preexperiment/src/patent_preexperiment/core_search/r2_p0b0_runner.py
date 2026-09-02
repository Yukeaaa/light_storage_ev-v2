"""R2-P0-B0 runner：pilot-stable 下调事件上的真实响应幅度异质性（存在性杀伤门）。

流程：读 P0-A binding down 事件(train+val) → 重建 t+1..t+5 pilot 轨迹 →
区分 pilot-stable(<1A 主判 / <2A 敏感性) → 计算 response_fraction(1/3/5min) →
under-delivery(<0.8) 与 p10 三区门判定 → 分层描述 → 写产物 + 报告。

同步产出 step_magnitude × pilot-stable retention_5m（robustness appendix，non-gating）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.r2_config import R2Config, R2P0B0Config, load_r2_config
from patent_preexperiment.core_search.r2_response import (
    R2P0B0Verdict,
    attach_pilot_trace,
    compute_down_response_fraction,
    compute_retention,
    evaluate_r2_p0b0_gate,
    max_pilot_deviation,
)

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_BINDING_EVENTS = (
    _PATENT_ROOT / "results" / "raw" / "core_search" / "p0_a" / "binding_events.parquet"
)
_SESSION_ROOT = _PATENT_ROOT / "datasets" / "session_response_1min"


def load_binding_down_trainval(events_path: str | Path | None = None) -> pd.DataFrame:
    p = Path(events_path) if events_path else _BINDING_EVENTS
    if not p.exists():
        raise FileNotFoundError(f"未找到 P0-A binding 事件库：{p}")
    ev = pd.read_parquet(p)
    dn = ev[(ev["direction"] == "down") & (ev["split"].isin(["train", "validation"]))]
    return dn.copy()


def load_caltech_pilot_series(session_root: str | Path | None = None) -> pd.DataFrame:
    """加载 caltech 1-min 表的 pilot 序列（仅 session_id/timestamp_utc/pilot_a）。"""
    root = Path(session_root) if session_root else _SESSION_ROOT
    site_dir = root / "site=caltech"
    if not site_dir.exists():
        raise FileNotFoundError(f"未找到 session_response_1min caltech 分区：{site_dir}")
    frames = [
        pd.read_parquet(f, columns=["session_id", "timestamp_utc", "pilot_a"])
        for f in sorted(site_dir.glob("**/data.parquet"))
    ]
    cal = pd.concat(frames, ignore_index=True)
    return cal.drop_duplicates(["session_id", "timestamp_utc"])


def run_r2_p0b0(
    cfg: R2Config | None = None,
    *,
    events: pd.DataFrame | None = None,
) -> tuple[R2P0B0Verdict, pd.DataFrame]:
    cfg = cfg or load_r2_config()
    dn = events if events is not None else load_binding_down_trainval()
    p0 = cfg.p0_b0

    cal = load_caltech_pilot_series()
    trace = attach_pilot_trace(dn, cal, horizon_min=p0.horizon_min)
    dev = max_pilot_deviation(trace, p0.horizon_min)
    trace["_max_pilot_dev_a"] = dev
    trace["stable_primary"] = dev < p0.primary_max_dev_a
    trace["stable_sensitivity"] = dev < p0.sensitivity_max_dev_a

    trace = compute_down_response_fraction(trace, p0.lag_min, p0.clip)
    trace = compute_retention(trace, p0.lag_min)

    primary = trace[trace["stable_primary"]].copy()
    sensitivity = trace[trace["stable_sensitivity"]].copy()

    verdict = evaluate_r2_p0b0_gate(primary, sensitivity, p0)

    # 分层（描述性，不参与主门）
    station_strata = _station_strata(primary)
    step_mag_robustness = _step_magnitude_robustness(primary)

    # 写产物
    out_root = _PATENT_ROOT / p0.results_root
    out_root.mkdir(parents=True, exist_ok=True)
    trace.drop(columns=["_max_pilot_dev_a"], inplace=True)
    trace.to_parquet(out_root / "binding_down_pilot_trace.parquet", index=False)
    pd.DataFrame([_verdict_row(verdict)]).to_csv(
        out_root / "r2_p0b0_gate_verdict.csv", index=False
    )
    _summary_table(primary, sensitivity, p0).to_csv(
        out_root / "r2_p0b0_summary.csv", index=False
    )
    station_strata.to_csv(out_root / "station_strata.csv", index=False)
    step_mag_robustness.to_csv(out_root / "step_magnitude_robustness.csv", index=False)

    _write_report(cfg, verdict, primary, sensitivity, station_strata, step_mag_robustness)
    return verdict, trace


def _summary_table(
    primary: pd.DataFrame, sensitivity: pd.DataFrame, p0: R2P0B0Config
) -> pd.DataFrame:
    rows = []
    for label, df in [("primary(<1A)", primary), ("sensitivity(<2A)", sensitivity)]:
        for lag in p0.lag_min:
            s = df[f"r_{lag}m"].dropna()
            under80 = (
                float((s < p0.gate.under_delivery_threshold).mean())
                if not s.empty
                else np.nan
            )
            rows.append({
                "set": label,
                "lag_min": lag,
                "n": int(s.shape[0]),
                "median": float(s.median()) if not s.empty else np.nan,
                "p10": float(s.quantile(0.10)) if not s.empty else np.nan,
                "p25": float(s.quantile(0.25)) if not s.empty else np.nan,
                "p75": float(s.quantile(0.75)) if not s.empty else np.nan,
                "p90": float(s.quantile(0.90)) if not s.empty else np.nan,
                "iqr": (
                    float(s.quantile(0.75) - s.quantile(0.25))
                    if not s.empty
                    else np.nan
                ),
                "under80": under80,
            })
    return pd.DataFrame(rows)


def _station_strata(primary: pd.DataFrame) -> pd.DataFrame:
    if primary.empty:
        return pd.DataFrame(columns=["station_id", "n", "r_1m_median", "under80"])
    rows = []
    for st, g in primary.groupby("station_id", observed=True):
        s = g["r_1m"].dropna()
        rows.append({
            "station_id": st,
            "n": int(g.shape[0]),
            "r_1m_median": float(s.median()) if not s.empty else np.nan,
            "under80": float((s < 0.8).mean()) if not s.empty else np.nan,
        })
    return pd.DataFrame(rows).sort_values("n", ascending=False)


def _step_magnitude_robustness(primary: pd.DataFrame) -> pd.DataFrame:
    """step_magnitude × pilot-stable retention_5m（non-gating appendix）。"""
    col = "retention_5m"
    if primary.empty or "step_magnitude_bin" not in primary.columns:
        return pd.DataFrame(
            columns=[
                "step_magnitude_bin", "n", "retention_5m_median",
                "retention_5m_p25", "retention_5m_p75",
            ]
        )
    rows = []
    for b, g in primary.groupby("step_magnitude_bin", observed=True):
        s = g[col].dropna()
        rows.append({
            "step_magnitude_bin": b,
            "n": int(g.shape[0]),
            "retention_5m_median": float(s.median()) if not s.empty else np.nan,
            "retention_5m_p25": float(s.quantile(0.25)) if not s.empty else np.nan,
            "retention_5m_p75": float(s.quantile(0.75)) if not s.empty else np.nan,
        })
    return pd.DataFrame(rows)


def _verdict_row(v: R2P0B0Verdict) -> dict[str, object]:
    return {
        "verdict": v.verdict,
        "primary_n": v.primary_n,
        "primary_under80": v.primary_under80,
        "primary_p10": v.primary_p10,
        "primary_r1m_median": v.primary_r1m_median,
        "primary_r1m_iqr": v.primary_r1m_iqr,
        "sensitivity_n": v.sensitivity_n,
        "sensitivity_under80": v.sensitivity_under80,
        "sensitivity_p10": v.sensitivity_p10,
        "sensitivity_reversed": v.sensitivity_reversed,
    }


def _write_report(
    cfg: R2Config,
    verdict: R2P0B0Verdict,
    primary: pd.DataFrame,
    sensitivity: pd.DataFrame,
    station_strata: pd.DataFrame,
    step_mag_robustness: pd.DataFrame,
) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    p0 = cfg.p0_b0
    g = p0.gate
    L: list[str] = []
    L.append("# CORE_SEARCH_R2_P0B0：pilot-stable 下调事件上的响应幅度异质性\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append(f"> 配置：configs/core_search_r2.yaml（rule_version={cfg.rule_version}，冻结）")
    L.append(
        "> 方法学：自然控制事件推断设备响应，必须审计 (t,t+h] 控制输入轨迹"
        "（master plan 通用规则）\n"
    )

    L.append("## 1. 目的\n")
    L.append("> pilot 持续压低后，车辆下调是否还存在值得预测的欠交付异质性？\n")

    L.append("## 2. 主判集与敏感性\n")
    L.append(
        f"- 主判集：binding down + pilot-stable(<{p0.primary_max_dev_a:.0f}A "
        f"over t..t+{p0.horizon_min}) + train+val"
    )
    L.append(f"- 敏感性：<{p0.sensitivity_max_dev_a:.0f}A")
    L.append(f"- 欠交付定义：r_1m < {g.under_delivery_threshold}\n")

    L.append("## 3. response_fraction 汇总（pilot-stable）\n")
    L.append("| set | lag | n | median | p10 | p25 | p75 | p90 | IQR | under80 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in _summary_table(primary, sensitivity, p0).iterrows():
        L.append(
            f"| {r['set']} | {int(r['lag_min'])} | {int(r['n'])} | {r['median']:.3f} | "
            f"{r['p10']:.3f} | {r['p25']:.3f} | {r['p75']:.3f} | {r['p90']:.3f} | "
            f"{r['iqr']:.3f} | {r['under80']:.3f} |"
        )
    L.append("")

    L.append("## 4. 三区门判定\n")
    marker = {"CLOSED": "**CLOSED**", "CONDITIONAL": "**CONDITIONAL**", "OPEN": "**OPEN**"}
    L.append(f"### 判定：{marker.get(verdict.verdict, verdict.verdict)}\n")
    L.append(f"> {verdict.reason}\n")
    L.append("| 指标 | 值 | 阈值 |")
    L.append("|---|---|---|")
    L.append(
        f"| primary under80 (r_1m<0.8) | {verdict.primary_under80:.3f} "
        f"| CLOSED if ≤{g.closed_under80_max} |"
    )
    L.append(f"| primary r_1m p10 | {verdict.primary_p10:.3f} | CLOSED if ≥{g.closed_p10_min} |")
    L.append(f"| primary r_1m median | {verdict.primary_r1m_median:.3f} | — |")
    L.append(f"| primary r_1m IQR | {verdict.primary_r1m_iqr:.3f} | — |")
    L.append(f"| sensitivity(<2A) under80 | {verdict.sensitivity_under80:.3f} | 无方向性反转 |")
    L.append(f"| sensitivity(<2A) p10 | {verdict.sensitivity_p10:.3f} | 无方向性反转 |")
    L.append(f"| sensitivity reversed | {verdict.sensitivity_reversed} | False |\n")

    L.append("## 5. station 分层（描述性，不参与主门）\n")
    if not station_strata.empty:
        L.append("| station_id | n | r_1m_median | under80 |")
        L.append("|---|---|---|---|")
        for _, r in station_strata.head(20).iterrows():
            L.append(
                f"| {r['station_id']} | {int(r['n'])} | {r['r_1m_median']:.3f} "
                f"| {r['under80']:.3f} |"
            )
        L.append("")

    L.append("## 6. robustness appendix（step_magnitude × retention_5m，non-gating）\n")
    if not step_mag_robustness.empty:
        L.append("| step_magnitude_bin | n | retention_5m median | p25 | p75 |")
        L.append("|---|---|---|---|---|")
        for _, r in step_mag_robustness.iterrows():
            L.append(
                f"| {r['step_magnitude_bin']} | {int(r['n'])} | {r['retention_5m_median']:.3f} | "
                f"{r['retention_5m_p25']:.3f} | {r['retention_5m_p75']:.3f} |"
            )
        L.append("")
    L.append("> 注：此表只作 robustness，不重新打开 R2-A（R2-A 已 CLOSED）。\n")

    L.append("## 7. 结论\n")
    if verdict.verdict == "CLOSED":
        L.append("- 下调欠交付几乎不存在 → **R2-B CLOSED**（无 selection problem）。")
        L.append("- 下调侧高度可靠、常过冲（r>1）；唯一变化在过冲方向，指向服务代价 → R2-C。\n")
    elif verdict.verdict == "OPEN":
        L.append("- 存在大量欠交付 → 需进一步验证其在线可观测结构后，才可进入 R2-B 预注册。\n")
    else:
        L.append("- 欠交付处于灰区 → 仅诊断结构，不建模型。\n")

    L.append("## 8. 产物文件\n")
    L.append("- `results/raw/core_search/r2_p0b0/binding_down_pilot_trace.parquet`")
    L.append("- `results/raw/core_search/r2_p0b0/r2_p0b0_gate_verdict.csv`")
    L.append("- `results/raw/core_search/r2_p0b0/r2_p0b0_summary.csv`")
    L.append("- `results/raw/core_search/r2_p0b0/station_strata.csv`")
    L.append("- `results/raw/core_search/r2_p0b0/step_magnitude_robustness.csv`\n")

    report_path = _PATENT_ROOT / p0.report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
