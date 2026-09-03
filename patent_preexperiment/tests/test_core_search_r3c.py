"""CORE-SEARCH R3-C 单元测试：四臂放电决策 + 共享 BESS 约束。"""

from __future__ import annotations

import numpy as np

from patent_preexperiment.core_search.r3c_system import _dispatch

_E_CAP = 70.95  # Pcap = 283.8 kW × 15min
_SOC = 5.0  # kWh
_PMAX = 100.0
_EMAX = 15.7
_SOC_MIN = 0.1
_SOC_MAX = 0.9
_ETA_DIS = 0.95


def _d(arm: str, p_net: float, m: int = 5, e_used: float = 10.0) -> float:
    r = 15 - m + 1
    return _dispatch(arm, p_net, m, e_used, _E_CAP, r, _SOC, _PMAX, _EMAX,
                     _SOC_MIN, _SOC_MAX, _ETA_DIS)


def test_B0_discharges_full_excess():
    # pcap = 283.8, p_net=300 → d=16.2
    assert np.isclose(_d("B0", 300.0), 300.0 - 283.8)


def test_B1_remaining_budget():
    # allowed_avg = (70.95-10)*60/11 = 332.45；p_net=400 → d≈67.5
    assert np.isclose(_d("B1", 400.0), 400.0 - (70.95 - 10.0) * 60.0 / 11.0)


def test_B2_equals_B1_under_persistence():
    assert np.isclose(_d("B1", 400.0), _d("B2", 400.0))


def test_C_defers_when_no_projected_deficit():
    # deficit = 10 + 300*11/60 - 70.95 < 0 → 无需动作 → d=0
    assert _d("C", 300.0) == 0.0


def test_C_acts_when_deficit_exceeds_future_capacity():
    # deficit = 10 + 500*11/60 - 70.95 ≈ 30.7 > e_avail(≈3.26) → d = min(缺额*60, Pmax)=100
    assert _d("C", 500.0) == 100.0
