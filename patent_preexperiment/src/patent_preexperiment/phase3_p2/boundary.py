"""M3 边界生成器 —— history_protective_boundary（D2/D3 数值门自然 embodiment）。

- 窗口：同一 run 内、严格早于当前 cycle（`shift(1)` 因果化）、时间窗 `window_min`
  分钟、非空 `actual_power_kw` 的 0.95 分位；窗内样本 < `min_samples` → 边界为空。
- run 定义绑定 E0 `severe_gap_before`：`severe_gap_before=true` 开新 run，滚动窗重置。
- history_sufficiency：当前 cycle 之前、同一 run 内、非空 `actual_power_kw` 样本数
  >= `min_history_samples`（按 schema 字面定义，不设时间窗上限）。
"""

from __future__ import annotations

import pandas as pd

from patent_preexperiment.phase3_p2.schema import SchemaConfig

_RUN_KEYS = ["session_id", "run_id"]


def assign_runs(
    df: pd.DataFrame,
    *,
    history_limit_per_run: int | None = None,
) -> pd.DataFrame:
    """按 E0 severe_gap_before 切 run，并计算 cycle_index / run_start。

    - run 边界：session 首行 或 `severe_gap_before == True`。
    - `history_limit_per_run`（replay 专用）：只把每个 run 前 K 行纳入历史，
      用于演示 history-insufficient → M4 conservative fallback。
    - 返回副本，原 df 不变。
    """
    out = df.copy()
    out = out.sort_values(["session_id", "timestamp_utc"], kind="stable")
    out["_first"] = out.groupby("session_id").cumcount() == 0
    out["_new_run"] = out["_first"] | out["severe_gap_before"].fillna(True)
    out["run_id"] = out.groupby("session_id")["_new_run"].cumsum()
    out["cycle_index"] = out.groupby(_RUN_KEYS).cumcount()
    out["run_start"] = out["_new_run"]
    out["_pos"] = out.groupby(_RUN_KEYS).cumcount()
    out["_nonnull"] = out["actual_power_kw"].notna().astype(int)
    cum = out.groupby(_RUN_KEYS)["_nonnull"].cumsum()
    if history_limit_per_run is not None:
        if history_limit_per_run < 0:
            raise ValueError(f"history_limit_per_run 必须 >=0: {history_limit_per_run}")
        keep = out["_pos"] < history_limit_per_run
        cum = cum.where(keep)
    out["_cum"] = cum
    out["history_count"] = (
        out.groupby(_RUN_KEYS)["_cum"].shift(1).fillna(0).astype(int)
    )
    return out


def history_sufficiency(out: pd.DataFrame, scfg: SchemaConfig) -> pd.Series:
    """history_sufficient = run 内当前 cycle 之前的非空 actual 样本数 >= min_history_samples。"""
    return out["history_count"] >= scfg.min_history_samples


def protective_bound(
    out: pd.DataFrame,
    scfg: SchemaConfig,
) -> pd.Series:
    """因果化 protective_bound：shift(1) + 时间窗 Q95；样本不足 → NaN（null boundary）。

    返回与 `out` 对齐的 Series（按 session_id/run_id/timestamp_utc merge 回原序）。
    """
    dfi = out.copy()
    dfi["_row_id"] = range(len(dfi))
    dfi = dfi.set_index("_row_id")
    dfi["_shift"] = dfi.groupby(_RUN_KEYS)["actual_power_kw"].shift(1)
    rolled = (
        dfi.groupby(_RUN_KEYS)[["_shift", "timestamp_utc"]]
        .rolling(
            f"{scfg.history_window_min}min",
            min_periods=scfg.history_min_samples,
            on="timestamp_utc",
        )
        .quantile(scfg.history_quantile)
        .reset_index()
    )
    # rolled 列：session_id/run_id/_row_id/_shift/timestamp_utc；按 _row_id 对回原序
    ordered = rolled.sort_values("_row_id").set_index("_row_id")
    if len(ordered) != len(out):
        raise RuntimeError(
            "protective_bound 对齐失败：rolling 结果行数不一致"
        )
    return ordered["_shift"].reset_index(drop=True)


def build_boundary_frame(
    df: pd.DataFrame,
    scfg: SchemaConfig,
    *,
    history_limit_per_run: int | None = None,
) -> pd.DataFrame:
    """per-cycle 边界层：run/cycle_index/history_sufficiency/protective_bound。"""
    out = assign_runs(df, history_limit_per_run=history_limit_per_run)
    out["history_sufficient"] = history_sufficiency(out, scfg)
    out["protective_bound"] = protective_bound(out, scfg).to_numpy()
    return out
