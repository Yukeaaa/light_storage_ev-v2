"""D2 — 动作输入（controller-conformance replay）与约束等级 → 允许修正区间。

- 输入完全外生（v1.0.1 P0-1）：budget/probe 只依赖 (session_id, cycle_index)，
  生成时**不读取** boundary_value / allowed interval / actual / application_state /
  outcome。本模块不做任何数据运算，结构化保证独立性。
- md5hex 机械冻结（v1.0.2 freeze）：seed_byte = int(MD5(UTF-8 session_id) hex 前两位, 16)。
- disposition 唯一化（P0-1 fix）：accepted / clipped_upper / clipped_lower，无 reject。
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.phase3_p2.schema import LOCKED, NORMAL, PROTECTIVE, SchemaConfig

ACCEPTED = "accepted"
CLIPPED_UPPER = "clipped_upper"
CLIPPED_LOWER = "clipped_lower"
BOUNDARY_UNAVAILABLE = "boundary_unavailable"


def seed_byte(session_id: str) -> int:
    """v1.0.2 freeze：seed_byte = int(md5_hex[0:2], 16)；session_id 原样（不 trim）。"""
    md5_hex = hashlib.md5(session_id.encode("utf-8")).hexdigest()
    return int(md5_hex[:2], 16)


def budget_kw(seed: int, scfg: SchemaConfig) -> float:
    """B = base + step * (seed mod modulus) → {3.0, 4.5, 6.0, 7.5}。"""
    return scfg.budget_base_kw + scfg.budget_step_kw * float(seed % scfg.budget_modulus)


def probe_kw(seed: int, cycle_index: int, scfg: SchemaConfig) -> float:
    """probe(t) = grid[(cycle_index + seed mod 5) mod 5]；与 boundary/state 无关。"""
    idx = (cycle_index + seed % scfg.probe_modulus) % scfg.probe_modulus
    return scfg.probe_grid[idx]


def allowed_interval(
    state: str,
    budget: float,
    boundary: float | None,
    scfg: SchemaConfig,
) -> tuple[float | None, float | None]:
    """application_state → (L, U)。M3 recovery 后 NORMAL 用同一 protective boundary 值。"""
    if state == LOCKED:
        return 0.0, 0.0
    if state == PROTECTIVE:
        return -budget, 0.0
    if state == NORMAL:
        if boundary is None:
            return None, None
        return -budget, max(0.0, boundary - budget)
    raise ValueError(f"非法 application_state: {state!r}")


def disposition_of(requested: float, lower: float | None, upper: float | None) -> str:
    """唯一 disposition 语义（schema action_disposition；L/U 缺失 → boundary_unavailable）。"""
    if lower is None or upper is None:
        return BOUNDARY_UNAVAILABLE
    if lower <= requested <= upper:
        return ACCEPTED
    if requested > upper:
        return CLIPPED_UPPER
    return CLIPPED_LOWER


def clip_delta(requested: float, lower: float | None, upper: float | None) -> float | None:
    if lower is None or upper is None:
        return None
    return float(min(max(requested, lower), upper))


def build_action_frame(
    cycle: pd.DataFrame,
    scfg: SchemaConfig,
    seed_map: dict[str, int],
) -> pd.DataFrame:
    """在 cycle 层 df 上追加外生动作输入（budget/probe）与约束输出（L/U/final/disposition）。

    `cycle` 必须已含：session_id / cycle_index / info_mode / application_state /
    boundary_value（模式相关的边界值：M1=injection 标量、M3=protective_bound、
    M2/M4=NaN）。所有数值列用 float64；边界缺失用 NaN（→ boundary_unavailable）。
    """
    out = cycle.copy()
    seeds = np.array(
        [seed_map.get(sid, -1) for sid in out["session_id"]], dtype=np.int64
    )
    if (seeds < 0).any():
        raise RuntimeError("P2 动作输入失败：存在未注册 session_id 的 seed")
    out["seed_byte"] = seeds
    out["budget"] = scfg.budget_base_kw + scfg.budget_step_kw * (
        seeds % scfg.budget_modulus
    ).astype(np.float64)
    probe_idx = (
        out["cycle_index"].to_numpy(dtype=np.int64) + seeds % scfg.probe_modulus
    ) % scfg.probe_modulus
    grid = np.asarray(scfg.probe_grid, dtype=np.float64)
    out["requested_delta"] = grid[probe_idx]
    out["probe_seed"] = seeds % scfg.probe_modulus
    out["budget_seed"] = seeds % scfg.budget_modulus

    is_locked = out["application_state"] == LOCKED
    is_protective = out["application_state"] == PROTECTIVE
    boundary = out["boundary_value"].astype(np.float64)
    budget = out["budget"].astype(np.float64)

    lower = np.where(is_locked, 0.0, -budget)
    upper_normal = np.where(
        boundary.isna(),
        np.nan,
        np.maximum(0.0, boundary - budget),
    )
    upper = np.where(is_locked, 0.0, np.where(is_protective, 0.0, upper_normal))
    out["L"] = np.where(is_locked, 0.0, -budget)
    out["U"] = upper

    request = out["requested_delta"].to_numpy(dtype=np.float64)
    final = np.empty(len(out), dtype=np.float64)
    final[:] = np.nan
    has_bound = ~np.isnan(upper)
    final[has_bound] = np.clip(request[has_bound], lower[has_bound], upper[has_bound])
    out["final_delta"] = final

    disp = np.empty(len(out), dtype=object)
    disp[:] = BOUNDARY_UNAVAILABLE
    ok = has_bound
    accepted = ok & (request >= lower) & (request <= upper)
    upper_clip = ok & (request > upper)
    lower_clip = ok & (request < lower)
    disp[accepted] = ACCEPTED
    disp[upper_clip] = CLIPPED_UPPER
    disp[lower_clip] = CLIPPED_LOWER
    out["disposition"] = disp

    # 独立一致性检查：final == clip(requested, L, U)（用纯标量 clip 重算）
    clip_final = np.full(len(out), np.nan, dtype=np.float64)
    clip_final[has_bound] = np.clip(request[has_bound], lower[has_bound], upper[has_bound])
    out["_clip_check"] = np.isclose(final, clip_final, equal_nan=False) | ~has_bound
    out["_has_bound"] = has_bound

    # 反事实等级（K2 / trace after-condition 审计用）：同一 probe 在另两等级下的 final
    cf_locked = np.clip(request, 0.0, 0.0)
    cf_protective = np.clip(request, -budget.to_numpy(), 0.0)
    cf_normal = np.where(
        np.isnan(upper_normal),
        np.nan,
        np.clip(request, -budget.to_numpy(), upper_normal),
    )
    out["final_cf_locked"] = cf_locked
    out["final_cf_protective"] = cf_protective
    out["final_cf_normal"] = cf_normal
    return out


def seed_map_for(ids: Any) -> dict[str, int]:
    """由 session_id 集合构建 seed 映射（审计：probe/budget 只依赖 session_id）。"""
    return {sid: seed_byte(sid) for sid in ids}
