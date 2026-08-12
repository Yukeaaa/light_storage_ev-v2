"""P2.1A formal diagnostics（v1.3 §4.5 / §5 报告必报项；诊断/审计，不入门）。

frozen v1.3 要求正式结果除 A Gate 数字外，还要报告：
  - B0/B1 trigger timing distribution（F2 timing confound 审计材料）
  - 最差站点 / 月份分层结果
  - ≥ 20 个失败案例（B0 trigger 且 Y=0）可视化

**本模块只由 run_formal_test 延迟 import**（Step-0 import 物理隔离）；诊断字段
**绝不进入 Gate 计算**（Gate 只消费 point_metrics + delta_cis）。

失败案例选择机械固定：按 (session_id, segment_id, timestamp_utc) 稳定排序取前 20，
禁止人工挑图。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.phase3_p2_1.triggers import B0, B1

N_FAILURE_CASES = 20
"""frozen v1.3 §4.5 要求的失败案例最少数量（公开常量，供 runner 报告引用）。"""
_FIG_DPI = 100


def generate_formal_diagnostics(
    trigger_table: pd.DataFrame,
    eligible: pd.DataFrame,
    bf: pd.DataFrame,
    out_dir: Path,
) -> dict[str, Any]:
    """生成 formal 诊断 artifacts（timing 分布 / 站点月分层 / 失败案例可视化）。

    Args:
        trigger_table: build_trigger_table 输出（含 y, method, session_id, segment_id,
            cycle_index, timestamp_utc）。需另含 station_id（由 build_trigger_table
            透传或此处 join）。
        eligible: Step-0 eligible artifact（含 station_id, session_id, segment_id,
            timestamp_utc, site）。
        bf: Step-0 boundary_frame artifact（含 station_id, site, session_id, run_id,
            segment_id, timestamp_utc, actual_power_kw, protective_bound, post_window_ok）。
        out_dir: 诊断 artifact 落盘目录（results/raw/phase3_p2_1/）。

    Returns:
        {timing_table, station_month_table, failure_cases, timing_plot, failure_plot}
        的路径与摘要；全部确定性可复现。
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. B0/B1 trigger timing distribution（cycle_index 直方图）
    timing = _timing_distribution(trigger_table)

    # 2. 站点 / 月份分层（用 eligible 的 station_id/site + timestamp_utc 派生 month）
    station_month = _station_month_stratified(trigger_table, eligible)

    # 3. ≥20 失败案例（B0 trigger 且 Y=0），机械固定选取
    failure_cases = _select_failure_cases(trigger_table, eligible, bf, N_FAILURE_CASES)
    n_failure_available = _count_b0_failures(trigger_table)
    n_selected = int(len(failure_cases))
    requirement_met = n_failure_available >= N_FAILURE_CASES

    # 4. 可视化（matplotlib Agg backend，无 GUI 依赖）
    timing_plot = _write_timing_plot(timing, out_dir / "p2_1a_timing_distribution.png")
    failure_plot = _write_failure_cases_plot(
        failure_cases, bf, out_dir / "p2_1a_failure_cases.png"
    )

    # 落盘表格（parquet + csv，便于审计）
    timing_path = out_dir / "p2_1a_timing_distribution.parquet"
    timing.to_parquet(timing_path, index=False)
    sm_path = out_dir / "p2_1a_station_month.parquet"
    station_month.to_parquet(sm_path, index=False)
    fc_path = out_dir / "p2_1a_failure_cases.parquet"
    failure_cases.to_parquet(fc_path, index=False)

    # worst B0 stratum（gain 最低；tie → station_id, month 字典序）
    worst_b0 = _worst_b0_stratum(station_month)

    return {
        "timing_distribution": {
            "path": str(timing_path.as_posix()),
            "plot": str(timing_plot.as_posix()),
            "n_b0_triggers": int(
                timing.loc[timing["method"] == B0, "count"].sum()
            ) if not timing.empty else 0,
            "n_b1_triggers": int(
                timing.loc[timing["method"] == B1, "count"].sum()
            ) if not timing.empty else 0,
        },
        "station_month": {
            "path": str(sm_path.as_posix()),
            "n_strata": int(len(station_month)),
            "worst_b0_station_month": worst_b0,
        },
        "failure_cases": {
            "path": str(fc_path.as_posix()),
            "plot": str(failure_plot.as_posix()),
            "n_selected": n_selected,
            "n_available": n_failure_available,
            "requirement_met": requirement_met,
            "diagnostic_shortfall": (not requirement_met),
            "selection_rule": (
                "B0 trigger & Y=0，按 (session_id, segment_id, timestamp_utc) "
                f"稳定排序取前 {min(N_FAILURE_CASES, n_failure_available)}/"
                f"{N_FAILURE_CASES}，禁止人工挑图"
            ),
        },
    }


def _timing_distribution(trigger_table: pd.DataFrame) -> pd.DataFrame:
    """B0/B1 trigger 的 cycle_index 直方图（每个 cycle_index 的计数）。"""
    rows = []
    for method in (B0, B1):
        sub = trigger_table[trigger_table["method"] == method]
        if sub.empty:
            continue
        vc = sub["cycle_index"].value_counts().sort_index()
        for ci, cnt in vc.items():
            rows.append({
                "method": method,
                "cycle_index": int(ci) if isinstance(ci, (int, float)) else -1,
                "count": int(cnt),
            })
    return pd.DataFrame(rows, columns=["method", "cycle_index", "count"])


def _station_month_stratified(
    trigger_table: pd.DataFrame,
    eligible: pd.DataFrame,
) -> pd.DataFrame:
    """按 (station_id, month) 分层的 trigger 数与 gain。month 从 timestamp_utc 派生。"""
    if "station_id" not in eligible.columns:
        return pd.DataFrame(columns=["station_id", "month", "method", "n", "gain"])
    # trigger_table 无 station_id → join eligible
    key_cols = ["segment_id", "timestamp_utc"]
    has_station = "station_id" in trigger_table.columns
    if not has_station:
        tt = trigger_table.merge(
            eligible[key_cols + ["station_id"]], on=key_cols, how="left"
        )
    else:
        tt = trigger_table.copy()
    tt["month"] = pd.to_datetime(tt["timestamp_utc"]).dt.strftime("%Y-%m")
    rows = []
    for (station, month, method), sub in tt.groupby(
        ["station_id", "month", "method"], sort=True
    ):
        rows.append({
            "station_id": str(station),
            "month": str(month),
            "method": str(method),
            "n": int(len(sub)),
            "gain": float(sub["y"].mean()) if len(sub) > 0 else float("nan"),
        })
    return pd.DataFrame(rows, columns=["station_id", "month", "method", "n", "gain"])


def _select_failure_cases(
    trigger_table: pd.DataFrame,
    eligible: pd.DataFrame,
    bf: pd.DataFrame,
    n: int,
) -> pd.DataFrame:
    """机械固定选取 ≥n 个 B0 trigger 且 Y=0 的失败案例。

    选择规则：B0 trigger & Y=0 → 按 (session_id, segment_id, timestamp_utc) 稳定排序
    → 取前 n。禁止人工挑图。
    """
    b0 = trigger_table[(trigger_table["method"] == B0) & (~trigger_table["y"])].copy()
    if b0.empty:
        return pd.DataFrame(columns=["session_id", "segment_id", "timestamp_utc",
                                     "cycle_index", "station_id", "actual_power_kw",
                                     "protective_bound", "y"])
    b0 = b0.sort_values(["session_id", "segment_id", "timestamp_utc"]).head(n)
    # join station_id / actual / pb from eligible for context（b0 已有 station_id →
    # 先 drop 再 merge，避免 pandas 自动加 _x/_y 后缀）
    key_cols = ["segment_id", "timestamp_utc"]
    ctx = eligible[key_cols + ["actual_power_kw", "protective_bound"]].rename(
        columns={"actual_power_kw": "ctx_actual", "protective_bound": "ctx_pb"}
    )
    b0 = b0.merge(ctx, on=key_cols, how="left")
    b0 = b0.rename(columns={"ctx_actual": "actual_power_kw", "ctx_pb": "protective_bound"})
    keep = ["session_id", "segment_id", "timestamp_utc", "cycle_index",
            "station_id", "actual_power_kw", "protective_bound", "y"]
    return b0[keep].reset_index(drop=True)


def _count_b0_failures(trigger_table: pd.DataFrame) -> int:
    """B0 trigger 且 Y=0 的总数（用于判断 ≥20 requirement 是否满足）。"""
    b0 = trigger_table[(trigger_table["method"] == B0) & (~trigger_table["y"])]
    return int(len(b0))


def _worst_b0_stratum(station_month: pd.DataFrame) -> dict[str, Any] | None:
    """B0 strata 中 gain 最低者；tie → (station_id, month) 字典序。

    返回 {station_id, month, n, gain} 或 None（无 B0 strata）。
    纯诊断，不进 Gate。
    """
    if station_month.empty:
        return None
    b0 = station_month[station_month["method"] == B0].copy()
    if b0.empty:
        return None
    # gain 最低；tie → station_id, month 字典序（稳定机械选取）
    b0 = b0.sort_values(
        ["gain", "station_id", "month"], ascending=[True, True, True]
    )
    row = b0.iloc[0]
    return {
        "station_id": str(row["station_id"]),
        "month": str(row["month"]),
        "n": int(row["n"]),
        "gain": float(row["gain"]) if pd.notna(row["gain"]) else None,
    }


def _write_timing_plot(timing: pd.DataFrame, path: Path) -> Path:
    """B0/B1 cycle_index 分布柱状图（matplotlib Agg backend）。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    if not timing.empty:
        for method, color in ((B0, "tab:blue"), (B1, "tab:orange")):
            sub = timing[timing["method"] == method]
            if not sub.empty:
                ax.bar(
                    sub["cycle_index"] + (0.4 if method == B1 else -0.4),
                    sub["count"], width=0.4, label=method, color=color, alpha=0.8,
                )
    ax.set_xlabel("cycle_index (within segment)")
    ax.set_ylabel("trigger count")
    ax.set_title("P2.1A B0/B1 trigger timing distribution")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=_FIG_DPI)
    plt.close(fig)
    return path


def _write_failure_cases_plot(failure_cases: pd.DataFrame, bf: pd.DataFrame, path: Path) -> Path:
    """失败案例 actual_power / protective_bound 轨迹小图（最多 20 个子图）。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(failure_cases)
    if n == 0:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "No B0-trigger & Y=0 failure cases", ha="center", va="center")
        ax.set_title("P2.1A failure cases (B0 trigger & Y=0)")
        fig.savefig(path, dpi=_FIG_DPI)
        plt.close(fig)
        return path

    ncols = 4
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows), squeeze=False)
    for idx in range(nrows * ncols):
        ax = axes[idx // ncols][idx % ncols]
        if idx < n:
            row = failure_cases.iloc[idx]
            seg_bf = bf[
                (bf["segment_id"] == row["segment_id"])
                & (bf["session_id"] == row["session_id"])
            ].sort_values("timestamp_utc")
            if not seg_bf.empty:
                xs = seg_bf["cycle_index"].to_numpy()
                ax.plot(xs, seg_bf["actual_power_kw"].to_numpy(),
                        label="actual", color="tab:blue", linewidth=1)
                ax.plot(xs, seg_bf["protective_bound"].to_numpy(),
                        label="pb (Q95)", color="tab:red", linewidth=1, linestyle="--")
                trig_ci = int(row["cycle_index"])
                ax.axvline(trig_ci, color="tab:green", linestyle=":", linewidth=1,
                           label="B0 trigger")
            ax.set_title(
                f"{row['session_id'][:12]} c={trig_ci}", fontsize=7
            )
            ax.tick_params(labelsize=6)
            if idx == 0:
                ax.legend(fontsize=6)
        else:
            ax.set_visible(False)
    fig.suptitle("P2.1A failure cases (B0 trigger & Y=0, mechanical selection)", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=_FIG_DPI)
    plt.close(fig)
    return path
