"""HIL 可控真值场景生成器（对应 A-EV 计划 §2 数据合同 / §4 场景矩阵 / §5 闭环 episode）。

设计要点：
1. **事件真值由注入端给定**（`Truth`），控制策略不可见——这正是 A 最缺的 ground truth。
2. 现场为 3 资源 + PCC：R0（BESS，双向）、R1（BESS，双向）、R2（充电设备，单向下向）。
   单边资源覆盖说明书 §12「仅支持单向调节的资源仅设置对应方向的能力边界」。
3. A-EV-1 核心对照：对**同一个约 20 kW 的偏差**注入四种不同原因；
   限值统一由该资源基值推出，保证各原因下偏差幅值一致。
4. 观测中的 `p_req` 为**含承接修正的有效要求**，因此"承接资源未按要求执行"可被观测到
   （权 7 回写与级联的前提）。
5. `Simulator` 步进式：观测 → 策略 → 修正量回流 → 下一步。生成结果 `Episode` 同时保留
   观测、事件真值与 plant 真值。`ScenarioSpec` 可 JSON 序列化，将来直接驱动真实 HIL。

**本模块产出的是合成数据，仅用于机制与管线验证，不构成效果证据。**
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .types import DIR_DOWN, DIR_UP, Obs, PlantRow, ResourceSpec, Truth, TruthRow

# ---------------------------------------------------------------- 场景定义


@dataclass
class SecondaryEvent:
    """级联事件（A-EV-4）：承接资源随后也被持续限制。"""

    rid: str
    at: float
    kind: Truth = Truth.LOCAL_LIMIT


@dataclass
class ScenarioSpec:
    """一个 episode 的完整注入说明（可序列化 → 可直接驱动 HIL）。"""

    name: str
    event: Truth
    target_rid: str
    direction: int
    magnitude: float = 20.0
    t_event_start: float = 30.0
    t_event_end: float = 80.0
    horizon: float = 120.0
    dt: float = 1.0
    seed: int = 7
    secondary: SecondaryEvent | None = None
    probe_at: float = 0.0            # 恢复试探（A-EV-5）的请求时刻
    probe_magnitude: float = 0.0
    # 该 episode 是否**期望**发生恢复：用于区分"应恢复"与"不得误恢复"
    expect_recovery: bool = False

    def to_json(self) -> str:
        d = asdict(self)
        d["event"] = self.event.value
        if self.secondary is not None:
            d["secondary"]["kind"] = self.secondary.kind.value
        return json.dumps(d, ensure_ascii=False, indent=2)


@dataclass
class Episode:
    spec: ScenarioSpec
    specs: list[ResourceSpec]
    obs: list[Obs] = field(default_factory=list)
    truth: list[TruthRow] = field(default_factory=list)
    plant: list[PlantRow] = field(default_factory=list)
    plan: dict[float, float] = field(default_factory=dict)
    corrections: list[dict[str, float]] = field(default_factory=list)

    def station_plan_at(self, t: float) -> float:
        return self.plan.get(round(t, 3), 0.0)


class Policy(Protocol):
    def step(self, t: float, obs: list[Obs]) -> Any: ...

    @property
    def corrections(self) -> dict[str, float]: ...


# ---------------------------------------------------------------- 默认现场


def default_site(cfg: dict[str, Any]) -> list[ResourceSpec]:
    s = cfg["site"]
    return [
        ResourceSpec("R0", s["r0"]["p_rated"], True, s["r0"]["soc"], s["r0"]["temp_c"],
                     ramp_kw_per_s=s["r0"]["ramp"]),
        ResourceSpec("R1", s["r1"]["p_rated"], True, s["r1"]["soc"], s["r1"]["temp_c"],
                     ramp_kw_per_s=s["r1"]["ramp"]),
        ResourceSpec("R2", s["r2"]["p_rated"], False, s["r2"]["soc"], s["r2"]["temp_c"],
                     ramp_kw_per_s=s["r2"]["ramp"]),   # 仅吸收（单向下向）
    ]


def default_scenarios(cfg: dict[str, Any]) -> list[ScenarioSpec]:
    S = ScenarioSpec
    t_end = float(cfg["scenario"]["t_event_end"])
    return [
        S("S0_normal", Truth.NORMAL, "R0", DIR_UP, magnitude=0.0),
        # ---- A-EV-1：同幅值偏差、四种不同原因 ----
        S("S1_comm_freeze", Truth.COMM_FREEZE, "R0", DIR_UP),
        S("S2_transient", Truth.TRANSIENT, "R0", DIR_UP),
        S("S3_local_limit_up", Truth.LOCAL_LIMIT, "R0", DIR_UP),
        S("S4_external_constraint", Truth.EXTERNAL_CONSTRAINT, "R0", DIR_UP),
        # ---- 能力边界另一侧（吸收方向）----
        S("S5_local_limit_down", Truth.LOCAL_LIMIT, "R2", DIR_DOWN),
        # ---- A-EV-4：级联 ----
        S("S6_cascade", Truth.LOCAL_LIMIT, "R0", DIR_UP, secondary=SecondaryEvent("R1", at=60.0)),
        # ---- A-EV-5：恢复（限值解除 + 上探）----
        S("S7_recovery_ok", Truth.LOCAL_LIMIT, "R0", DIR_UP, t_event_end=t_end,
          probe_at=t_end + 5.0, probe_magnitude=50.0, expect_recovery=True),
        # ---- A-EV-5：恢复试探失败（限值未解除）→ 不得误触发恢复 ----
        S("S8_recovery_fail", Truth.LOCAL_LIMIT, "R0", DIR_UP, t_event_end=999.0,
          probe_at=t_end + 5.0, probe_magnitude=50.0),
    ]


# ---------------------------------------------------------------- 步进式仿真器


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class Simulator:
    """站点 plant（限值裁剪 + 一阶响应滞后 + 通信冻结导致的观测陈旧）。"""

    def __init__(self, spec: ScenarioSpec, specs: list[ResourceSpec], cfg: dict[str, Any]) -> None:
        self.spec = spec
        self.specs = {s.rid: s for s in specs}
        self.cfg = cfg
        self.base = {k: float(v) for k, v in cfg["schedule"]["base_setpoint_kw"].items()}
        self.rng = random.Random(spec.seed)
        self.tau = float(cfg["plant"]["response_tau_s"])
        self.noise = float(cfg["plant"]["meas_noise_kw"])
        self.prev_true: dict[str, float] = {s.rid: self.base[s.rid] for s in specs}
        self.frozen: dict[str, float] = {}
        self.last_seen: dict[str, float] = dict(self.prev_true)

    # -- 内部：给定 t 与修正量，算出一行结果 -------------------------------
    def _conditions(self, t: float) -> tuple[bool, bool, bool, Truth]:
        spec = self.spec
        event_on = (spec.t_event_start <= t < spec.t_event_end) and spec.event is not Truth.NORMAL
        probe_on = spec.probe_at > 0.0 and t >= spec.probe_at
        sec_on = spec.secondary is not None and spec.secondary.at <= t < spec.t_event_end
        truth_target = spec.event if event_on else Truth.NORMAL
        return event_on, probe_on, sec_on, truth_target

    def advance(
        self, t: float, corrections: dict[str, float]
    ) -> tuple[list[Obs], list[TruthRow], list[PlantRow], float]:
        spec, cfg = self.spec, self.cfg
        base = self.base
        event_on, probe_on, sec_on, truth_target = self._conditions(t)

        req: dict[str, float] = {}
        for rid in self.specs:
            p = base[rid]
            if rid == spec.target_rid and event_on:
                p += spec.magnitude * (DIR_UP if spec.direction == DIR_UP else DIR_DOWN)
            if rid == spec.target_rid and probe_on:
                p += spec.probe_magnitude * (DIR_UP if spec.direction == DIR_UP else DIR_DOWN)
            # 级联事件只**限制**承接资源（其有效要求已含上一步下发的功率修正量），
            # 不额外增加站级需求——否则会把 plan 抬高、把残差算歪。
            req[rid] = p
        p_eff = {rid: req[rid] + corrections.get(rid, 0.0) for rid in req}
        plan = sum(req.values())

        obs_rows: list[Obs] = []
        truth_rows: list[TruthRow] = []
        plant_rows: list[PlantRow] = []
        for rid, s in self.specs.items():
            up_lim, down_lim = s.up_limit(), s.down_limit()
            if rid == spec.target_rid and event_on and truth_target in (
                Truth.LOCAL_LIMIT,
                Truth.EXTERNAL_CONSTRAINT,
            ):
                lim = abs(base[rid])
                if spec.direction == DIR_UP:
                    up_lim = min(up_lim, lim)
                else:
                    down_lim = min(down_lim, lim)
            if sec_on and spec.secondary is not None and rid == spec.secondary.rid:
                lim = abs(base[rid])
                if spec.direction == DIR_UP:
                    up_lim = min(up_lim, lim)
                else:
                    down_lim = min(down_lim, lim)

            target = _clip(p_eff[rid], -down_lim, up_lim)
            win = float(cfg["attribution"]["response_window_s"])
            lagging = (
                (rid == spec.target_rid and truth_target is Truth.TRANSIENT)
                or (rid == spec.target_rid and probe_on and (t - spec.probe_at) < win)
                or (sec_on and spec.secondary is not None and rid == spec.secondary.rid
                    and (t - spec.secondary.at) < win)
            )
            if lagging:
                alpha = min(1.0, spec.dt / self.tau)
                p_true = self.prev_true[rid] + (target - self.prev_true[rid]) * alpha
            else:
                p_true = target
            self.prev_true[rid] = p_true

            comm_bad = event_on and rid == spec.target_rid and truth_target is Truth.COMM_FREEZE
            if comm_bad:
                p_seen = self.frozen.setdefault(rid, self.last_seen[rid])
            else:
                p_seen = p_true + self.rng.gauss(0.0, self.noise)
                self.last_seen[rid] = p_seen

            cmd_sent_t = 0.0
            if rid == spec.target_rid and event_on:
                cmd_sent_t = spec.t_event_start
            if rid == spec.target_rid and probe_on:
                cmd_sent_t = max(cmd_sent_t, spec.probe_at)
            if sec_on and spec.secondary is not None and rid == spec.secondary.rid:
                cmd_sent_t = max(cmd_sent_t, spec.secondary.at)

            ll_active = (
                event_on and rid == spec.target_rid and truth_target is Truth.LOCAL_LIMIT
            ) or (sec_on and spec.secondary is not None and rid == spec.secondary.rid)

            obs_rows.append(
                Obs(
                    t=t,
                    rid=rid,
                    p_req=p_eff[rid],
                    p_meas=p_seen,
                    cmd_sent_t=cmd_sent_t,
                    resp_start_t=(cmd_sent_t + float(cfg["plant"]["response_delay_s"]))
                    if cmd_sent_t
                    else None,
                    comm_ok=not comm_bad,
                    data_fresh=not comm_bad,
                    ts_aligned=True,
                    local_limit_active=ll_active,
                    local_limit_dir=spec.direction if ll_active else 0,
                    mode_switch=False,
                    protection_event=False,
                    station_constraint_active=(
                        event_on and rid == spec.target_rid
                        and truth_target is Truth.EXTERNAL_CONSTRAINT
                    ),
                    soc=s.soc,
                    temp_c=s.temp_c,
                )
            )
            plant_rows.append(
                PlantRow(
                    t=t,
                    rid=rid,
                    p_req_effective=p_eff[rid],
                    p_meas_true=p_true,
                    dispatched_correction=corrections.get(rid, 0.0),
                )
            )
            label = truth_target if rid == spec.target_rid else Truth.NORMAL
            if sec_on and spec.secondary is not None and rid == spec.secondary.rid:
                label = Truth.LOCAL_LIMIT
            truth_rows.append(
                TruthRow(
                    t=t,
                    rid=rid,
                    truth=label,
                    true_deviation=p_true - p_eff[rid],
                    observed_deviation=p_seen - p_eff[rid],
                )
            )
        return obs_rows, truth_rows, plant_rows, plan


def run_episode(
    spec: ScenarioSpec, specs: list[ResourceSpec], cfg: dict[str, Any], policy: Policy
) -> Episode:
    """按步骤交替推进：观测 → 策略 → 修正量回流 → 下一步。"""
    sim = Simulator(spec, specs, cfg)
    ep = Episode(spec=spec, specs=specs)
    n = int(spec.horizon / spec.dt)
    for k in range(n + 1):
        t = round(k * spec.dt, 3)
        obs_rows, truth_rows, plant_rows, plan = sim.advance(t, dict(policy.corrections))
        ep.obs.extend(obs_rows)
        ep.truth.extend(truth_rows)
        ep.plant.extend(plant_rows)
        ep.plan[t] = plan
        policy.step(t, obs_rows)
        ep.corrections.append(dict(policy.corrections))
    return ep


# ---------------------------------------------------------------- 便捷访问


def observation_index(ep: Episode) -> dict[float, list[Obs]]:
    idx: dict[float, list[Obs]] = {}
    for o in ep.obs:
        idx.setdefault(o.t, []).append(o)
    return idx


def truth_series(ep: Episode, rid: str) -> dict[float, Truth]:
    return {r.t: r.truth for r in ep.truth if r.rid == rid}


def plant_series(ep: Episode, rid: str) -> dict[float, PlantRow]:
    return {r.t: r for r in ep.plant if r.rid == rid}


def station_actual_at(ep: Episode, t: float) -> float:
    return sum(r.p_meas_true for r in ep.plant if abs(r.t - t) < 1e-6)
