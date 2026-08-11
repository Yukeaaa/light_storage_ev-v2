"""D1 — 信息类别 → 边界生成模式选择的穷尽 precedence 查表（P0-3 / P0-1）。

- 机器权威形式：直接加载 schema `d1_lookup.precedence`（`if` / `mode` / `else` 字段），
  逐条求值，禁止把规则顺序硬编码在代码里。
- `if` 表达式用 `ast` 严格解析：只允许四个信息布尔变量
  （capability_available / pilot_available / actual_available / history_sufficient）
  与 `and` / `or` / `not` / `== true` 组合；任何其它语法 → 确定性失败。
- 未覆盖组合一律落 `else: fail_closed`（→ M4），绝不输出未支持区间。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from patent_preexperiment.phase3_p2.schema import M1, M2, M3, M4, SchemaConfig

InfoVars = tuple[bool, bool, bool, bool]
# (capability_available, pilot_available, actual_available, history_sufficient)

_ALLOWED_VARS = frozenset(
    {"capability_available", "pilot_available", "actual_available", "history_sufficient"}
)


def eval_condition(condition: str, env: dict[str, bool]) -> bool:
    """按 schema 的 `if` 表达式对给定信息面求值（机器可执行、确定性）。"""

    def _eval(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            if node.id in ("true", "false"):
                return node.id == "true"
            if node.id not in _ALLOWED_VARS:
                raise ValueError(f"D1 precedence 引用不允许的变量: {node.id!r}")
            return env[node.id]
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return node.value
            raise ValueError(f"D1 precedence 不允许的常量: {node.value!r}")
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            return all(_eval(v) for v in node.values)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            return any(_eval(v) for v in node.values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not _eval(node.operand)
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            op = node.ops[0]
            if isinstance(op, ast.Eq):
                left = _eval(node.left)
                right = _eval(node.comparators[0])
                return left == right
            if isinstance(op, ast.NotEq):
                left = _eval(node.left)
                right = _eval(node.comparators[0])
                return left != right
            raise ValueError(f"D1 precedence 不支持的比较符: {type(op).__name__}")
        raise ValueError(f"D1 precedence 不支持的语法: {ast.dump(node)}")

    tree = ast.parse(condition, mode="eval")
    return _eval(tree.body)


@dataclass(frozen=True)
class LookupResult:
    mode: str
    reason_code: str


def lookup_mode(precedence: tuple[tuple[str, str | None], ...], env: dict[str, bool]) -> LookupResult:
    """对单个信息面查 precedence 表：第一条命中的 if 规则 → 对应 mode。

    `else: fail_closed` 必须存在且位于最后；没有 else 或没有规则命中 → 确定性失败。
    """
    for idx, (cond, mode) in enumerate(precedence):
        if mode is None:
            raise ValueError(f"D1 precedence 规则 {idx + 1} 缺少 mode")
        if cond == "else":
            return LookupResult(mode=mode, reason_code="fail_closed")
        if eval_condition(cond, env):
            return LookupResult(mode=mode, reason_code=f"rule{idx + 1}")
    raise ValueError("D1 precedence 没有 else fail_closed 兜底（schema 校验应已拦截）")


def build_info_mode_table(scfg: SchemaConfig) -> tuple[dict[InfoVars, LookupResult], list[str], list[str]]:
    """穷尽 16 种信息组合 → (info_mode, reason)。返回表 + mode/reason 的 16 长度数组。

    - `table`：按 InfoVars 查模式（供单点求值 / 测试）。
    - `mode_arr` / `reason_arr`：按 code=cap*8+pilot*4+actual*2+history 下标索引，
      供 pandas 向量化。
    """
    table: dict[InfoVars, LookupResult] = {}
    mode_arr: list[str] = [""] * 16
    reason_arr: list[str] = [""] * 16
    for cap in (False, True):
        for pilot in (False, True):
            for actual in (False, True):
                for hist in (False, True):
                    env = {
                        "capability_available": cap,
                        "pilot_available": pilot,
                        "actual_available": actual,
                        "history_sufficient": hist,
                    }
                    res = lookup_mode(scfg.precedence, env)
                    code = int(cap) * 8 + int(pilot) * 4 + int(actual) * 2 + int(hist)
                    table[(cap, pilot, actual, hist)] = res
                    mode_arr[code] = res.mode
                    reason_arr[code] = res.reason_code
    return table, mode_arr, reason_arr


def info_code(capability: Any, pilot: Any, actual: Any, history: Any) -> int:
    """四个信息布尔 → 0..15 下标（cap*8+pilot*4+actual*2+history）。"""
    return int(bool(capability)) * 8 + int(bool(pilot)) * 4 + int(bool(actual)) * 2 + int(bool(history))


def boundary_mode_for(mode: str, scfg: SchemaConfig) -> str:
    return scfg.layer2_boundary_modes[mode]


def assert_exhaustive(scfg: SchemaConfig) -> None:
    """确定性验证：16 种信息组合全部映射到合法 info_mode，且 fail-closed 兜底存在。"""
    table, _mode_arr, _reason_arr = build_info_mode_table(scfg)
    if len(table) != 16:
        raise ValueError(f"D1 查表未穷尽: {len(table)}/16")
    for res in table.values():
        if res.mode not in (M1, M2, M3, M4):
            raise ValueError(f"D1 查表输出非法 mode: {res.mode!r}")
    if scfg.fail_closed_mode != M4:
        raise ValueError(f"D1 fail-closed 兜底不是 M4: {scfg.fail_closed_mode!r}")
