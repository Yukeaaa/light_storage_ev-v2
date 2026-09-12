"""A 参考实现：串联模块 1–5（对应权 1【a】–【e】与权 12 的六个功能单元）。

事务语义（权 7、说明书 §9.7）：承接排除是**当前功率修正事务内**的选择排除，
缺口消失即事务结束、排除清空——**不是**持久资格或资源集合成员资格。

消融开关（A-EV 计划 §6，用于把【b】【c】【e】的贡献分别隔离）：

    maintain_state             模块 2「持久能力状态维护」是否启用（关 ⇒ 无更新、无恢复）
    size_from_persistent_state 承接规模是否取自**持久能力知识**（关 ⇒ 固定取额定快照）
    writeback_enabled          模块 5「执行反馈回写」是否启用（关 ⇒ 承接失败不回写、
                               不产生事务级排除，因而无级联）

缺口的来源口径：**经有效性判定确认成立的执行偏差**（VALID_CAPABILITY_LIMIT 与
VALID_EXECUTION_DEVIATION 两类）。未通过有效性判定的偏差（通信无效 / 暂态 / 外部约束 /
证据不足）既不构成缺口、也不更新能力状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .attribution import Attriber
from .capability import (
    RecoveryTrack,
    apply_capability_update,
    init_capability,
    maybe_recover,
    writeback_carrier,
)
from .gap_carrier import residual_gap, select_carriers, station_gap
from .thresholds import Thresholds, build_thresholds
from .types import (
    AttributionResult,
    CapabilityState,
    Dispatch,
    Obs,
    ResourceSpec,
    StationGap,
    Verdict,
)


@dataclass
class StepResult:
    t: float
    verdicts: dict[str, Verdict | None] = field(default_factory=dict)
    confirmed: list[tuple[str, AttributionResult]] = field(default_factory=list)
    gap_sources: list[tuple[str, AttributionResult]] = field(default_factory=list)
    cap_events: list[dict[str, Any]] = field(default_factory=list)
    recover_events: list[dict[str, Any]] = field(default_factory=list)
    writebacks: list[dict[str, Any]] = field(default_factory=list)
    gap: StationGap | None = None
    dispatches: list[Dispatch] = field(default_factory=list)
    residual: float = 0.0
    excluded: tuple[str, ...] = ()
    carriers: tuple[str, ...] = ()
    bounds: dict[str, tuple[float, float]] = field(default_factory=dict)


class AEVPipeline:
    """A 案参考实现（归因门 → 能力状态 → 缺口 → 跨资源承接 → 执行反馈回写）。"""

    name = "A"
    use_attribution_gate = True
    maintain_state = True
    size_from_persistent_state = True
    writeback_enabled = True

    def __init__(
        self,
        specs: list[ResourceSpec],
        cfg: dict[str, Any],
        strategy: str | None = None,
    ) -> None:
        self.specs = {s.rid: s for s in specs}
        self.cfg = cfg
        self.strategy = strategy
        self.thr: Thresholds = build_thresholds(cfg, specs)
        self.attr = Attriber(self.thr)
        self.states: dict[str, CapabilityState] = {s.rid: init_capability(s, cfg) for s in specs}
        # 承接规模所用状态：默认 = 持久能力状态（活的引用）；消融可改为冻结的额定快照
        self.sizing_states: dict[str, CapabilityState] = (
            self.states
            if self.size_from_persistent_state
            else {s.rid: init_capability(s, cfg) for s in specs}
        )
        self.tracks: dict[tuple[str, int], RecoveryTrack] = {}
        self.history: list[StepResult] = []
        self._corrections: dict[str, float] = {}
        self._excluded: set[str] = set()
        self._switch_counts: dict[str, int] = {}
        self._pending_wb: set[str] = set()
        self._issued_at: dict[str, float] = {}

    # ------------------------------------------------------------------
    @property
    def corrections(self) -> dict[str, float]:
        return self._corrections

    def _attribute(self, obs: Obs) -> AttributionResult | None:
        """归因门。子类可通过覆写实现对照策略。"""
        return self.attr.attribute(obs)

    # ------------------------------------------------------------------
    def step(self, t: float, obs_rows: list[Obs]) -> StepResult:
        res = StepResult(t=t)
        obs_by = {o.rid: o for o in obs_rows}

        # ---- 模块 1：有效性与能力归因判断
        updates: list[tuple[str, AttributionResult]] = []
        admissible: list[tuple[str, AttributionResult]] = []
        for o in obs_rows:
            r = self._attribute(o)
            res.verdicts[o.rid] = r.verdict if r is not None else None
            if r is None:
                continue
            if r.allows_update:
                updates.append((o.rid, r))
            if r.admissible:
                admissible.append((o.rid, r))
        res.confirmed = updates
        res.gap_sources = admissible

        # ---- 模块 2：能力状态更新（消融可关闭）
        if self.maintain_state:
            for rid, r in updates:
                ev = apply_capability_update(self.states[rid], r, obs_by[rid], self.cfg)
                if ev is not None:
                    res.cap_events.append(ev)
                key = (rid, r.evidence_direction)
                if key not in self.tracks:
                    self.tracks[key] = RecoveryTrack(rid=rid, direction=r.evidence_direction)

        # ---- 模块 5（回写）：对持有修正量的承接资源检查其实际执行结果
        # 确认条件：须已越过控制响应观察窗（说明书 §6.1 判据 3；权 7 的"满足确认条件"）
        win = self.thr.window_s
        if self.writeback_enabled:
            for rid in list(self._pending_wb):
                ob_wb = obs_by.get(rid)
                if ob_wb is None:
                    continue
                if t - self._issued_at.get(rid, t) < win:
                    continue
                ev = writeback_carrier(self.states[rid], ob_wb, self.thr, self.cfg)
                if ev is not None:
                    res.writebacks.append(ev)
                    self._excluded.add(rid)          # 当前事务内排除（权 7，事务级）
                    self._corrections.pop(rid, None)
                    self._pending_wb.discard(rid)

        # ---- 模块 3：缺口（仅由经有效性判定确认成立的执行偏差构成）
        gap = station_gap(admissible)
        gap.t = t
        res.gap = gap
        if gap.direction == 0:
            # 缺口消失 → 事务结束
            self._excluded.clear()
            self._corrections.clear()
            self._pending_wb.clear()
            self._issued_at.clear()

        # ---- 模块 4：承接选择与功率修正量
        sources = {rid for rid, _ in admissible}
        dispatches = select_carriers(
            gap,
            self.specs,
            obs_by,
            self.sizing_states,
            sources,
            self._excluded,
            self._switch_counts,
            self.thr,
            self.cfg,
            self.strategy,
        )
        for d in dispatches:
            if d.carrier_rid not in self._corrections:
                self._issued_at[d.carrier_rid] = t
            self._corrections[d.carrier_rid] = d.correction
            self._pending_wb.add(d.carrier_rid)
            self._switch_counts[d.carrier_rid] = self._switch_counts.get(d.carrier_rid, 0) + 1
        res.dispatches = dispatches
        res.residual = residual_gap(gap, dispatches)
        res.excluded = tuple(sorted(self._excluded))
        res.carriers = tuple(sorted(self._corrections))

        # ---- 模块 5（恢复）：分级恢复 + 迟滞 + 回退（消融可关闭）
        if self.maintain_state:
            for (_rid, _d), track in self.tracks.items():
                ob_rec = obs_by.get(track.rid)
                if ob_rec is None:
                    continue
                ev = maybe_recover(
                    self.states[track.rid], self.specs[track.rid], ob_rec, track, self.thr, self.cfg
                )
                if ev is not None:
                    res.recover_events.append(ev)

        # 能力边界上报：仅在维护持久状态时有意义（否则为"空真"，与 B2 同口径）
        res.bounds = (
            {rid: (st.up_bound, st.down_bound) for rid, st in self.states.items()}
            if self.maintain_state
            else {}
        )
        self.history.append(res)
        return res
