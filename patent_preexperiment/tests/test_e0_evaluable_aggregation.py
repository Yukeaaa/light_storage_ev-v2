"""E0-Full evaluable 汇总层聚合规则（审查结论7 §9.2；e0_full.yaml evaluable 节）。

规则（冻结）：
- evaluable=False 的记录不得进入均值；
- 其 0.0 值不得被理解为真实事件率为零；
- 不可评估池/月单独报告（含 reason）；
- 报告可评估会话覆盖率；
- 样本不足统一 reason=insufficient_core_sessions（E0F-05 起用，替代临时决定是否保留）。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from patent_preexperiment.config.yamlutil import load_yaml
from tests.test_e0_split import _synth_sessions, assign_split  # 复用 S0 契约参考

_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "e0_full.yaml"


def aggregate_rates(records: pd.DataFrame) -> dict:
    """参考聚合实现。输入列：pool, evaluable, reason, rate。

    Returns:
        dict：mean_rate_evaluable_only（无可评估记录时为 None）、
        evaluable_pools、non_evaluable_pools（含 pool/reason/rate）、evaluable_coverage。
    """
    eligible = records[records["evaluable"].astype(bool)]
    non_eligible = records[~records["evaluable"].astype(bool)]
    mean = float(eligible["rate"].mean()) if len(eligible) else None
    coverage = float(len(eligible) / max(len(records), 1)) if len(records) else 0.0
    return {
        "mean_rate_evaluable_only": mean,
        "evaluable_pools": list(eligible["pool"]),
        "non_evaluable_pools": [
            {"pool": p, "reason": r, "rate": v}
            for p, r, v in zip(
                non_eligible["pool"], non_eligible["reason"], non_eligible["rate"], strict=True
            )
        ],
        "evaluable_coverage": coverage,
    }


def _records(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["pool", "evaluable", "reason", "rate"])


def test_not_evaluable_excluded_from_mean() -> None:
    rec = _records([
        {"pool": "p1", "evaluable": True, "reason": None, "rate": 0.10},
        {"pool": "p2", "evaluable": False, "reason": "no_core_sessions", "rate": 0.0},
    ])
    agg = aggregate_rates(rec)
    assert agg["mean_rate_evaluable_only"] == pytest.approx(0.10, abs=1e-12)
    assert agg["evaluable_pools"] == ["p1"]


def test_zero_not_real_zero() -> None:
    # evaluable=False 的 0.0 不得当作"真实事件率为零"计入
    rec = _records([
        {"pool": "ok", "evaluable": True, "reason": None, "rate": 0.12},
        {"pool": "no_core", "evaluable": False, "reason": "no_core_sessions", "rate": 0.0},
    ])
    agg = aggregate_rates(rec)
    assert agg["mean_rate_evaluable_only"] == pytest.approx(0.12, abs=1e-12)
    ncp = agg["non_evaluable_pools"]
    assert len(ncp) == 1
    assert ncp[0]["pool"] == "no_core" and ncp[0]["reason"] == "no_core_sessions"
    assert ncp[0]["rate"] == 0.0


def test_insufficient_core_sessions_reason_reported() -> None:
    rec = _records([
        {"pool": "thin", "evaluable": False, "reason": "insufficient_core_sessions", "rate": 0.0},
    ])
    agg = aggregate_rates(rec)
    assert agg["mean_rate_evaluable_only"] is None
    assert agg["non_evaluable_pools"][0]["reason"] == "insufficient_core_sessions"


def test_all_not_evaluable_mean_is_none_not_zero() -> None:
    rec = _records([
        {"pool": "a", "evaluable": False, "reason": "no_core_sessions", "rate": 0.0},
        {"pool": "b", "evaluable": False, "reason": "insufficient_core_sessions", "rate": 0.0},
    ])
    agg = aggregate_rates(rec)
    assert agg["mean_rate_evaluable_only"] is None  # 不得回退为 0.0
    assert agg["evaluable_coverage"] == pytest.approx(0.0)


def test_evaluable_coverage_reported() -> None:
    rec = _records([
        {"pool": "a", "evaluable": True, "reason": None, "rate": 0.05},
        {"pool": "b", "evaluable": True, "reason": None, "rate": 0.08},
        {"pool": "c", "evaluable": False, "reason": "no_core_sessions", "rate": 0.0},
    ])
    agg = aggregate_rates(rec)
    assert agg["evaluable_coverage"] == pytest.approx(2 / 3, abs=1e-12)
    assert agg["mean_rate_evaluable_only"] == pytest.approx(0.065, abs=1e-12)


def test_empty_input() -> None:
    rec = _records([])
    agg = aggregate_rates(rec)
    assert agg["mean_rate_evaluable_only"] is None
    assert agg["evaluable_coverage"] == pytest.approx(0.0)
    assert agg["evaluable_pools"] == [] and agg["non_evaluable_pools"] == []


def test_config_matches_aggregation_rules() -> None:
    cfg = load_yaml(_CONFIG)
    ev = cfg["evaluable"]
    assert ev["exclude_not_evaluable_from_mean"] is True
    assert ev["zero_not_real_zero"] is True
    assert ev["report_non_evaluable_separately"] is True
    assert ev["report_evaluable_coverage"] is True


def test_reused_split_contract_runs() -> None:
    # 保证 S0 三个测试文件引用的参考实现可互相协作（切分→按池聚合的完整链路）
    sessions = _synth_sessions(120)
    sessions.loc[[0], "is_external"] = True
    out = assign_split(sessions)
    rec = pd.DataFrame({
        "pool": [
            f"{site}:{sp}" for site, sp in zip(out["site"], out["split"], strict=True)
        ],
        "evaluable": out["split"].isin(["train", "validation", "test"]),
        "reason": out["split"].map(lambda s: None if s in ("train", "validation", "test") else s),
        "rate": [0.1 if s in ("train", "validation", "test") else 0.0 for s in out["split"]],
    })
    agg = aggregate_rates(rec)
    assert agg["evaluable_coverage"] == pytest.approx(119 / 120, abs=1e-12)
    assert len(agg["non_evaluable_pools"]) == 1
