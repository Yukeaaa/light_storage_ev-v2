"""application_state 状态机（Layer 3；P0-2 三层解耦 + 状态持久性 + D3 recovery）。

状态转换（唯一路径，schema `state_machine.transitions`）：
- mode 变化 / run_start / severe_gap_reset → 应用该模式 `default_application_state`；
- M3 段内 boundary-contact 条件连续 `sustained_cycles` 个 1-min cycle → NORMAL
  （D3 recovery，boundary_mode 不变；仅 M3+PROTECTIVE 可触发）。

**封闭形式**：`state = NORMAL if m3_recovered else default[mode]`。

- `m3_recovered` 在 M3 段内单调（首个连续 k 候选后持续 True）→ 天然实现 P0-2
  状态持久性：recovery 后只要 info_mode 仍是 M3，下一 cycle 保持 NORMAL，不重查 default；
- run_start / severe_gap_reset 后 history 清空 → 候选不可能成立 → 回 default
  （M3 新 run = PROTECTIVE）；
- M4（LOCKED）无 protective_bound，候选恒 False → 不可能直接 recovery（P0-2）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.phase3_p2.schema import M3, NORMAL, SchemaConfig

_RUN_KEYS = ["session_id", "run_id"]


def recovery_candidate(cycle: pd.DataFrame, scfg: SchemaConfig) -> pd.Series:
    """boundary-contact 候选（因果化）：mode==M3 且 pb>0 且 actual >= 0.95*pb。

    不含 sustained 连续性；连续性由 `m3_recovered` 处理。actual_power_kw 为当前 cycle
    实测；pb 为 shift(1) 历史（<t），见边界层。
    """
    pb = pd.to_numeric(cycle["protective_bound"], errors="coerce")
    actual = pd.to_numeric(cycle["actual_power_kw"], errors="coerce")
    return (cycle["info_mode"] == M3) & (pb > 0.0) & (actual >= scfg.recovery_ratio * pb)


def _segment_shift(series: pd.Series, seg: pd.Series, lag: int) -> pd.Series:
    """在段 id 分组内对 series 做 lag 位移；越界补 False（跨段不计数）。"""
    frame = pd.DataFrame({"_v": series, "_seg": seg.to_numpy()})
    shifted = frame.groupby("_seg")["_v"].shift(lag)
    return shifted.fillna(False)


def _m3_recovered_flag(out: pd.DataFrame, scfg: SchemaConfig) -> pd.Series:
    """M3 段内首次连续 sustained_cycles 个候选 → 该行起 m3_recovered=True（段内单调）。"""
    cand = recovery_candidate(out, scfg).astype(bool)
    is_m3 = (out["info_mode"] == M3).astype(int)
    prev_m3 = out.groupby(_RUN_KEYS)["info_mode"].shift(1)
    prev_is_m3 = (prev_m3 == M3).astype(int).fillna(0)
    seg_change = out["run_start"] | (is_m3 != prev_is_m3)
    seg = seg_change.cumsum()

    all_k = cand.astype(int).copy()
    for lag in range(1, scfg.recovery_sustained_cycles):
        prev = _segment_shift(cand, seg, lag)
        all_k = all_k & prev.astype(int)
    cum = all_k.groupby(seg).cumsum()
    return (out["info_mode"] == M3) & (cum > 0)


def application_state(
    cycle: pd.DataFrame,
    scfg: SchemaConfig,
) -> tuple[pd.Series, pd.Series]:
    """返回 (application_state, recovery_event)。

    - `recovery_event`：recovery 实际生效的 cycle（m3_recovered 首次由 False→True）。
    - 封闭形式：state = NORMAL if m3_recovered else default[mode]（见模块 docstring）。
    """
    out = cycle.copy()
    mode = out["info_mode"]
    defaults = pd.Series(
        [scfg.default_application_state[m] for m in mode], index=out.index
    )
    recovered = _m3_recovered_flag(out, scfg)
    _rec = out.copy()
    _rec["_recovered"] = recovered.to_numpy()
    prev_recovered = (
        _rec.groupby(_RUN_KEYS)["_recovered"].shift(1).fillna(False).astype(bool)
    )
    recovery_event = recovered & ~prev_recovered

    state = np.where(recovered.to_numpy(), NORMAL, defaults.to_numpy())
    return pd.Series(state, index=out.index), recovery_event


def build_state_frame(
    cycle: pd.DataFrame,
    scfg: SchemaConfig,
) -> pd.DataFrame:
    """在 cycle 层 df 上追加 application_state / recovery_event。

    输入需含：info_mode / run_start / protective_bound / actual_power_kw。
    """
    out = cycle.copy()
    for col in ("info_mode", "run_start", "protective_bound", "actual_power_kw"):
        if col not in out.columns:
            raise ValueError(f"build_state_frame 缺少列: {col}")
    state, recovery_event = application_state(out, scfg)
    out["application_state"] = state
    out["recovery_event"] = recovery_event
    return out
