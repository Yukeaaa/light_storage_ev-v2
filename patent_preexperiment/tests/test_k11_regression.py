"""K1.1-E 最小回归测试：泄漏不变性 / 单位 / 机会能量 / mask 一致 / done 分层 / 确定性。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patent_preexperiment.allocation.opportunity import (
    CYCLE_MIN,
    available_mask,
    build_cycle_table,
)
from patent_preexperiment.response.done import (
    PHASE_CORE,
    PHASE_MISSING,
    PHASE_POST,
    PHASE_TAIL,
    add_done_phases,
    infer_done,
    phase_for_minutes,
)


def _synth_minutes() -> pd.DataFrame:
    """两个会话、同一池、12 个 5min 周期（60 分钟）。A pilot=6kW actual≈3；B pilot=4 actual≈2。"""
    idx = pd.date_range("2018-11-01 10:00", periods=60, freq="min")
    rows = []
    for sess, pilot, actual in [("A", 6.0, 3.0), ("B", 4.0, 2.0)]:
        df = pd.DataFrame(
            {
                "session_id": sess,
                "station_id": f"st_{sess}",
                "site": "caltech",
                "garage": "CG1",
                "timestamp_utc": idx,
                "actual_power_kw": float(actual),
                "pilot_power_kw": float(pilot),
                "pilot_available": True,
                "pilot_present": 1.0,
            }
        )
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


def _cycle_start(dt: pd.Timestamp) -> pd.Timestamp:
    return dt.floor(f"{CYCLE_MIN}min")


@pytest.fixture()
def synth() -> pd.DataFrame:
    return _synth_minutes()


def test_no_leakage_current_cycle_perturbation(synth: pd.DataFrame) -> None:
    """硬测试：修改当前控制周期的实际功率，当前周期预算代理/历史上界/headroom 不得变化。"""
    cyc0, prox0 = build_cycle_table(synth)
    target_start = pd.Timestamp("2018-11-01 10:30")

    def row(cand: pd.DataFrame, sess: str, start: pd.Timestamp) -> pd.Series:
        c = cand[(cand["cycle"] == start) & (cand["session_id"] == sess)]
        assert len(c) == 1
        return c.iloc[0]

    b0 = row(prox0, "A", target_start)
    for col in ("A0_avg", "A1_pilot", "A2_prev_actual", "A3_rolling_quantile",
                "A4_min_pilot_quantile", "actual_rollmax", "actual_rollq"):
        assert pd.notna(b0[col]), f"{col} 在目标周期应有值"

    df2 = synth.copy()
    mask = (
        (df2["session_id"] == "A")
        & (df2["timestamp_utc"] >= target_start)
        & (df2["timestamp_utc"] < target_start + pd.Timedelta(f"{CYCLE_MIN}min"))
    )
    df2.loc[mask, "actual_power_kw"] += 1.5
    _, prox1 = build_cycle_table(df2)
    b1 = row(prox1, "A", target_start)

    for col in ("A0_avg", "A1_pilot", "A2_prev_actual", "A3_rolling_quantile",
                "A4_min_pilot_quantile", "actual_rollmax", "actual_rollq"):
        assert b0[col] == pytest.approx(b1[col], abs=1e-9), f"当前周期扰动改变了 {col}"

    head0 = b0["actual_rollmax"] - b0["A0_avg"]
    head1 = b1["actual_rollmax"] - b1["A0_avg"]
    assert head0 == pytest.approx(head1, abs=1e-9), "headroom 不应受当前周期扰动影响"


def test_perturbation_propagates_to_next_cycle(synth: pd.DataFrame) -> None:
    """当前周期扰动应只影响下一周期的 actual_prev（检验滞后方向正确）。"""
    target_start = pd.Timestamp("2018-11-01 10:30")
    df2 = synth.copy()
    mask = (
        (df2["session_id"] == "A")
        & (df2["timestamp_utc"] >= target_start)
        & (df2["timestamp_utc"] < target_start + pd.Timedelta(f"{CYCLE_MIN}min"))
    )
    df2.loc[mask, "actual_power_kw"] += 1.5
    _, prox1 = build_cycle_table(df2)
    nxt = target_start + pd.Timedelta(f"{CYCLE_MIN}min")
    c = prox1[(prox1["cycle"] == nxt) & (prox1["session_id"] == "A")]
    assert len(c) == 1
    assert c.iloc[0]["A2_prev_actual"] == pytest.approx(3.0 + 1.5, abs=1e-9)


def test_kw_min_to_kwh_conversion(synth: pd.DataFrame) -> None:
    """单位测试：候选能量(kWh) = 预算差值(kW) × 周期/60；非候选周期=0。"""
    cyc_level, _ = build_cycle_table(synth)
    slack = cyc_level["slack_A0_avg_kwh"] * CYCLE_MIN / 60.0
    expected = slack.where(cyc_level["candidate_A0_avg"], 0.0)
    np.testing.assert_allclose(
        cyc_level["candidate_energy_A0_avg_kwh"].to_numpy(), expected.to_numpy(), atol=1e-9
    )


def test_candidate_energy_zero_when_not_candidate(synth: pd.DataFrame) -> None:
    """不满足机会条件时机会能量必须为 0。"""
    cyc_level, _ = build_cycle_table(synth)
    all_proxies = ("A0_avg", "A1_pilot", "A2_prev_actual",
                   "A3_rolling_quantile", "A4_min_pilot_quantile")
    for p in all_proxies:
        non = cyc_level[~cyc_level[f"candidate_{p}"]]
        if len(non):
            assert (non[f"candidate_energy_{p}_kwh"] == 0).all(), f"{p}: 非候选周期能量应=0"


def test_available_mask_paired_consistency(synth: pd.DataFrame) -> None:
    """基线比较 eligible mask 一致：组内各代理在完全相同周期上评估。"""
    cyc_level, _ = build_cycle_table(synth)
    mask_prox = ["A0_avg", "A2_prev_actual",
                 "A3_rolling_quantile", "A4_min_pilot_quantile"]
    cal_mask = available_mask(cyc_level, "caltech.CG1", mask_prox)
    sub = cyc_level[cal_mask]
    assert len(sub) >= 1
    for p in ("A0_avg", "A2_prev_actual", "A3_rolling_quantile", "A4_min_pilot_quantile"):
        assert (sub[f"n_budget_{p}"] >= 1).all(), f"{p} 在配对集内必须全部可计算"
    # 同组内各代理候选率在同一周期集合上计算
    rates = {p: sub[f"candidate_{p}"].mean() for p in
             ("A0_avg", "A2_prev_actual", "A3_rolling_quantile", "A4_min_pilot_quantile")}
    assert all(0.0 <= v <= 1.0 for v in rates.values())


def test_post_done_not_in_core_run_segment(synth: pd.DataFrame) -> None:
    """done 之后不能进入核心运行段。"""
    df = synth.copy()
    df["done_charging_time"] = pd.Timestamp("2018-11-01 10:50")
    df["minutes_from_end"] = 60.0
    out = add_done_phases(df, p_on_kw=0.5)
    post = out[out["timestamp_utc"] > pd.Timestamp("2018-11-01 10:50")]
    assert len(post) > 0
    assert (post["phase"] == PHASE_POST).all(), "done 后分钟必须标为 post_done"


def test_done_relative_windows_layered(synth: pd.DataFrame) -> None:
    """done 前不同窗口分层正确：>120 core；30–120 mid；0–30 tail；缺失→missing。"""
    assert phase_for_minutes(200.0) == PHASE_CORE
    assert phase_for_minutes(120.0) == "pre_done_mid"
    assert phase_for_minutes(60.0) == "pre_done_mid"
    assert phase_for_minutes(30.0) == PHASE_TAIL
    assert phase_for_minutes(10.0) == PHASE_TAIL
    assert phase_for_minutes(-5.0) == PHASE_POST
    assert phase_for_minutes(None) == PHASE_MISSING


def test_infer_done_anchor(synth: pd.DataFrame) -> None:
    """离线完成锚点推断：功率<0.3kW 持续20min 且不恢复 → 推断 done。"""
    idx = pd.date_range("2018-11-01 10:00", periods=60, freq="min")
    actual = [3.0] * 20 + [0.8] * 10 + [0.2] * 30  # 20min 工作 + 10min 降流 + 30min 低功率
    df = pd.DataFrame({"timestamp_utc": idx, "actual_power_kw": actual})
    d = infer_done(df, p_on_kw=0.5)
    assert d == pd.Timestamp("2018-11-01 10:30")  # 第一个持续低功率(<0.3kW,20min)窗口起点


def test_infer_done_recovering_not_flagged(synth: pd.DataFrame) -> None:
    """低功率后恢复工作功率：不得推断为完成（避免把暂停当完成）。"""
    idx = pd.date_range("2018-11-01 10:00", periods=60, freq="min")
    actual = [3.0] * 20 + [0.2] * 15 + [2.5] * 25
    df = pd.DataFrame({"timestamp_utc": idx, "actual_power_kw": actual})
    d = infer_done(df, p_on_kw=0.5)
    assert d is None


def test_determinism_build_cycles(synth: pd.DataFrame) -> None:
    """同一配置重复运行结果一致。"""
    c0, p0 = build_cycle_table(synth)
    c1, p1 = build_cycle_table(synth)
    pd.testing.assert_frame_equal(c0, c1)
    pd.testing.assert_frame_equal(p0, p1)
