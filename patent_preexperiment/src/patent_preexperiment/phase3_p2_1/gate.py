"""P2.1A A-gate verdict（v1.3 §4.4 / C1）——发明核 falsification 主 Gate。

PASS = 以下六条全部成立（C1 穷尽逻辑：PASS=CI_lower>0，FAIL=CI_lower<=0；NaN 一律 FAIL；
sanity/NI 本就二态）：
  1. CI_lower(Δ(B1)) > 0            Δ(B1)=gain(B0)−gain(B1)（D3 严格优于 persistence）
  2. CI_lower(Δ(B3)) > 0            Δ(B3)=gain(B0)−gain(B3)（D3 严格优于随机匹配）
  3. gain(B0) > gain(B4)            null control sanity（trigger 有意义；正式 PASS 条件）
  4. coverage(B0) >= 0.8 × coverage(B1)   coverage non-inferiority（coverage_ni_factor）
  5. latency(B0) <= latency(B1) + 3       latency non-inferiority（latency_ni_add_cycles）
  6. CI_lower(Δ(B2)) > 0            Δ(B2)=gain(B0)−max[gain(B2a),gain(B2b)]（D3 优于最强 rolling）

Δ(B2) functional：max(gain(B2a), gain(B2b)) 在每个 bootstrap replicate 内取（见 bootstrap.py）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from patent_preexperiment.phase3_p2_1.frozen import FROZEN
from patent_preexperiment.phase3_p2_1.triggers import B0, B1, B4


@dataclass(frozen=True)
class AGateVerdict:
    verdict: str  # "PASS" | "FAIL"
    conditions: dict[str, bool] = field(default_factory=dict)  # 六条各自判定
    condition_details: dict[str, Any] = field(default_factory=dict)  # 每条的数值依据
    failed_conditions: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "conditions": dict(self.conditions),
            "condition_details": self.condition_details,
            "failed_conditions": list(self.failed_conditions),
        }


def a_gate_verdict(
    point: dict[str, Any],
    delta_cis: dict[str, tuple[float, float]],
) -> AGateVerdict:
    """A-gate 判定（6 条件）。point=point_metrics 输出；delta_cis={Δ名: (lo, hi)}。"""
    cov = point["coverage"]
    lat = point["latency"]
    gains = point["gains"]

    ci_b1 = delta_cis.get("delta_b1")
    ci_b3 = delta_cis.get("delta_b3")
    ci_b2 = delta_cis.get("delta_b2")

    c1 = _ci_lower_positive(ci_b1)
    c2 = _ci_lower_positive(ci_b3)
    c3 = _b4_dominance(gains[B0], gains[B4])
    c4 = _coverage_ni(cov[B0], cov[B1])
    c5 = _latency_ni(lat[B0], lat[B1])
    c6 = _ci_lower_positive(ci_b2)

    conditions = {
        "c1_delta_b1": c1,
        "c2_delta_b3": c2,
        "c3_b4_dominance": c3,
        "c4_coverage_ni": c4,
        "c5_latency_ni": c5,
        "c6_delta_b2": c6,
    }
    failed = tuple(name for name, ok in conditions.items() if not ok)
    verdict = "PASS" if not failed else "FAIL"

    return AGateVerdict(
        verdict=verdict,
        conditions=conditions,
        condition_details={
            "c1_delta_b1": {"ci_lower": _ci_lo(ci_b1), "ci_upper": _ci_hi(ci_b1)},
            "c2_delta_b3": {"ci_lower": _ci_lo(ci_b3), "ci_upper": _ci_hi(ci_b3)},
            "c3_b4_dominance": {
                "gain_b0": gains[B0], "gain_b4": gains[B4], "holds": c3,
            },
            "c4_coverage_ni": {
                "coverage_b0": cov[B0], "coverage_b1": cov[B1],
                "required": FROZEN.coverage_ni_factor * cov[B1],
                "ni_factor": FROZEN.coverage_ni_factor,
            },
            "c5_latency_ni": {
                "latency_b0": lat[B0], "latency_b1": lat[B1],
                "allowed": lat[B1] + FROZEN.latency_ni_add_cycles,
                "add_cycles": FROZEN.latency_ni_add_cycles,
            },
            "c6_delta_b2": {"ci_lower": _ci_lo(ci_b2), "ci_upper": _ci_hi(ci_b2)},
        },
        failed_conditions=failed,
    )


def _ci_lower_positive(ci: tuple[float, float] | None) -> bool:
    if ci is None:
        return False
    lo, _hi = ci
    return bool(np.isfinite(lo)) and lo > 0.0


def _ci_lo(ci: tuple[float, float] | None) -> float | None:
    return ci[0] if ci is not None else None


def _ci_hi(ci: tuple[float, float] | None) -> float | None:
    return ci[1] if ci is not None else None


def _b4_dominance(gain_b0: float, gain_b4: float) -> bool:
    if not (np.isfinite(gain_b0) and np.isfinite(gain_b4)):
        return False
    return bool(gain_b0 > gain_b4)


def _coverage_ni(cov_b0: float, cov_b1: float) -> bool:
    if not (np.isfinite(cov_b0) and np.isfinite(cov_b1)):
        return False
    return bool(cov_b0 >= FROZEN.coverage_ni_factor * cov_b1)


def _latency_ni(lat_b0: float, lat_b1: float) -> bool:
    if not (np.isfinite(lat_b0) and np.isfinite(lat_b1)):
        return False
    return bool(lat_b0 <= lat_b1 + FROZEN.latency_ni_add_cycles)
