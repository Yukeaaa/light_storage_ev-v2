"""CORE-SEARCH R3-P0-A 单元测试：净负荷 forecast error 计算。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.r3_p0a_gate import _forecast_error


def test_forecast_error_shift_alignment():
    df = pd.DataFrame({
        "actual_consumption": [10.0, 20.0, 30.0, 40.0],
        "actual_pv": [0.0, 0.0, 0.0, 0.0],
        "load_00": [5.0, 15.0, 25.0, 35.0],
        "pv_00": [0.0, 0.0, 0.0, 0.0],
    })
    # net_actual = [10,20,30,40]; net_forecast = [5,15,25,35]
    # error[t] = net_actual[t+1] - net_forecast[t] = [15,15,15,NaN]
    err = _forecast_error(df, "load_00", "pv_00", lag_steps=1)
    assert np.allclose(err.dropna().to_numpy(), 15.0)
    assert err.isna().sum() == 1  # 最后一行 actual 无 t+1
