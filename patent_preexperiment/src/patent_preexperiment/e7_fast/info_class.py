"""信息类别逐分钟判定（review §3.1；复用 P2 冻结 d1 查表与 boundary Q95，只读不改）。

- 四个布尔：capability_available（ACN 无真实 capability → 恒 False）/ pilot_available /
  actual_available / history_sufficient。
- info_mode：穷尽 precedence 查表（P2 d1.build_info_mode_table），16 组合 → M1/M2/M3/M4。
- Q95 历史：P2 boundary.protective_bound（shift(1) + 15min 窗，因果化）。
- run 定义：绑定 E0 severe_gap_before（severe_gap_before=true 开新 run，滚动窗重置）。
"""

from __future__ import annotations

import pandas as pd

from patent_preexperiment.e7_fast.config import E7FastConfig
from patent_preexperiment.phase3_p2.boundary import (
    assign_runs,
    history_sufficiency,
    protective_bound,
)
from patent_preexperiment.phase3_p2.d1 import build_info_mode_table, info_code
from patent_preexperiment.phase3_p2.schema import M1, M2, M3, M4

_INFO_MODES = (M1, M2, M3, M4)


def attach_info_class(
    df: pd.DataFrame,
    cfg: E7FastConfig,
    *,
    history_limit_per_run: int | None = None,
) -> pd.DataFrame:
    """为 1-min 会话表附加 run/cycle/history/info 布尔/info_mode/q95_history。

    输入要求列：session_id, timestamp_utc, actual_power_kw, pilot_available,
                severe_gap_before, gap_before_min（assign_runs 需要）。
    返回副本，新增列：run_id, cycle_index, history_count, history_sufficient,
                      capability_available, pilot_available（已存在则复用）,
                      actual_available, info_code, info_mode, q95_history_kw。
    """
    scfg = cfg.p2_schema
    out = assign_runs(df, history_limit_per_run=history_limit_per_run)
    out["history_sufficient"] = history_sufficiency(out, scfg)
    out["capability_available"] = False  # ACN 无真实 BMS capability（review §3.1 / M1 仅从属）
    if "pilot_available" not in out.columns:
        raise ValueError("attach_info_class 需要 pilot_available 列")
    out["actual_available"] = out["actual_power_kw"].notna()
    # info_code = cap*8 + pilot*4 + actual*2 + history
    out["info_code"] = (
        out["capability_available"].astype(int) * 8
        + out["pilot_available"].astype(int) * 4
        + out["actual_available"].astype(int) * 2
        + out["history_sufficient"].astype(int)
    )
    _table, mode_arr, _reason_arr = build_info_mode_table(scfg)
    out["info_mode"] = out["info_code"].map(dict(enumerate(mode_arr)))
    if out["info_mode"].isna().any():
        raise RuntimeError("info_mode 映射出现 NaN（precedence 查表未穷尽？）")
    out["q95_history_kw"] = protective_bound(out, scfg).to_numpy()
    return out


def info_mode_of(
    capability: bool, pilot: bool, actual: bool, history: bool, cfg: E7FastConfig
) -> str:
    """单点信息模式查表（供测试 / 单 cycle 求值）。"""
    _table, mode_arr, _reason_arr = build_info_mode_table(cfg.p2_schema)
    return mode_arr[info_code(capability, pilot, actual, history)]
