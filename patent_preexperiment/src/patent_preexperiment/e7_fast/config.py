"""E7-FAST 配置加载与冻结值校验。

- 加载 `configs/e7_fast.yaml`，把机器可执行的冻结阈值抽取为 typed dataclass。
- 算法只消费本模块暴露的常量，禁止在算法中硬编码冻结数值（AGENTS.md 红线）。
- 信息类别 precedence / Q95 参数复用 P2 冻结 schema（phase3_p2.schema），只读不改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.phase3_p2.schema import SchemaConfig, load_schema

_DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "e7_fast.yaml"
_P2_SCHEMA = Path(__file__).resolve().parents[3] / "configs" / "phase3_p2_action_schema.yaml"


@dataclass(frozen=True)
class PowerGuard:
    actual_kw_min: float
    actual_kw_max: float
    pilot_a_max: float


@dataclass(frozen=True)
class PilotStepRules:
    """自然 pilot 变化事件检测规则（review §5；冻结）。"""

    detection_unit: str          # pilot_a
    record_unit: str             # pilot_power_kw
    pos_delta_a_min: float       # Δpilot >= 2 A
    pos_rel_ratio_min: float     # Δpilot/pilot_before >= 15%
    neg_delta_a_max: float       # Δpilot <= -2 A
    neg_rel_ratio_min: float
    pre_window_min: int
    pre_pilot_no_second_change_a: float
    pre_actual_no_big_jump_kw: float
    post_lag_min: tuple[int, ...]
    first_connect_min: int
    severe_gap_in_window: bool
    non_physical: bool
    offline_done_window_min: int


@dataclass(frozen=True)
class Q95History:
    window_min: int
    quantile: float
    min_samples: int
    min_history_samples: int


@dataclass(frozen=True)
class PositiveGate:
    a_events: int
    a_sessions: int
    a_stations: int
    a_months: int
    b_low: int
    b_high: int
    c_max: int


@dataclass(frozen=True)
class NegativeGate:
    events_min: int
    sessions_min: int
    stations_min: int


@dataclass(frozen=True)
class D0Config:
    info_coverage_path: str
    pilot_step_events_path: str
    evidence_registry_path: str
    report_path: str
    pilot_rules: PilotStepRules
    q95: Q95History
    positive_gate: PositiveGate
    negative_gate: NegativeGate


@dataclass(frozen=True)
class SplitConfig:
    external_only: tuple[str, ...]
    counting_scope: str          # train+validation 为 gate 主判集


@dataclass(frozen=True)
class E7FastConfig:
    experiment_id: str
    rule_version: str
    output_version: str
    config_path: str
    power_guard: PowerGuard
    split: SplitConfig
    d0: D0Config
    p2_schema: SchemaConfig       # 复用 P2 冻结 schema（信息类别 + Q95 参数）
    raw: dict[str, Any] = field(default_factory=dict)


def _require(node: dict[str, Any], key: str) -> Any:
    if key not in node:
        raise ValueError(f"e7_fast.yaml 缺失关键字段: {key!r}")
    return node[key]


def load_e7_fast_config(path: str | Path | None = None) -> E7FastConfig:
    cfg_path = Path(path or _DEFAULT_CONFIG)
    raw = load_yaml(cfg_path)
    experiment_id = str(_require(raw, "experiment_id"))
    if experiment_id != "E7_FAST_v1":
        raise ValueError(f"e7_fast.yaml experiment_id 漂移: {experiment_id!r}")

    power = dict(_require(raw, "power"))
    guard = dict(power.get("non_physical_guard", {}))
    power_guard = PowerGuard(
        actual_kw_min=float(guard["actual_kw_min"]),
        actual_kw_max=float(guard["actual_kw_max"]),
        pilot_a_max=float(guard["pilot_a_max"]),
    )

    split_raw = dict(_require(raw, "split"))
    split_cfg = SplitConfig(
        external_only=tuple(split_raw.get("external_only", [])),
        counting_scope=str(split_raw.get("d0_counting_scope", "")),
    )

    info_raw = dict(_require(raw, "info_class"))
    hist_raw = dict(info_raw.get("q95_history", {}))
    q95 = Q95History(
        window_min=int(hist_raw["window_min"]),
        quantile=float(hist_raw["quantile"]),
        min_samples=int(hist_raw["min_samples"]),
        min_history_samples=int(
            dict(info_raw.get("history_sufficient", {}))["min_history_samples"]
        ),
    )

    d0_raw = dict(_require(raw, "d0"))
    out_raw = dict(d0_raw["outputs"])
    steps_raw = dict(d0_raw["d0_2_pilot_steps"])
    pos_raw = dict(steps_raw["positive_event"])
    neg_raw = dict(steps_raw["negative_event"])
    pre_raw = dict(steps_raw["pre_stability"])
    excl_raw = dict(steps_raw["exclusions"])
    pilot_rules = PilotStepRules(
        detection_unit=str(steps_raw["detection_unit"]),
        record_unit=str(steps_raw["record_unit"]),
        pos_delta_a_min=float(pos_raw["delta_pilot_a_min"]),
        pos_rel_ratio_min=float(pos_raw["relative_ratio_min"]),
        neg_delta_a_max=float(neg_raw["delta_pilot_a_max"]),
        neg_rel_ratio_min=float(neg_raw["relative_ratio_min"]),
        pre_window_min=int(pre_raw["window_min"]),
        pre_pilot_no_second_change_a=float(pre_raw["pilot_no_second_change_a"]),
        pre_actual_no_big_jump_kw=float(pre_raw["actual_no_big_jump_kw"]),
        post_lag_min=tuple(int(x) for x in steps_raw["post_observation_lag_min"]),
        first_connect_min=int(excl_raw["first_connect_min"]),
        severe_gap_in_window=bool(excl_raw["severe_gap_in_window"]),
        non_physical=bool(excl_raw["non_physical_power"]),
        offline_done_window_min=int(excl_raw["offline_done_charging_window_min"]),
    )

    gate_raw = dict(d0_raw["sufficiency_gate"])
    pos_gate_raw = dict(gate_raw["positive_pilot_up"])
    a_raw = dict(pos_gate_raw["A_level"])
    b_raw = dict(pos_gate_raw["B_level"])
    positive_gate = PositiveGate(
        a_events=int(a_raw["usable_events_min"]),
        a_sessions=int(a_raw["unique_sessions_min"]),
        a_stations=int(a_raw["stations_min"]),
        a_months=int(a_raw["months_min"]),
        b_low=int(b_raw["usable_events_range"][0]),
        b_high=int(b_raw["usable_events_range"][1]),
        c_max=int(pos_gate_raw["C_level"]["usable_events_max"]),
    )
    neg_gate_raw = dict(gate_raw["negative_pilot"])
    negative_gate = NegativeGate(
        events_min=int(neg_gate_raw["usable_events_min"]),
        sessions_min=int(neg_gate_raw["unique_sessions_min"]),
        stations_min=int(neg_gate_raw["stations_min"]),
    )

    d0 = D0Config(
        info_coverage_path=str(out_raw["info_coverage"]),
        pilot_step_events_path=str(out_raw["pilot_step_events"]),
        evidence_registry_path=str(out_raw["evidence_registry"]),
        report_path=str(out_raw["report"]),
        pilot_rules=pilot_rules,
        q95=q95,
        positive_gate=positive_gate,
        negative_gate=negative_gate,
    )

    p2_schema = load_schema(_P2_SCHEMA)

    return E7FastConfig(
        experiment_id=experiment_id,
        rule_version=str(raw.get("rule_version", "")),
        output_version=str(raw.get("output_version", "")),
        config_path=str(cfg_path),
        power_guard=power_guard,
        split=split_cfg,
        d0=d0,
        p2_schema=p2_schema,
        raw=raw,
    )
