"""CORE-SEARCH R3-C0 单元测试：窗口分类 + m_unavoidable。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.r3_c0_gate import (
    _classify,
    _m_unavoidable_per_window,
)


def test_classify_false_alarm_and_violation():
    w = pd.DataFrame({
        "mean_kw": [90.0, 110.0],
        "max_kw": [105.0, 115.0],
    })
    out = _classify(w, pcap=100.0)
    assert bool(out["trigger"].iloc[0]) is True
    assert bool(out["false_alarm"].iloc[0]) is True  # max>pcap 但 mean<=pcap
    assert bool(out["violation"].iloc[1]) is True


def test_m_unavoidable_constant_load():
    idx = pd.date_range("2019-01-01", periods=15, freq="1min", tz="UTC")
    load = pd.Series(100.0, index=idx)  # 恒 100 kW
    windows = pd.DataFrame({"violation": [True]}, index=[idx[0]])
    m = _m_unavoidable_per_window(load, windows, pcap=80.0, length_min=15)
    # E_cap = 80*15/60 = 20 kWh；累计 100*m/60 > 20 → m > 12 → m=13
    assert np.isclose(m.iloc[0], 13.0)
