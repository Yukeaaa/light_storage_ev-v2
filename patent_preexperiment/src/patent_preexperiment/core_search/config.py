"""CORE-PATENT SEARCH 配置加载与冻结值校验。

加载 `configs/core_search_v1.yaml`，把机器可执行的冻结阈值抽取为 typed dataclass。
算法只消费本模块暴露的常量，禁止在算法中硬编码冻结数值（AGENTS.md 红线）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from patent_preexperiment.config.yamlutil import load_yaml

_DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "core_search_v1.yaml"


@dataclass(frozen=True)
class PowerGuard:
    actual_kw_min: float
    actual_kw_max: float
    pilot_a_max: float


@dataclass(frozen=True)
class RatedVoltage:
    jpl: float
    caltech: float
    office001: float


@dataclass(frozen=True)
class SplitConfig:
    rule: str
    external_only: tuple[str, ...]
    stress_only: tuple[str, ...]


@dataclass(frozen=True)
class BindingRules:
    """binding/non-binding 事件分类规则（P0-A 核心；review §五）。"""

    tolerance_kw: float

    def is_binding_decrease(self, pilot_after_kw: float, actual_before_kw: float) -> bool:
        return pilot_after_kw < actual_before_kw - self.tolerance_kw

    def is_binding_increase(self, pilot_after_kw: float, actual_before_kw: float) -> bool:
        return pilot_after_kw > actual_before_kw + self.tolerance_kw


@dataclass(frozen=True)
class ResponseLagRules:
    lag_min: tuple[int, ...]
    fraction_clip_low: float
    fraction_clip_high: float


@dataclass(frozen=True)
class P0AGate:
    """P0-A 判断门阈值（train+validation 主判集）。"""

    usable_events_min: int
    unique_sessions_min: int
    stations_min: int
    months_min: int
    no_go_1m_full_response_median: float
    no_go_1m_full_response_std: float
    time_dynamic_diff_threshold: float
    heterogeneity_iqr_threshold: float
    repeatability_corr_threshold: float


@dataclass(frozen=True)
class P0AConfig:
    binding: BindingRules
    response: ResponseLagRules
    gate: P0AGate
    results_root: str
    report_path: str
    counting_scope: str


@dataclass(frozen=True)
class FlexTier:
    name: str
    definition: str


@dataclass(frozen=True)
class P0BGate:
    """P0-B 量纲门阈值（结构化冻结，禁止硬编码）。"""

    bess_comparison_kw_low: float
    bess_comparison_kw_high: float
    go_reliable_flex_peak_min_kw: float


@dataclass(frozen=True)
class P0BConfig:
    tiers: tuple[FlexTier, ...]
    gate: P0BGate
    results_root: str
    report_path: str
    counting_scope: str


@dataclass(frozen=True)
class SystemKpiThresholds:
    dead_pct_max: float
    engineering_minor_low: float
    engineering_minor_high: float
    observe_low: float
    observe_high: float
    worth_deep_low: float
    worth_deep_high: float
    strong_core_candidate_min: float


@dataclass(frozen=True)
class CoreSearchConfig:
    experiment_id: str
    rule_version: str
    config_path: str
    frozen_date: str
    system_kpi_thresholds: SystemKpiThresholds
    power_guard: PowerGuard
    rated_voltage: RatedVoltage
    split: SplitConfig
    p0_a: P0AConfig
    p0_b: P0BConfig
    raw: dict[str, Any] = field(default_factory=dict)


def _require(node: dict[str, Any], key: str) -> Any:
    if key not in node:
        raise ValueError(f"core_search_v1.yaml 缺失关键字段: {key!r}")
    return node[key]


def load_core_search_config(path: str | Path | None = None) -> CoreSearchConfig:
    cfg_path = Path(path or _DEFAULT_CONFIG)
    raw = load_yaml(cfg_path)
    experiment_id = str(_require(raw, "experiment_id"))
    if experiment_id != "CORE_SEARCH_v1":
        raise ValueError(f"core_search_v1.yaml experiment_id 漂移: {experiment_id!r}")

    power = dict(_require(dict(_require(raw, "data")), "power"))
    guard_raw = dict(power.get("non_physical_guard", {}))
    power_guard = PowerGuard(
        actual_kw_min=float(guard_raw["actual_kw_min"]),
        actual_kw_max=float(guard_raw["actual_kw_max"]),
        pilot_a_max=float(guard_raw["pilot_a_max"]),
    )
    rv_raw = dict(power.get("rated_voltage", {}))
    rated_voltage = RatedVoltage(
        jpl=float(rv_raw["jpl"]),
        caltech=float(rv_raw["caltech"]),
        office001=float(rv_raw["office001"]),
    )

    split_raw = dict(_require(raw, "split"))
    split_cfg = SplitConfig(
        rule=str(split_raw.get("rule", "")),
        external_only=tuple(split_raw.get("external_only", [])),
        stress_only=tuple(split_raw.get("stress_only", [])),
    )

    kpi_raw = dict(_require(raw, "system_kpi_thresholds"))
    system_kpi = SystemKpiThresholds(
        dead_pct_max=float(kpi_raw["dead_pct_max"]),
        engineering_minor_low=float(kpi_raw["engineering_minor_pct_range"][0]),
        engineering_minor_high=float(kpi_raw["engineering_minor_pct_range"][1]),
        observe_low=float(kpi_raw["observe_pct_range"][0]),
        observe_high=float(kpi_raw["observe_pct_range"][1]),
        worth_deep_low=float(kpi_raw["worth_deep_pct_range"][0]),
        worth_deep_high=float(kpi_raw["worth_deep_pct_range"][1]),
        strong_core_candidate_min=float(kpi_raw["strong_core_candidate_pct_min"]),
    )

    p0a_raw = dict(_require(raw, "p0_a_ev_response"))
    binding_raw = dict(p0a_raw["binding_classification"])
    binding = BindingRules(tolerance_kw=float(binding_raw["tolerance_kw"]))
    lag_list = p0a_raw["response_lag_min"]
    clip_raw = p0a_raw.get("fraction_clip", "[0, 2]")
    clip_lo, clip_hi = _parse_clip(clip_raw)
    response = ResponseLagRules(
        lag_min=tuple(int(x) for x in lag_list),
        fraction_clip_low=clip_lo,
        fraction_clip_high=clip_hi,
    )
    gate_raw = p0a_raw.get("gate", {})
    p0a_gate = _parse_p0a_gate(gate_raw)
    p0a_out = dict(p0a_raw["outputs"])
    p0_a = P0AConfig(
        binding=binding,
        response=response,
        gate=p0a_gate,
        results_root=str(p0a_out["results_root"]),
        report_path=str(p0a_out["report"]),
        counting_scope="train+validation",
    )

    p0b_raw = dict(_require(raw, "p0_b_ev_flex_scale"))
    tiers_raw = dict(p0b_raw["flex_tiers"])
    tiers = tuple(
        FlexTier(name=name, definition=str(t["definition"]))
        for name, t in tiers_raw.items()
        if isinstance(t, dict) and "definition" in t
    )
    p0b_out = dict(_require(p0b_raw, "outputs"))
    p0_b = P0BConfig(
        tiers=tiers,
        gate=_parse_p0b_gate(dict(_require(p0b_raw, "gate"))),
        results_root=str(p0b_out["results_root"]),
        report_path=str(p0b_out["report"]),
        counting_scope="train+validation",
    )

    return CoreSearchConfig(
        experiment_id=experiment_id,
        rule_version=str(raw.get("rule_version", "")),
        config_path=str(cfg_path),
        frozen_date=str(raw.get("frozen_date", "")),
        system_kpi_thresholds=system_kpi,
        power_guard=power_guard,
        rated_voltage=rated_voltage,
        split=split_cfg,
        p0_a=p0_a,
        p0_b=p0_b,
        raw=raw,
    )


def _parse_clip(clip: Any) -> tuple[float, float]:
    if isinstance(clip, str):
        # strip inline comments (e.g. "[0, 2]   # 诊断")
        cleaned = clip.split("#", 1)[0].strip().strip("[]()")
        parts = [p.strip() for p in cleaned.split(",")]
        return float(parts[0]), float(parts[1])
    if isinstance(clip, list):
        return float(clip[0]), float(clip[1])
    return 0.0, 2.0


def _parse_p0a_gate(gate_raw: dict[str, Any]) -> P0AGate:
    """从结构化字段读取 P0-A 门阈值；缺失即抛错（fail-closed，禁止硬编码回退）。"""
    sufficiency = dict(_require(gate_raw, "sufficiency"))
    no_go_1m = dict(_require(gate_raw, "no_go_deterministic_1m"))
    return P0AGate(
        usable_events_min=int(_require(sufficiency, "usable_events_min")),
        unique_sessions_min=int(_require(sufficiency, "unique_sessions_min")),
        stations_min=int(_require(sufficiency, "stations_min")),
        months_min=int(_require(sufficiency, "months_min")),
        no_go_1m_full_response_median=float(
            _require(no_go_1m, "full_response_median_min")
        ),
        no_go_1m_full_response_std=float(_require(no_go_1m, "full_response_std_max")),
        time_dynamic_diff_threshold=float(
            _require(gate_raw, "time_dynamic_diff_threshold")
        ),
        heterogeneity_iqr_threshold=float(
            _require(gate_raw, "heterogeneity_iqr_threshold")
        ),
        repeatability_corr_threshold=float(
            _require(gate_raw, "repeatability_corr_threshold")
        ),
    )


def _parse_p0b_gate(gate_raw: dict[str, Any]) -> P0BGate:
    """从结构化字段读取 P0-B 量纲门阈值；缺失即抛错。"""
    return P0BGate(
        bess_comparison_kw_low=float(_require(gate_raw, "bess_comparison_kw_low")),
        bess_comparison_kw_high=float(_require(gate_raw, "bess_comparison_kw_high")),
        go_reliable_flex_peak_min_kw=float(
            _require(gate_raw, "go_reliable_flex_peak_min_kw")
        ),
    )
