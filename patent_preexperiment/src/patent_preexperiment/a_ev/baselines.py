"""对照基线（A-EV 计划 §6 固定三条 + A 本体）。

    B0  看到执行偏差就直接收缩能力边界（**无归因门**）
    B1  仅依据 SOC / 温度 / Pmax 等**内部状态**静态降额（不看执行证据）
    B2  只把执行误差**滚入下一周期计划**（不维护持久能力状态）
    A   归因 → 能力状态 → 跨资源承接 → 执行反馈回写

B0 由 `AEVPipeline` 覆写归因门得到，因此与 A 的差异**只**来自归因环节；
B1 / B2 不产生能力更新，也不做跨资源承接——二者的代价体现在第二主指标上。
"""

from __future__ import annotations

from typing import Any

from .algorithm import AEVPipeline
from .types import (
    DIR_UP,
    AttributionResult,
    CapabilityState,
    Obs,
    ResourceSpec,
    Verdict,
)


class BaselineB0(AEVPipeline):
    """无归因门：任何超带欠交付都直接当作"能力受限"并收缩边界。"""

    name = "B0_no_gate"
    use_attribution_gate = False

    def _attribute(self, obs: Obs) -> AttributionResult | None:
        band = float(self.cfg["attribution"]["deviation_band_kw"])
        req_dir = DIR_UP if obs.p_req > 0 else -DIR_UP
        under = abs(obs.p_req) - abs(obs.p_meas)
        if under < band:
            self.attr._reset(obs.rid)
            return None
        return AttributionResult(
            Verdict.VALID_CAPABILITY_LIMIT, req_dir, under, {"criterion": "no_gate"}
        )


class _StaticPolicy:
    """B1 / B2 的公共骨架：不维护持久能力状态、不做跨资源承接。"""

    name = "static"
    report_bounds = True

    def __init__(
        self,
        specs: list[ResourceSpec],
        cfg: dict[str, Any],
        strategy: str | None = None,
    ) -> None:
        self.specs = {s.rid: s for s in specs}
        self.cfg = cfg
        self.history: list[Any] = []
        self._corrections: dict[str, float] = {}
        self.states: dict[str, CapabilityState] = {}

    @property
    def corrections(self) -> dict[str, float]:
        return self._corrections

    def step(self, t: float, obs_rows: list[Obs]) -> Any:
        from .algorithm import StepResult

        res = StepResult(t=t)
        if self.report_bounds:
            res.bounds = {rid: (st.up_bound, st.down_bound) for rid, st in self.states.items()}
        else:
            # 不维护持续能力状态：不上报能力边界（其"错误更新率=0"为空真，须在报告中标注）
            res.bounds = {}
        self.history.append(res)
        return res


class BaselineB1(_StaticPolicy):
    """内部状态静态降额：能力上限由 SOC / 温度 / 本机限值直接算出，不随执行证据更新。"""

    name = "B1_static_derate"

    def __init__(
        self,
        specs: list[ResourceSpec],
        cfg: dict[str, Any],
        strategy: str | None = None,
    ) -> None:
        super().__init__(specs, cfg, strategy)
        self.states = {
            s.rid: CapabilityState(
                rid=s.rid,
                up_bound=self._derate(s, DIR_UP),
                down_bound=self._derate(s, -DIR_UP),
                up_conf=0.5,
                down_conf=0.5,
                init_source="static_derate",
            )
            for s in specs
        }

    def _derate(self, spec: ResourceSpec, direction: int) -> float:
        lim = spec.up_limit() if direction == DIR_UP else spec.down_limit()
        if lim <= 0:
            return 0.0
        soc = spec.soc
        # 静态规则：SOC 越偏离工作区，降额越强（不读执行证据）
        k = 1.0
        if direction == DIR_UP and soc < 0.3:
            k = 0.5
        if direction == -DIR_UP and soc > 0.7:
            k = 0.5
        if spec.temp_c > 45.0:
            k *= 0.7
        return lim * k


class BaselineB2(_StaticPolicy):
    """误差滚动：把执行误差滚入下一周期计划，不维护持续能力知识、不重分配。"""

    name = "B2_error_rolling"
    report_bounds = False

    def __init__(
        self,
        specs: list[ResourceSpec],
        cfg: dict[str, Any],
        strategy: str | None = None,
    ) -> None:
        super().__init__(specs, cfg, strategy)
        self.states = {
            s.rid: CapabilityState(
                rid=s.rid,
                up_bound=0.0,       # 不维护能力边界
                down_bound=0.0,
                up_conf=0.0,
                down_conf=0.0,
                init_source="none",
            )
            for s in specs
        }
