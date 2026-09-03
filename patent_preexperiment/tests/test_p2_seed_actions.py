"""P2 D2 动作输入（seed/budget/probe）与约束等级 → 允许区间单测（v1.0.1 P0-1 / v1.0.2 freeze）。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from patent_preexperiment.phase3_p2.actions import (
    ACCEPTED,
    BOUNDARY_UNAVAILABLE,
    CLIPPED_LOWER,
    CLIPPED_UPPER,
    allowed_interval,
    budget_kw,
    build_action_frame,
    disposition_of,
    probe_kw,
    seed_byte,
    seed_map_for,
)
from patent_preexperiment.phase3_p2.schema import (
    LOCKED,
    M2,
    M3,
    M4,
    NORMAL,
    PROTECTIVE,
    load_schema,
)

PP = Path(__file__).resolve().parents[1]
SCFG = load_schema(PP / "configs" / "phase3_p2_action_schema.yaml")


def test_seed_byte_deterministic_and_bounded() -> None:
    for sid in ("sess_a", "sess_b", "sess_long-name-123"):
        s1 = seed_byte(sid)
        assert s1 == seed_byte(sid)
        assert 0 <= s1 <= 255
    # 不同会话一般不同（md5 首字节）；至少不全部相同
    seeds = {seed_byte(s) for s in ("a1", "a2", "a3", "a4", "a5")}
    assert len(seeds) >= 2


def test_seed_map_covers_sessions() -> None:
    ids = ["x1", "x2", "x3"]
    sm = seed_map_for(ids)
    assert set(sm) == set(ids)
    assert sm["x1"] == seed_byte("x1")


def test_budget_values_frozen_grid() -> None:
    for seed in range(0, 256):
        b = budget_kw(seed, SCFG)
        assert b in (3.0, 4.5, 6.0, 7.5)
        assert b == pytest.approx(3.0 + 1.5 * (seed % 4))


def test_probe_depends_only_on_seed_and_cycle_index() -> None:
    for seed in range(0, 256):
        for ci in range(0, 20):
            p = probe_kw(seed, ci, SCFG)
            assert p in SCFG.probe_grid
            # 与 boundary/state 无关的机械规律：仅由 (seed%5, cycle_index) 决定
            assert p == pytest.approx(
                SCFG.probe_grid[(ci + seed % SCFG.probe_modulus) % SCFG.probe_modulus]
            )


def test_allowed_interval_per_state() -> None:
    assert allowed_interval(LOCKED, 3.0, None, SCFG) == (0.0, 0.0)
    assert allowed_interval(PROTECTIVE, 3.0, 5.0, SCFG) == (-3.0, 0.0)
    assert allowed_interval(NORMAL, 3.0, 5.0, SCFG) == (-3.0, 2.0)
    assert allowed_interval(NORMAL, 3.0, None, SCFG) == (None, None)
    # NORMAL 上界不会为负（boundary 小于 budget → 0）
    assert allowed_interval(NORMAL, 6.0, 2.0, SCFG) == (-6.0, 0.0)


def test_disposition_unique_semantics() -> None:
    assert disposition_of(0.0, -3.0, 2.0) == ACCEPTED
    assert disposition_of(3.0, -3.0, 2.0) == CLIPPED_UPPER
    assert disposition_of(-5.0, -3.0, 2.0) == CLIPPED_LOWER
    assert disposition_of(1.0, None, None) == BOUNDARY_UNAVAILABLE
    assert disposition_of(0.0, 0.0, 0.0) == ACCEPTED


def _mini_cycle() -> pd.DataFrame:
    """4 行 cycle 帧：M4 LOCKED、M3 PROTECTIVE、M3 NORMAL(recovered)、M2 无边界 NORMAL。"""
    return pd.DataFrame(
        {
            "session_id": ["s1"] * 4,
            "cycle_index": [0, 1, 2, 3],
            "info_mode": [M4, M3, M3, M2],
            "application_state": [LOCKED, PROTECTIVE, NORMAL, NORMAL],
            "boundary_value": [np.nan, 5.0, 5.0, np.nan],
        }
    )


def test_build_action_frame_semantics() -> None:
    seed_map = seed_map_for(["s1"])
    out = build_action_frame(_mini_cycle(), SCFG, seed_map)
    assert out["seed_byte"].tolist() == [seed_map["s1"]] * 4
    # budget 只依赖 seed
    assert out["budget"].nunique() == 1

    budget = float(out["budget"].iloc[0])
    # LOCKED → [0,0]
    assert out.loc[0, "L"] == 0.0 and out.loc[0, "U"] == 0.0
    assert out.loc[0, "final_delta"] == 0.0
    # PROTECTIVE → [-budget, 0]
    assert out.loc[1, "L"] == -budget and out.loc[1, "U"] == 0.0
    # NORMAL → [-budget, boundary-budget]（boundary=5.0）
    assert out.loc[2, "U"] == pytest.approx(max(0.0, 5.0 - budget))
    # 无边界 → boundary_unavailable
    assert out.loc[3, "disposition"] == BOUNDARY_UNAVAILABLE
    assert np.isnan(out.loc[3, "final_delta"])

    # 所有有界 cycle：final == clip(request, L, U) 且 disposition 唯一
    assert bool(out["_clip_check"].all())
    for i in range(3):
        req = float(out.loc[i, "requested_delta"])
        L, U = float(out.loc[i, "L"]), float(out.loc[i, "U"])
        assert out.loc[i, "final_delta"] == pytest.approx(min(max(req, L), U))
        expected = ACCEPTED if L <= req <= U else (CLIPPED_UPPER if req > U else CLIPPED_LOWER)
        assert out.loc[i, "disposition"] == expected


def test_build_action_frame_missing_seed_stops() -> None:
    with pytest.raises(RuntimeError, match="未注册 session_id"):
        build_action_frame(_mini_cycle(), SCFG, {"other": 1})


def test_probe_independence_from_boundary() -> None:
    """probe/budget 只依赖 (seed, cycle_index)，与 boundary_value 无关（P0-1 审计）。"""
    seed_map = seed_map_for(["s1"])
    a = build_action_frame(_mini_cycle(), SCFG, seed_map)
    shifted = _mini_cycle().copy()
    shifted["boundary_value"] = shifted["boundary_value"] * 100.0
    b = build_action_frame(shifted, SCFG, seed_map)
    assert a["requested_delta"].tolist() == b["requested_delta"].tolist()
    assert a["budget"].tolist() == b["budget"].tolist()
    assert a["seed_byte"].tolist() == b["seed_byte"].tolist()
