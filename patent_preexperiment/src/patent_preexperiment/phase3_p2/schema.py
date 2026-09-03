"""冻结 schema 加载与校验（P2 v1.0.2）。

- 直接加载 `configs/phase3_p2_action_schema.yaml`，把机器可执行字段抽取为
  `SchemaConfig`；算法只消费本模块暴露的常量，禁止在算法中硬编码冻结数值。
- 冻结字段校验：`experiment_id` / `protocol_version` / `gate2_verdict` / `scope`
  必须与 v1.0.2 一致，任何漂移 → fail-closed。
- 字符串型数值（budget 规则 / probe 网格 / recovery 条件）用机器解析，解析失败即报错，
  防止"冻结数值只存在于注释"。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from patent_preexperiment.config.yamlutil import load_yaml

M1 = "M1_capability_rich"
M2 = "M2_pilot_actual"
M3 = "M3_current_only"
M4 = "M4_history_insufficient"

LOCKED = "LOCKED"
PROTECTIVE = "PROTECTIVE"
NORMAL = "NORMAL"

_INFO_MODES = (M1, M2, M3, M4)
_APPLICATION_STATES = (LOCKED, PROTECTIVE, NORMAL)

_EXPECTED_EXPERIMENT_ID = "P2_v1_0_2"
_EXPECTED_PROTOCOL = "phase3_p2_preregistration_v1.0.2"
_EXPECTED_GATE2 = "NARROW_CONDITIONAL_GO"
_EXPECTED_SCOPE = "mechanism_realizability_only"


@dataclass(frozen=True)
class SchemaConfig:
    """P2 v1.0.2 机器可执行冻结配置（从 YAML 抽取后校验）。"""

    experiment_id: str
    protocol_version: str
    gate2_verdict: str
    scope: str
    schema_path: str

    # D1 precedence（结构化机器可执行条目；实现直接加载，禁止二次解释文字）
    precedence: tuple[tuple[str, str | None], ...] = field(default_factory=tuple)
    # precedence 中每条 rule 的 mode（if 命中 / else fail_closed）
    fail_closed_mode: str = M4

    layer2_boundary_modes: dict[str, str] = field(default_factory=dict)
    default_application_state: dict[str, str] = field(default_factory=dict)

    min_history_samples: int = 5
    history_window_min: int = 15
    history_quantile: float = 0.95
    history_min_samples: int = 5

    injection_value_kw: float = 7.2

    budget_base_kw: float = 3.0
    budget_step_kw: float = 1.5
    budget_modulus: int = 4
    probe_grid: tuple[float, ...] = (-3.0, -1.5, 0.0, 1.5, 3.0)
    probe_modulus: int = 5

    recovery_ratio: float = 0.95
    recovery_sustained_cycles: int = 3

    m1_target: float = 1.0
    m2_target: float = 1.0
    m4_target: float = 0.0
    m3_min_traces: int = 20
    m3_min_sessions: int = 5

    sentinel_name: str = "p2_sentinel.json"

    # 原始 schema dict（供 manifest / 审计引用；不参与算法）
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def info_modes(self) -> tuple[str, ...]:
        return _INFO_MODES

    @property
    def application_states(self) -> tuple[str, ...]:
        return _APPLICATION_STATES


def _expect_key(node: Any, key: str) -> Any:
    if not isinstance(node, dict) or key not in node:
        raise ValueError(f"P2 schema 缺失关键字段: {key!r}")
    return node[key]


def _parse_probe_grid(rule: str) -> tuple[float, ...]:
    m = re.search(r"probe_grid=\[(?P<items>[^\]]+)\]", rule)
    if not m:
        raise ValueError(f"P2 schema probe 规则无法解析: {rule!r}")
    items = [x.strip() for x in m.group("items").split(",") if x.strip()]
    if not items:
        raise ValueError(f"P2 schema probe 网格为空: {rule!r}")
    return tuple(float(ast.literal_eval(x)) for x in items)


def _parse_budget_rule(rule: str) -> tuple[float, float, int]:
    m = re.search(r"=\s*([0-9.]+)\s*\+\s*([0-9.]+)\s*\*.*mod\s*(\d+)", rule)
    if not m:
        raise ValueError(f"P2 schema budget 规则无法解析: {rule!r}")
    return float(m.group(1)), float(m.group(2)), int(m.group(3))


def _parse_recovery_ratio(condition: str) -> float:
    m = re.search(r"actual_power_kw\s*>=\s*([0-9.]+)\s*\*\s*protective_bound", condition)
    if not m:
        raise ValueError(f"P2 schema recovery 条件无法解析: {condition!r}")
    if "protective_bound > 0" not in condition:
        raise ValueError(f"P2 schema recovery 条件缺少 protective_bound>0 守卫: {condition!r}")
    return float(m.group(1))


def _parse_precedence(node: Any) -> tuple[tuple[str, str | None], ...]:
    precedence = _expect_key(node, "precedence")
    if not isinstance(precedence, list) or not precedence:
        raise ValueError("P2 schema d1_lookup.precedence 必须是非空列表")
    parsed: list[tuple[str, str | None]] = []
    has_else = False
    for idx, rule in enumerate(precedence):
        if not isinstance(rule, dict):
            raise ValueError(f"P2 schema precedence 第 {idx + 1} 条不是 dict")
        cond = rule.get("if")
        mode = rule.get("mode")
        if cond is not None and "else" in rule:
            raise ValueError(f"P2 schema precedence 第 {idx + 1} 条同时含 if 与 else")
        if cond is not None:
            if not isinstance(cond, str) or not isinstance(mode, str):
                raise ValueError(f"P2 schema precedence 第 {idx + 1} 条 if/mode 类型错误")
            parsed.append((cond, mode))
        elif "else" in rule:
            if not isinstance(mode, str):
                raise ValueError(f"P2 schema precedence 第 {idx + 1} 条 else.mode 类型错误")
            parsed.append(("else", mode))
            has_else = True
        else:
            raise ValueError(f"P2 schema precedence 第 {idx + 1} 条必须含 if 或 else")
    if not has_else or parsed[-1][0] != "else":
        raise ValueError("P2 schema precedence 最后一条必须是 else fail_closed 兜底")
    return tuple(parsed)


def _validate_precedence_vars(precedence: tuple[tuple[str, str | None], ...]) -> None:
    """用 ast 校验 if 表达式只引用四个信息变量，防止 schema 漂移成任意代码。"""
    allowed = frozenset(
        {"capability_available", "pilot_available", "actual_available", "history_sufficient"}
    )

    def _check(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            if node.id in ("true", "false"):
                return
            if node.id not in allowed:
                raise ValueError(f"P2 schema precedence 引用不允许的变量: {node.id!r}")
            return
        if isinstance(node, ast.BoolOp):
            for v in node.values:
                _check(v)
            return
        if isinstance(node, ast.UnaryOp):
            _check(node.operand)
            return
        if isinstance(node, ast.Compare):
            _check(node.left)
            for c in node.comparators:
                _check(c)
            return
        if isinstance(node, ast.Constant):
            return
        raise ValueError(f"P2 schema precedence 不支持的语法: {ast.dump(node)}")

    for cond, _mode in precedence:
        if cond == "else":
            continue
        tree = ast.parse(cond, mode="eval")
        _check(tree.body)


def load_schema(path: str | Path) -> SchemaConfig:
    raw = load_yaml(path)
    experiment_id = str(_expect_key(raw, "experiment_id"))
    protocol_version = str(_expect_key(raw, "protocol_version"))
    gate2_verdict = str(_expect_key(raw, "gate2_verdict"))
    scope = str(_expect_key(raw, "scope"))
    if experiment_id != _EXPECTED_EXPERIMENT_ID:
        raise ValueError(
            f"P2 schema experiment_id 漂移: {experiment_id!r} != {_EXPECTED_EXPERIMENT_ID!r}"
        )
    if protocol_version != _EXPECTED_PROTOCOL:
        raise ValueError(
            f"P2 schema protocol_version 漂移: {protocol_version!r} != {_EXPECTED_PROTOCOL!r}"
        )
    if gate2_verdict != _EXPECTED_GATE2:
        raise ValueError(f"P2 schema gate2_verdict 漂移: {gate2_verdict!r}")
    if scope != _EXPECTED_SCOPE:
        raise ValueError(f"P2 schema scope 漂移: {scope!r}")

    state_machine = _expect_key(raw, "state_machine")
    d1_lookup = _expect_key(raw, "d1_lookup")
    boundary_generators = _expect_key(raw, "boundary_generators")
    candidate_action = _expect_key(raw, "candidate_action")
    recovery_trigger = _expect_key(raw, "recovery_trigger")
    primary_metrics = _expect_key(raw, "primary_metrics")
    governance = _expect_key(raw, "governance")

    precedence = _parse_precedence(d1_lookup)
    _validate_precedence_vars(precedence)
    fail_closed_mode = str(precedence[-1][1])

    history_suff = _expect_key(d1_lookup, "history_sufficiency")
    hpb = _expect_key(boundary_generators, "history_protective_boundary")
    cap = _expect_key(boundary_generators, "capability_supported_boundary")

    budget_rule = str(_expect_key(_expect_key(candidate_action, "current_budget_source"), "rule"))
    probe_rule = str(_expect_key(_expect_key(candidate_action, "requested_delta_source"), "rule"))
    budget_base, budget_step, budget_mod = _parse_budget_rule(budget_rule)
    probe_grid = _parse_probe_grid(probe_rule)

    recovery_condition = str(_expect_key(recovery_trigger, "condition"))  # type: ignore[arg-type]

    layer2 = {
        str(k): str(v)
        for k, v in _expect_key(state_machine, "layer2_boundary_modes").items()
    }
    default_state = {
        str(k): str(v)
        for k, v in _expect_key(state_machine, "default_application_state").items()
    }
    for mode in _INFO_MODES:
        if mode not in layer2:
            raise ValueError(f"P2 schema layer2_boundary_modes 缺少 {mode}")
        if mode not in default_state:
            raise ValueError(f"P2 schema default_application_state 缺少 {mode}")
        if layer2[mode] not in ("capability_supported_boundary", "response_history_boundary",
                                "history_protective_boundary", "conservative_fallback"):
            raise ValueError(f"P2 schema boundary_mode 非法: {layer2[mode]!r}")
        if default_state[mode] not in _APPLICATION_STATES:
            raise ValueError(f"P2 schema default state 非法: {default_state[mode]!r}")

    sentinel_name = str(_expect_key(governance, "sentinel")).split("；")[0].strip()

    return SchemaConfig(
        experiment_id=experiment_id,
        protocol_version=protocol_version,
        gate2_verdict=gate2_verdict,
        scope=scope,
        schema_path=str(path),
        precedence=precedence,
        fail_closed_mode=fail_closed_mode,
        layer2_boundary_modes=layer2,
        default_application_state=default_state,
        min_history_samples=int(_expect_key(history_suff, "min_history_samples")),
        history_window_min=int(_expect_key(hpb, "window_min")),
        history_quantile=float(_expect_key(hpb, "quantile")),
        history_min_samples=int(_expect_key(hpb, "min_samples")),
        injection_value_kw=float(_expect_key(cap, "injection_value_kw")),
        budget_base_kw=budget_base,
        budget_step_kw=budget_step,
        budget_modulus=budget_mod,
        probe_grid=probe_grid,
        probe_modulus=len(probe_grid),
        recovery_ratio=_parse_recovery_ratio(recovery_condition),
        recovery_sustained_cycles=int(_expect_key(recovery_trigger, "sustained_cycles")),
        m1_target=float(
            _expect_key(primary_metrics["M1_D1_branch_realizability"], "target")
        ),
        m2_target=float(
            _expect_key(primary_metrics["M2_D2_action_bound_realizability"], "target")
        ),
        m4_target=float(
            _expect_key(primary_metrics["M4_unsupported_release_prevention"], "target")
        ),
        m3_min_traces=int(
            _expect_key(primary_metrics["M3_D3_recovery_trace_existence"], "minimum_traces")
        ),
        m3_min_sessions=int(
            _expect_key(primary_metrics["M3_D3_recovery_trace_existence"], "minimum_sessions")
        ),
        sentinel_name=sentinel_name,
        raw=cast(dict[str, Any], raw),
    )
