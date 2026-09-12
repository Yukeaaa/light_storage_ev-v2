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
    DIR_DOWN,
    DIR_UP,
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
    fallback_dispatches: list[Dispatch] = field(default_factory=list)
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
    #: V0.3 模块 6（工程监督层，**非权项链路**）：站级 PCC 残差独立闭环后备。
    #: 能力证据通道保持严格（有疑问宁可不更新）；站级补偿由 PCC 独立表计残差驱动，
    #: 二者解耦——参考实现默认关闭以保证 A-EV 机制隔离，工程形态开启。
    pcc_fallback_enabled = False

    def __init__(
        self,
        specs: list[ResourceSpec],
        cfg: dict[str, Any],
        strategy: str | None = None,
        thr: Thresholds | None = None,
    ) -> None:
        self.specs = {s.rid: s for s in specs}
        self.cfg = cfg
        self.strategy = strategy
        # formal 阶段由 runner 注入锁内 resolved thresholds；缺省路径仅供合成回归/单测
        self.thr: Thresholds = thr if thr is not None else build_thresholds(cfg, specs)
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
        # 监督后备（模块 6）状态
        self._pcc_corrections: dict[str, float] = {}
        self._pcc_streak = 0
        self._pcc_dir = 0

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

        # ---- 模块 1：有效性与能力归因判断（PCC 等非资源观测行不进资源归因）
        updates: list[tuple[str, AttributionResult]] = []
        admissible: list[tuple[str, AttributionResult]] = []
        for o in obs_rows:
            if o.rid not in self.specs:
                continue
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
                    self._pcc_corrections.pop(rid, None)   # 后备通道同步回收
                    self._pending_wb.discard(rid)

        # ---- 模块 3：缺口（仅由经有效性判定确认成立的执行偏差构成）
        gap = station_gap(admissible)
        gap.t = t
        res.gap = gap
        if gap.direction == 0:
            # 缺口消失 → 事务结束（仅清空**归因通道**的事务级状态；后备通道自行管理，
            # 避免站级残差闭合后后备修正被逐步清掉造成振荡）
            self._excluded.clear()
            for rid in list(self._corrections):
                if rid not in self._pcc_corrections:
                    self._corrections.pop(rid, None)
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

        # ---- 模块 6：站级 PCC 残差监督后备（工程层；能力证据通道不受其影响）
        if self.pcc_fallback_enabled:
            res.fallback_dispatches = self._pcc_supervise(t, obs_by)
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

    # ------------------------------------------------------------------
    def _pcc_supervise(self, t: float, obs_by: dict[str, Obs]) -> list[Dispatch]:
        """模块 6：站级 PCC 残差监督后备（工程层，非权项链路）。

        - 残差来源 = **PCC 独立表计**（p_req=站级计划 − p_meas=站级实测），
          与资源级能力证据通道**完全解耦**：设备通信冻结/观测陈旧时不影响站级闭环；
        - 能力学习仍只走模块 1–2 的严格通道，本模块**不**更新能力状态；
        - level-holding：底层缺额 = 观测残差 + 已在服务的修正量；确认持续后把
          后备承接量补足到底层缺额（扣除非后备通道已在服务的部分，避免双重承接）；
        - 站级真实超发（观测残差持续为负）→ 释放后备修正；
        - 承接候选排除通信无效/数据不新鲜的资源（其执行结果不可观测）。
        """
        pcc = obs_by.get("PCC")
        if pcc is None or not pcc.comm_ok or not pcc.data_fresh:
            return []
        # 后备持有的修正量始终登记执行反馈监视——每步「缺口归零 → 事务清理」会清空
        # _pending_wb/_issued_at，若不重登记，承接资源失效时写回排除将永不触发。
        for rid in self._pcc_corrections:
            self._pending_wb.add(rid)
            self._issued_at.setdefault(rid, t)
        raw = pcc.p_req - pcc.p_meas                       # 站级残差（>0 缺注入）
        serving_total = sum(self._corrections.values())    # 已在服务的全部修正（两通道）
        underlying = raw + serving_total                   # 剔除已承接后的底层缺额
        band = self.thr.default_band
        if underlying > band:
            direction = DIR_UP
        elif raw < -band:
            direction = DIR_DOWN                            # 真实超发 → 释放后备
        else:
            self._pcc_streak, self._pcc_dir = 0, 0
            return []                                        # 带内：维持现状
        if direction != self._pcc_dir:
            self._pcc_streak, self._pcc_dir = 0, direction
        self._pcc_streak += 1
        if self._pcc_streak < self.thr.confirm_n:
            return []
        if direction == DIR_DOWN:
            for rid in self._pcc_corrections:
                self._corrections.pop(rid, None)
            self._pcc_corrections = {}
            return []
        attr_serving = sum(
            v for rid, v in self._corrections.items() if rid not in self._pcc_corrections
        )
        need = max(0.0, underlying - attr_serving)
        # 防抖：需求相对现有后备承接量变化未超判据带 → 维持现有承接，
        # 不逐步重选（否则会在"虚假 headroom"资源与实际承重资源间来回换手）。
        serving_pcc = sum(self._pcc_corrections.values())
        if abs(need - serving_pcc) < band:
            return []

        def _visibly_failing(rid: str) -> bool:
            """显性执行失败：已越过响应观察窗仍存在超带欠交付（且非上报型限值解释）。"""
            o = obs_by.get(rid)
            if o is None or o.reported_limit_active:
                return False
            if abs(o.p_req - o.p_meas) < self.thr.band(rid):
                return False
            issued = self._issued_at.get(rid)
            # 刚下发的指令给足响应观察窗；越过观察窗仍失败 → 不再向其派发
            return issued is None or (t - issued) >= self.thr.window_s

        gap = StationGap(t=t, direction=DIR_UP, magnitude=need, contributors=["PCC"])
        excluded = self._excluded | {
            rid
            for rid in self.specs
            if (not obs_by[rid].comm_ok or not obs_by[rid].data_fresh or _visibly_failing(rid))
        }
        dispatches = select_carriers(
            gap, self.specs, obs_by, self.sizing_states, set(), excluded,
            self._switch_counts, self.thr, self.cfg, self.strategy,
        )
        new_pcc = {d.carrier_rid: d.correction for d in dispatches}
        for rid in self._pcc_corrections:
            if rid not in new_pcc:
                self._corrections.pop(rid, None)
                self._pending_wb.discard(rid)
        # 后备派发同样登记执行反馈监视（_issued_at / _pending_wb）：
        # 承接资源失效时走与归因通道相同的写回排除路径（权 7 的确认条件）。
        for rid in new_pcc:
            if rid not in self._corrections:
                self._issued_at[rid] = t
            self._pending_wb.add(rid)
        self._pcc_corrections = new_pcc
        self._corrections.update(new_pcc)
        return dispatches
