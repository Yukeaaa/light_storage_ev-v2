"""CORE-PATENT SEARCH P0-B 单元测试：柔性口径 / 分池量纲汇总 / 量纲门。

用合成控制池验证逻辑正确性（不依赖外部数据）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.config import P0BConfig, P0BGate
from patent_preexperiment.core_search.p0b_flex import (
    compute_pool_flexibility,
    evaluate_p0b_gate,
    summarize_flex_scale,
)


def _make_pool(
    n: int,
    *,
    actual: list[float] | None = None,
    pilot: list[float] | None = None,
    coverage: list[float] | None = None,
    sites: list[str] | None = None,
) -> pd.DataFrame:
    actual = actual or [50.0] * n
    pilot = pilot or [70.0] * n
    coverage = coverage or [1.0] * n
    sites = sites or ["caltech"] * n
    return pd.DataFrame({
        "pool_id": [f"p{i}" for i in range(n)],
        "site": sites,
        "garage": ["California_Garage_01"] * n,
        "timestamp_utc": pd.date_range("2020-06-01", periods=n, freq="5min", tz="UTC"),
        "n_active": [5.0] * n,
        "n_matched": [5.0] * n,
        "n_charging": [5.0] * n,
        "actual_power_kw_total": actual,
        "pilot_upper_kw_total": pilot,
        "pilot_coverage": coverage,
    })


def test_compute_pool_flexibility_headroom_and_down():
    pool = _make_pool(2, actual=[50.0, 60.0], pilot=[70.0, 55.0])
    flex = compute_pool_flexibility(pool, r_down=0.6)
    assert np.allclose(flex["flex_up_f0_kw"], [20.0, 0.0])  # headroom clip 0
    assert np.allclose(flex["flex_down_reliable_kw"], [30.0, 36.0])  # actual*0.6
    assert np.allclose(flex["flex_up_f3_kw"], [0.0, 0.0])
    assert flex["hour"].iloc[0] == 0
    assert flex["month"].iloc[0] == "2020-06"


def test_summarize_flex_scale_per_site():
    pool = _make_pool(
        4,
        actual=[10.0, 100.0, 20.0, 40.0],
        pilot=[10.0, 150.0, 20.0, 40.0],
        sites=["caltech", "caltech", "jpl", "jpl"],
    )
    flex = compute_pool_flexibility(pool, r_down=0.5)
    summ = summarize_flex_scale(flex)
    assert set(summ["site"]) == {"caltech", "jpl"}
    cal = summ[summ["site"] == "caltech"].iloc[0]
    assert cal["ev_peak_kw"] == 100.0
    assert cal["flex_up_f0_peak_kw"] == 50.0  # 150-100
    assert cal["flex_down_reliable_peak_kw"] == 50.0  # 100*0.5
    assert cal["flex_to_ev_peak_ratio"] == 0.5


def _gate_cfg(go_min: float = 100.0) -> P0BConfig:
    return P0BConfig(
        tiers=(),
        gate=P0BGate(
            bess_comparison_kw_low=100.0,
            bess_comparison_kw_high=200.0,
            go_reliable_flex_peak_min_kw=go_min,
        ),
        results_root="results/raw/core_search/p0_b",
        report_path="reports/core_search/CORE_P0_B_EV_FLEX_SCALE.md",
        counting_scope="train+validation",
    )


def test_gate_go_when_reliable_flex_reaches_bess_low():
    pool = _make_pool(2, actual=[100.0, 300.0], pilot=[100.0, 300.0])
    flex = compute_pool_flexibility(pool, r_down=0.6)  # peak down = 300*0.6 = 180
    summ = summarize_flex_scale(flex)
    v = evaluate_p0b_gate(summ, _gate_cfg(), r_down=0.6)
    assert v.verdict == "GO"
    assert v.flex_down_reliable_peak_kw == 180.0


def test_gate_no_go_when_reliable_flex_below_bess_low():
    pool = _make_pool(2, actual=[50.0, 100.0], pilot=[50.0, 100.0])
    flex = compute_pool_flexibility(pool, r_down=0.5)  # peak down = 100*0.5 = 50
    summ = summarize_flex_scale(flex)
    v = evaluate_p0b_gate(summ, _gate_cfg(), r_down=0.5)
    assert v.verdict == "NO_GO"
    assert v.flex_down_reliable_peak_kw == 50.0
