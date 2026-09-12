"""HIL 可控真值场景生成器（对应 A-EV 计划 §2 数据合同 / §4 场景矩阵 / §5 闭环 episode）。

设计要点：
1. **事件真值由注入端给定**（`Truth`），控制策略不可见——这正是 A 最缺的 ground truth。
2. 现场为 3 资源 + PCC：R0（BESS，双向）、R1（BESS，双向）、R2（充电设备，单向下向）。
   单边资源覆盖说明书 §12「仅支持单向调节的资源仅设置对应方向的能力边界」。
3. A-EV-1 核心对照：对**同一个约 20 kW 的偏差**注入四种不同原因
   （其中**三种为非能力原因**：通信冻结 / 暂态响应 / 站级外部约束；
   一种是真实能力受限：本机持续限功率）；
   限值统一由该资源基值推出，保证各原因下偏差幅值一致。
4. 观测中的 `p_req` 为**含承接修正的有效要求**，因此"承接资源未按要求执行"可被观测到
   （权 7 回写与级联的前提）。
5. `Simulator` 步进式：观测 → 策略 → 修正量回流 → 下一步；
   plant 含**纯响应延迟 + 一阶响应**（`response_delay_s` 真实作用于 plant，V0.2）。
6. 三类场景集**严格分离**：
   `default_scenarios`（正式评价）/ `commissioning_scenarios`（标定，不评价）
   / `robustness_scenarios`（稳健性矩阵，预注册于配置）。
7. `ScenarioSpec` 可 JSON 序列化，将来直接驱动真实 HIL。

**本模块产出的是合成数据，仅用于机制与管线验证，不构成效果证据。**
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .types import DIR_DOWN, DIR_UP, LimitDir, Obs, PlantRow, ResourceSpec, Truth, TruthRow

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
    #: 该 episode 是否**期望**发生恢复：用于区分"应恢复"与"不得误恢复"
    expect_recovery: bool = False
    #: T1 限值在 t_event_end 之后是否继续生效（限值未解除，但站级要求已回基值）—— S9：
    #: 事务因缺口消失而结束，设备的**物理限值**并不随之解除。
    clamp_persist: bool = False
    #: 第二事件窗口（独立目标资源）：跨事务复用持久能力知识场景（S9）。
    #: 真值沿用 `event`（当前仅支持 LOCAL_LIMIT）。
    target2_rid: str = ""
    t_event2_start: float = 0.0
    t_event2_end: float = 0.0
    magnitude2: float = 0.0
    #: 上报型本地限值（S10）：本地 BMS/PCS 裁剪**可观测**（accepted < requested），
    #: 设备按接受到的指令正确执行 → 不构成执行偏差证据（命令链四层留痕演示）。
    reported_clamp: bool = False
    #: 通信冻结 + 真实未执行并存（S11）：观测陈旧**且** plant 真实受限——
    #: 能力证据须严格（不更新），站级补偿走 PCC 残差独立通道。
    real_failure_under_comm: bool = False
    #: 额外覆盖（稳健性矩阵）："" | "ts_misalign" | "mode_switch" | "protection"
    #: —— 均制造**同样的执行偏差**，但原因属于必须被排除/暂缓的类别
    extra_coverage: str = ""
    #: 场景集标注：正式评价 / 标定 / 稳健性（防止标定数据混入正式评价）
    phase: str = "evaluation"

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
    """由配置构造资源（V0.3：动态可行功率区间 [p_min, p_max] + 类别）。"""
    s = cfg["site"]

    def res(key: str, rid: str, **kw: Any) -> ResourceSpec:
        e = s[key]
        rated = float(e["p_rated"])
        kind = str(e.get("kind", kw.get("kind", "bess")))
        # p_min/p_max 缺省按类别推导（推荐配置中显式给出，便于预注册）
        p_min = float(e["p_min"]) if "p_min" in e else kw.get("p_min", -rated)
        p_max = float(e["p_max"]) if "p_max" in e else kw.get("p_max", rated)
        return ResourceSpec(
            rid, rated, p_min, p_max, kind=kind,
            soc=float(e["soc"]), temp_c=float(e["temp_c"]),
            ramp_kw_per_s=float(e["ramp"]),
        )

    return [
        res("r0", "R0"),                                        # BESS，双向
        res("r1", "R1"),                                        # BESS，双向（首选承接资源）
        res("r2", "R2", kind="evse", p_min=-60.0, p_max=0.0),   # 充电设备：区间 [-60, 0]
    ]


def default_scenarios(cfg: dict[str, Any]) -> list[ScenarioSpec]:
    """正式评价场景集（**不含**标定场景）。"""
    S = ScenarioSpec
    t_end = float(cfg["scenario"]["t_event_end"])
    return [
        S("S0_normal", Truth.NORMAL, "R0", DIR_UP, magnitude=0.0),
        # ---- A-EV-1：同幅值偏差、四种原因（三种非能力 + 一种真实能力受限）----
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
        # ---- A-EV-8（S11）：通信冻结 + 真实未执行并存 → 能力证据与站级补偿解耦 ----
        S("S11_comm_loss_real_failure", Truth.COMM_FREEZE, "R0", DIR_UP,
          real_failure_under_comm=True),
        # ---- A-EV-7（S10）：上报型本地限值（命令链 accepted<requested）——
        #      设备按"接受到的指令"正确执行 → 不构成执行偏差证据 ----
        S("S10_reported_clamp", Truth.LOCAL_LIMIT, "R0", DIR_UP, reported_clamp=True),
        # ---- A-EV-6（S9）：跨事务复用持久能力知识（权 7 事务级排除 ≠ 权 1【c】/【e】持久状态）----
        # T1：R0 被持续限值 → 归因确认 → up_bound 收缩到基值 30；事务随缺口消失而结束
        #     （corrections / 事务级排除清空），但**物理限值未解除**（clamp_persist）、
        #     无恢复试探 → 持久能力知识保持。
        # T2：R1 出现新的独立限值制造上向缺口；R0 是唯一其他可上向承接资源——
        #     正确 A 不向 R0 下发超过其已知能力的修正（headroom=0 → 不派）；
        #     A-no-state 按额定能力估计 → 再次向 R0 派发 → 二次不可执行命令。
        S("S9_learned_carrier_reuse", Truth.LOCAL_LIMIT, "R0", DIR_UP,
          t_event_start=30.0, t_event_end=80.0, magnitude=20.0, clamp_persist=True,
          target2_rid="R1", t_event2_start=110.0, t_event2_end=150.0, magnitude2=20.0,
          horizon=150.0),
    ]


def commissioning_scenarios(cfg: dict[str, Any]) -> list[ScenarioSpec]:
    """**标定专用**场景：只用于测设备阶跃响应时间与噪声水平，**不参与 A-EV 评价**。

    这些场景与正式评价场景**没有任何交集**，用于落实"commissioning 数据不进入
    正式评价"的预注册纪律（A-EV 计划 §7）。
    """
    S = ScenarioSpec

    def cm(
        name: str, rid: str, direction: int, probe: float, horizon: float = 80.0
    ) -> ScenarioSpec:
        return S(
            name, Truth.NORMAL, rid, direction, magnitude=0.0,
            t_event_start=0.0, t_event_end=0.0, horizon=horizon,
            probe_at=20.0, probe_magnitude=probe, phase="commissioning",
        )

    return [
        cm("CM_step_up_R0", "R0", DIR_UP, 20.0),
        cm("CM_step_down_R0", "R0", DIR_DOWN, 20.0),
        cm("CM_step_up_R1", "R1", DIR_UP, 20.0),
        cm("CM_step_down_R2", "R2", DIR_DOWN, 15.0),
        S("CM_rest_R0", Truth.NORMAL, "R0", DIR_UP, magnitude=0.0,
          t_event_start=0.0, t_event_end=0.0, horizon=60.0, phase="commissioning"),
    ]


def robustness_scenarios(cfg: dict[str, Any]) -> list[ScenarioSpec]:
    """稳健性矩阵（**预注册于配置**：方向 × 幅值 × 资源 × 重复 × 随机顺序 + 额外覆盖）。"""
    rb = cfg.get("robustness") or {}
    if not rb.get("enabled"):
        return []
    site = cfg["site"]
    rated = {
        "R0": float(site["r0"]["p_rated"]),
        "R1": float(site["r1"]["p_rated"]),
        "R2": float(site["r2"]["p_rated"]),
    }
    sc = cfg["scenario"]
    reps = int(rb.get("repeats", 1))
    seed0 = int(rb.get("seed", 101))
    out: list[ScenarioSpec] = []
    for dkey, dval in (("up", DIR_UP), ("down", DIR_DOWN)):
        for rid in rb.get("resources", {}).get(dkey, []):
            for pct in rb.get("magnitudes_pct", []):
                mag = round(rated[rid] * float(pct), 3)
                for k in range(reps):
                    out.append(
                        ScenarioSpec(
                            name=f"RB_{dkey}_{rid}_{int(round(float(pct) * 100))}pct_r{k}",
                            event=Truth.LOCAL_LIMIT,
                            target_rid=rid,
                            direction=dval,
                            magnitude=mag,
                            seed=seed0 + 13 * k + (3 if dval == DIR_UP else 7),
                            t_event_start=float(sc["t_event_start"]),
                            t_event_end=float(sc["t_event_end"]),
                            phase="robustness",
                        )
                    )
    for kind in rb.get("extra_coverage", []):
        # 额外覆盖：同样制造执行偏差，但原因**属于必须排除/暂缓的类别**
        out.append(
            ScenarioSpec(
                name=f"RB_extra_{kind}",
                event=Truth.LOCAL_LIMIT,
                target_rid=str(rb.get("extra_coverage_target", "R0")),
                direction=DIR_UP,
                magnitude=20.0,
                extra_coverage=str(kind),
                seed=seed0 + 999,
                t_event_start=float(sc["t_event_start"]),
                t_event_end=float(sc["t_event_end"]),
                phase="robustness",
            )
        )
    random.Random(seed0).shuffle(out)   # 顺序随机化（固定种子 → 可复现）
    return out


# ---------------------------------------------------------------- 步进式仿真器


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


#: 额外覆盖类别 → (观测标志, 事件真值标签)
_EXTRA_COVERAGE: dict[str, tuple[str, Truth]] = {
    "ts_misalign": ("ts", Truth.COMM_FREEZE),
    "mode_switch": ("mode", Truth.EXTERNAL_CONSTRAINT),
    "protection": ("prot", Truth.EXTERNAL_CONSTRAINT),
}


class Simulator:
    """站点 plant（限值裁剪 + 纯响应延迟 + 一阶响应 + 通信冻结导致的观测陈旧）。"""

    def __init__(self, spec: ScenarioSpec, specs: list[ResourceSpec], cfg: dict[str, Any]) -> None:
        self.spec = spec
        self.specs = {s.rid: s for s in specs}
        self.cfg = cfg
        self.base = {k: float(v) for k, v in cfg["schedule"]["base_setpoint_kw"].items()}
        self.rng = random.Random(spec.seed)
        self.tau = float(cfg["plant"]["response_tau_s"])
        self.delay = float(cfg["plant"]["response_delay_s"])
        self.noise = float(cfg["plant"]["meas_noise_kw"])
        self.prev_true: dict[str, float] = {s.rid: self.base[s.rid] for s in specs}
        self.frozen: dict[str, float] = {}
        self.last_seen: dict[str, float] = dict(self.prev_true)

    # -- 内部：给定 t 与修正量，算出一行结果 -------------------------------
    def _conditions(self, t: float) -> tuple[bool, bool, bool, bool, bool, Truth]:
        """返回 (w1_on, w1_clamp, w2_on, probe_on, sec_on, w1 真值)。

        w1_on   = 第一窗口内（站级要求抬升 + 限值生效）；
        w1_clamp = 第一窗口目标的限值是否生效 —— 含 `clamp_persist`（限值跨事务持续）；
        w2_on   = 第二窗口内（独立目标，真值沿用 `event`）。
        """
        spec = self.spec
        w1_on = (spec.t_event_start <= t < spec.t_event_end) and spec.event is not Truth.NORMAL
        clamp_kind = (
            spec.event in (Truth.LOCAL_LIMIT, Truth.EXTERNAL_CONSTRAINT)
            or bool(spec.extra_coverage)
            or spec.reported_clamp
            or spec.real_failure_under_comm
        )
        w1_clamp = (
            clamp_kind
            and spec.t_event_start <= t
            and (t < spec.t_event_end or spec.clamp_persist)
        )
        w2_on = bool(spec.target2_rid) and spec.t_event2_start <= t < spec.t_event2_end
        probe_on = spec.probe_at > 0.0 and t >= spec.probe_at
        sec_on = spec.secondary is not None and spec.secondary.at <= t < spec.t_event_end
        truth_target = spec.event if w1_on else Truth.NORMAL
        return w1_on, w1_clamp, w2_on, probe_on, sec_on, truth_target

    def advance(
        self, t: float, corrections: dict[str, float]
    ) -> tuple[list[Obs], list[TruthRow], list[PlantRow], float]:
        spec, cfg = self.spec, self.cfg
        base = self.base
        w1_on, w1_clamp, w2_on, probe_on, sec_on, truth_target = self._conditions(t)
        cov = spec.extra_coverage
        cov_kind = _EXTRA_COVERAGE.get(cov, (None, truth_target))[0]

        req: dict[str, float] = {}
        for rid in self.specs:
            p = base[rid]
            if rid == spec.target_rid and w1_on:
                p += spec.magnitude * (DIR_UP if spec.direction == DIR_UP else DIR_DOWN)
            if rid == spec.target2_rid and w2_on:
                p += spec.magnitude2 * (DIR_UP if spec.direction == DIR_UP else DIR_DOWN)
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
            clamp1_on = rid == spec.target_rid and w1_clamp
            clamp2_on = rid == spec.target2_rid and w2_on and spec.event in (
                Truth.LOCAL_LIMIT,
                Truth.EXTERNAL_CONSTRAINT,
            )
            if clamp1_on or clamp2_on:
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

            # --- 指令下发时刻
            cmd_sent_t = 0.0
            if rid == spec.target_rid and w1_on:
                cmd_sent_t = spec.t_event_start
            if rid == spec.target2_rid and w2_on:
                cmd_sent_t = max(cmd_sent_t, spec.t_event2_start)
            if rid == spec.target_rid and probe_on:
                cmd_sent_t = max(cmd_sent_t, spec.probe_at)
            if sec_on and spec.secondary is not None and rid == spec.secondary.rid:
                cmd_sent_t = max(cmd_sent_t, spec.secondary.at)

            # --- plant 动态：纯响应延迟 → 一阶响应
            target = _clip(p_eff[rid], -down_lim, up_lim)
            # 命令链四层留痕（V0.3）：accepted = 本地控制器接受（翻译/裁剪后）的指令。
            # 仅"上报型本地限值"场景中 accepted < requested；其余场景二者相同。
            reported = rid == spec.target_rid and w1_on and spec.reported_clamp
            p_cmd_accepted = target if reported else p_eff[rid]
            win = float(cfg["attribution"]["response_window_s"])
            lagging = (
                (rid == spec.target_rid and truth_target is Truth.TRANSIENT)
                or (rid == spec.target2_rid and w2_on and spec.event is Truth.TRANSIENT)
                or (rid == spec.target_rid and probe_on and (t - spec.probe_at) < win)
                or (sec_on and spec.secondary is not None and rid == spec.secondary.rid
                    and (t - spec.secondary.at) < win)
            )
            if lagging:
                if cmd_sent_t > 0.0 and (t - cmd_sent_t) < self.delay:
                    p_true = self.prev_true[rid]          # 纯延迟：输出保持原值
                else:
                    alpha = min(1.0, spec.dt / self.tau)
                    p_true = self.prev_true[rid] + (target - self.prev_true[rid]) * alpha
            else:
                p_true = target
            self.prev_true[rid] = p_true

            comm_bad = w1_on and rid == spec.target_rid and truth_target is Truth.COMM_FREEZE
            if comm_bad:
                p_seen = self.frozen.setdefault(rid, self.last_seen[rid])
            else:
                p_seen = p_true + self.rng.gauss(0.0, self.noise)
                self.last_seen[rid] = p_seen

            ll_active = (
                w1_on and rid == spec.target_rid and truth_target is Truth.LOCAL_LIMIT
            ) or (
                w2_on and rid == spec.target2_rid and spec.event is Truth.LOCAL_LIMIT
            ) or (sec_on and spec.secondary is not None and rid == spec.secondary.rid)
            ll_dir = LimitDir.UNKNOWN
            if ll_active:
                ll_dir = LimitDir.UP if spec.direction == DIR_UP else LimitDir.DOWN

            target_cov = rid == spec.target_rid and w1_on and bool(cov)
            obs_rows.append(
                Obs(
                    t=t,
                    rid=rid,
                    p_req=p_eff[rid],
                    p_meas=p_seen,
                    cmd_sent_t=cmd_sent_t,
                    resp_start_t=(cmd_sent_t + self.delay) if cmd_sent_t else None,
                    comm_ok=not comm_bad,
                    data_fresh=not comm_bad,
                    ts_aligned=not (target_cov and cov_kind == "ts"),
                    local_limit_active=ll_active,
                    local_limit_dir=ll_dir,
                    mode_switch=bool(target_cov and cov_kind == "mode"),
                    protection_event=bool(target_cov and cov_kind == "prot"),
                    station_constraint_active=(
                        w1_on and rid == spec.target_rid
                        and truth_target is Truth.EXTERNAL_CONSTRAINT and not cov
                    ),
                    soc=s.soc,
                    temp_c=s.temp_c,
                    p_cmd_requested=p_eff[rid],
                    p_cmd_accepted=p_cmd_accepted,
                    reported_limit_active=reported,
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
            if rid == spec.target2_rid and w2_on:
                label = spec.event
            if sec_on and spec.secondary is not None and rid == spec.secondary.rid:
                label = Truth.LOCAL_LIMIT
            if target_cov:
                label = _EXTRA_COVERAGE[cov][1]
            truth_rows.append(
                TruthRow(
                    t=t,
                    rid=rid,
                    truth=label,
                    true_deviation=p_eff[rid] - p_true,
                    observed_deviation=p_eff[rid] - p_seen,
                )
            )

        # ---- PCC 独立表计观测（V0.3，站级残差通道的数据来源）----
        # 与资源级观测**相互独立**：即使某资源通信冻结 / 观测陈旧，站级残差仍可测。
        station_actual = sum(r.p_meas_true for r in plant_rows)
        obs_rows.append(
            Obs(
                t=t,
                rid="PCC",
                p_req=plan,
                p_meas=station_actual + self.rng.gauss(0.0, self.noise),
                cmd_sent_t=0.0,
                resp_start_t=None,
                comm_ok=True,
                data_fresh=True,
                ts_aligned=True,
                local_limit_active=False,
                local_limit_dir=LimitDir.UNKNOWN,
                mode_switch=False,
                protection_event=False,
                station_constraint_active=False,
                soc=0.5,
                temp_c=25.0,
                p_cmd_requested=plan,
                p_cmd_accepted=plan,
                reported_limit_active=False,
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
