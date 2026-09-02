"""CORE-SEARCH Round 2 配置加载与冻结值校验（fail-closed）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patent_preexperiment.config.yamlutil import load_yaml

_DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "core_search_r2.yaml"


@dataclass(frozen=True)
class R2P0B0Gate:
    """R2-P0-B0 三区门阈值（冻结）。"""

    under_delivery_threshold: float
    closed_under80_max: float
    closed_p10_min: float
    cond_under80_low: float
    cond_under80_high: float
    cond_p10_low: float
    cond_p10_high: float
    open_under80_min: float
    open_p10_max: float
    sensitivity_no_reversal: bool


@dataclass(frozen=True)
class R2P0B0Config:
    primary_max_dev_a: float
    sensitivity_max_dev_a: float
    horizon_min: int
    lag_min: tuple[int, ...]
    clip: tuple[float, float]
    gate: R2P0B0Gate
    results_root: str
    report_path: str


@dataclass(frozen=True)
class R2Config:
    experiment_id: str
    rule_version: str
    r2_a_status: str
    p0_b0: R2P0B0Config
    r2_c_results_root: str
    r2_c_report_path: str


def _require(node: dict[str, Any], key: str) -> Any:
    if key not in node:
        raise ValueError(f"core_search_r2.yaml 缺失关键字段: {key!r}")
    return node[key]


def _parse_gate(gate_raw: dict[str, Any], ud_thr: float) -> R2P0B0Gate:
    closed = dict(_require(gate_raw, "closed"))
    cond = dict(_require(gate_raw, "conditional"))
    open_ = dict(_require(gate_raw, "open"))
    cond_lo, cond_hi = (float(x) for x in _require(cond, "under80_range"))
    p10_lo, p10_hi = (float(x) for x in _require(cond, "p10_range"))
    return R2P0B0Gate(
        under_delivery_threshold=ud_thr,
        closed_under80_max=float(_require(closed, "under80_max")),
        closed_p10_min=float(_require(closed, "p10_min")),
        cond_under80_low=cond_lo,
        cond_under80_high=cond_hi,
        cond_p10_low=p10_lo,
        cond_p10_high=p10_hi,
        open_under80_min=float(_require(open_, "under80_min")),
        open_p10_max=float(_require(open_, "p10_max")),
        sensitivity_no_reversal=bool(_require(gate_raw, "sensitivity_no_reversal")),
    )


def load_r2_config(path: str | Path | None = None) -> R2Config:
    cfg_path = Path(path or _DEFAULT_CONFIG)
    raw = load_yaml(cfg_path)
    experiment_id = str(_require(raw, "experiment_id"))
    if experiment_id != "CORE_SEARCH_R2":
        raise ValueError(f"core_search_r2.yaml experiment_id 漂移: {experiment_id!r}")

    r2a = dict(_require(raw, "r2_a_disposition"))
    r2a_status = str(_require(r2a, "status"))

    p0b = dict(_require(raw, "r2_p0_b0"))
    stab = dict(_require(p0b, "pilot_stability"))
    metrics = dict(_require(p0b, "metrics"))
    clip_raw = metrics.get("response_fraction_clip", [0.0, 2.0])
    gate = _parse_gate(dict(_require(p0b, "gate")), float(metrics["under_delivery_threshold"]))
    out = dict(_require(p0b, "outputs"))
    p0_b0 = R2P0B0Config(
        primary_max_dev_a=float(_require(stab, "primary_max_dev_a")),
        sensitivity_max_dev_a=float(_require(stab, "sensitivity_max_dev_a")),
        horizon_min=int(_require(stab, "horizon_min")),
        lag_min=tuple(int(x) for x in _require(metrics, "response_fraction_lag_min")),
        clip=(float(clip_raw[0]), float(clip_raw[1])),
        gate=gate,
        results_root=str(out["results_root"]),
        report_path=str(out["report"]),
    )

    r2c_out = dict(_require(_require(raw, "r2_c_data_gate"), "outputs"))
    return R2Config(
        experiment_id=experiment_id,
        rule_version=str(raw.get("rule_version", "")),
        r2_a_status=r2a_status,
        p0_b0=p0_b0,
        r2_c_results_root=str(r2c_out["results_root"]),
        r2_c_report_path=str(r2c_out["report"]),
    )
