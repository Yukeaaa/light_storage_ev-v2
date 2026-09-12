"""对照基线与消融策略（A-EV 计划 §6）。

**整链基线**（比较 A 相对"常规做法"的价值）：

    B0  看到执行偏差就直接收缩能力边界（**无归因门**）
    B1  仅依据 SOC / 温度 / Pmax 等**内部状态**静态降额（不看执行证据）
    B2  只把执行误差**滚入下一周期计划**（不维护持久能力状态）

**模块消融**（把 A 各环节的贡献分别隔离，V0.2 新增）：

    A-no-state      保留归因 + 缺口 + 承接，但承接只用**额定固定能力**，不维护持久状态 → 隔离【c】
    A-no-writeback  保留归因 + 能力更新 + 承接，但承接失败**不回写**、不产生事务级排除 → 隔离【e】

B0 由 `AEVPipeline` 覆写归因门得到，因此与 A 的差异**只**来自归因环节（⇒ 直接对应【b】）。
B1 / B2 不维护能力状态、不做跨资源承接，其代价体现在第二主指标上。
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
    deviation_of,
)


class BaselineB0(AEVPipeline):
    """无归因门：任何超带执行偏差都直接当作"能力受限"并收缩边界。

    注意其**错误更新并不限于欠交付**：过执行 / 反向执行同样被误判（这正是无门之害）。
    """

    name = "B0_no_gate"
    use_attribution_gate = False

    def _attribute(self, obs: Obs) -> AttributionResult | None:
        band = self.thr.band(obs.rid)
        dev = deviation_of(obs.p_req, obs.p_meas)
        if dev.gap_magnitude < band:
            self.attr._reset(obs.rid)
            return None
        return AttributionResult(
            verdict=Verdict.VALID_CAPABILITY_LIMIT,
            deviation=dev,
            evidence_direction=dev.req_dir,
            evidence_level=dev.delivered_in_req_dir,
            evidence={"criterion": "no_gate"},
        )


class ANoState(AEVPipeline):
    """消融【c】：有归因门与承接，但承接规模取自**额定固定能力**，不维护持久能力状态。

    其"错误更新率 = 0"属**空真**（从不更新），故其价值体现在控制类指标
    （剩余缺口 / 二次不可执行命令 / 级联能力）而非 EMUR。
    """

    name = "A_no_state"
    maintain_state = False
    size_from_persistent_state = False


class ANoWriteback(AEVPipeline):
    """消融【e】：有归因与能力更新，但承接失败**不回写**其能力状态、也不做事务级排除。

    因此缺口会持续派给同一承接资源，级联不会发生——用于隔离执行反馈闭环的价值。
    """

    name = "A_no_writeback"
    writeback_enabled = False


class ASupervisory(AEVPipeline):
    """A + 站级 PCC 残差监督后备（V0.3 模块 6，工程层）。

    与 A 的唯一差异 = `pcc_fallback_enabled`：能力证据通道**完全相同**（严格、
    通信无效不更新）；站级补偿额外由 PCC 独立表计残差驱动——演示
    "能力学习通道与站级控制残差通道解耦"的工程形态。该监督层属共享基础设施，
    **不进入权项链路**，也不改变 A-EV 机制隔离实验的主结论。
    """

    name = "A_sup"
    pcc_fallback_enabled = True


class _StaticPolicy:
    """B1 / B2 的公共骨架：不维护持久能力状态、不做跨资源承接。"""

    name = "static"
    report_bounds = True

    def __init__(
        self,
        specs: list[ResourceSpec],
        cfg: dict[str, Any],
        strategy: str | None = None,
        thr: Any = None,
    ) -> None:
        self.specs = {s.rid: s for s in specs}
        self.cfg = cfg
        self.thr = thr  # B1/B2 不使用阈值；仅为与 AEVPipeline 构造签名一致
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
        thr: Any = None,
    ) -> None:
        super().__init__(specs, cfg, strategy, thr)
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
        thr: Any = None,
    ) -> None:
        super().__init__(specs, cfg, strategy, thr)
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
