"""CORE-SEARCH R3-A 单元测试：reserve 评估口径 / 政策。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.r3a_system import (
    _evaluate,
    _policy_B0,
    _policy_B1,
)


def test_policy_b0_is_q95():
    e = pd.Series([1.0, -2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    # 线性插值 Q95 of [1..10] = 9.55
    assert np.isclose(_policy_B0(e), 9.55)


def test_policy_b1_hour_map():
    e = pd.Series([1.0, 2.0, 3.0, 10.0, 11.0, 12.0])
    hour = pd.Series([0, 0, 0, 1, 1, 1])
    m = _policy_B1(e, hour)
    assert set(m.keys()) == {0, 1}
    assert np.isclose(m[0], 2.9)  # Q95 of [1,2,3] = 2.9 (线性插值)
    assert np.isclose(m[1], 11.9)  # Q95 of [10,11,12]


def test_evaluate_locked_at_95():
    # 完美标定：R 恒等于 |e| → ratio=1 → scale=1, coverage=1
    e = pd.Series([1.0, 2.0, 3.0, 4.0])
    R = pd.Series([1.0, 2.0, 3.0, 4.0])
    r = _evaluate(R, e, dt=0.25)
    assert np.isclose(r["coverage"], 1.0)
    assert np.isclose(r["locked_kwh_at_95"], 1.0 * (1 + 2 + 3 + 4) * 0.25)
    # 欠标定：R 恒小 → 需要放大 → locked 更大
    R_small = pd.Series([0.5, 0.5, 0.5, 0.5])
    r2 = _evaluate(R_small, e, dt=0.25)
    assert r2["scale"] > 1.0
