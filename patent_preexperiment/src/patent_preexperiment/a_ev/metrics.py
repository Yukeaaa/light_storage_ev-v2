"""A-EV 指标。

**主指标**（A-EV 计划 §7，**不得合成单一数字**）：
    ① 错误能力更新率 EMUR
       —— 在**注入的非能力原因**窗口内，策略错误收缩能力边界的**样本比例**。
          分子：该窗口内"该资源的能力边界被压到初始值以下"的样本数；
          分母：该窗口内的样本数。打在【b】归因门。
    ② 真实能力受限后的剩余未补偿功率 / 能量 RESID（打在【c】→【d】→【e】控制效果）

**次指标**：噪声误更新率、能力边界估计误差、二次不可执行命令率、级联承接次数、
            恢复时延、恢复误触发数、PCC 剩余偏差。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .scenario import Episode, station_actual_at
from .types import DIR_UP, Obs, ResourceSpec, Truth

#: 注入的**非能力原因**（在这些样本上出现能力边界收缩即为错误更新）
INJECTED_NON_CAPABILITY = frozenset(
    {Truth.COMM_FREEZE, Truth.TRANSIENT, Truth.EXTERNAL_CONSTRAINT}
)


@dataclass
class EpisodeMetrics:
    name: str
    policy: str
    emur_numer: int = 0
    emur_denom: int = 0
    emur_rate: float | None = None
    emur_by_class: dict[str, Any] | None = None
    noise_numer: int = 0
    noise_denom: int = 0
    noise_rate: float | None = None
    resid_mean_kw: float | None = None
    resid_energy_kwh: float | None = None
    bound_err_mean_kw: float | None = None
    bad_cmd_rate: float | None = None
    cascade_count: int = 0
    recovery_delay_s: float | None = None
    recovery_steps: int = 0
    recovery_false_steps: int = 0
    pcc_resid_mean_kw: float | None = None


def _truth_lookup(ep: Episode) -> dict[tuple[float, str], Truth]:
    return {(r.t, r.rid): r.truth for r in ep.truth}


def _initial_bounds(spec: ResourceSpec) -> tuple[float, float]:
    return spec.up_limit(), spec.down_limit()


def _is_reduced(
    policy: Any, t: float, rid: str, spec: ResourceSpec, hist: dict[float, Any]
) -> bool:
    """该时刻该资源的能力边界是否已被压到初始值以下（任一方向）。"""
    step = hist.get(round(t, 3))
    if step is None or not getattr(step, "bounds", None):
        return False
    b = step.bounds.get(rid)
    if b is None:
        return False
    up0, down0 = _initial_bounds(spec)
    eps = 1e-6
    return bool(b[0] < up0 - eps or b[1] < down0 - eps)


def evaluate(ep: Episode, policy: Any, cfg: dict[str, Any]) -> EpisodeMetrics:
    m = EpisodeMetrics(name=ep.spec.name, policy=getattr(policy, "name", "?"))
    truth = _truth_lookup(ep)
    spec_by = {s.rid: s for s in ep.specs}
    band = float(cfg["attribution"]["deviation_band_kw"])
    dt = ep.spec.dt
    hist = {round(s.t, 3): s for s in getattr(policy, "history", [])}

    # ---------------- 主指标 1：错误能力更新率（样本级，仅在注入的非能力原因窗口内）
    by_class: dict[str, list[int]] = {}
    for (t, rid), tr in truth.items():
        spec = spec_by[rid]
        if tr in INJECTED_NON_CAPABILITY:
            m.emur_denom += 1
            rec = by_class.setdefault(tr.value, [0, 0])
            rec[1] += 1
            if _is_reduced(policy, t, rid, spec, hist):
                m.emur_numer += 1
                rec[0] += 1
        elif tr is Truth.NORMAL:
            m.noise_denom += 1
    # 噪声误更新：只统计**发生在 NORMAL 样本上**的收缩动作（事件级），
    # 不把"事件结束后尚未恢复"的状态计入——那属于恢复时延，不属于错误更新。
    for step in getattr(policy, "history", []):
        for ev in getattr(step, "cap_events", []):
            if truth.get((ev["t"], ev["rid"])) is Truth.NORMAL:
                m.noise_numer += 1

    m.emur_rate = (m.emur_numer / m.emur_denom) if m.emur_denom else None
    m.noise_rate = (m.noise_numer / m.noise_denom) if m.noise_denom else None
    m.emur_by_class = {
        k: {"numer": v[0], "denom": v[1], "rate": (v[0] / v[1]) if v[1] else None}
        for k, v in by_class.items()
    }

    # ---------------- 主指标 2 + 能力边界误差（仅真实能力受限的 episode）
    t0 = ep.spec.t_event_start
    t1 = min(ep.spec.t_event_end, ep.spec.horizon)
    offset = float(cfg["metrics"]["residual_window_offset_s"])
    ws = t0 + offset
    if ep.spec.event is Truth.LOCAL_LIMIT and ws < t1 and ep.spec.probe_at <= 0.0:
        ts = [round(ws + k * dt, 3) for k in range(int((t1 - ws) / dt))]
        vals = [abs(station_actual_at(ep, t) - ep.station_plan_at(t)) for t in ts]
        if vals:
            m.resid_mean_kw = sum(vals) / len(vals)
            m.resid_energy_kwh = sum(vals) * dt / 3600.0
        rid = ep.spec.target_rid
        side = 0 if ep.spec.direction == DIR_UP else 1
        base = abs(float(cfg["schedule"]["base_setpoint_kw"][rid]))
        errs = []
        for t in ts:
            s = hist.get(t)
            if s is None or rid not in getattr(s, "bounds", {}):
                continue
            errs.append(abs(s.bounds[rid][side] - base))
        if errs:
            m.bound_err_mean_kw = sum(errs) / len(errs)

    # ---------------- 次指标
    obs_by_t: dict[float, dict[str, Obs]] = {}
    for o in ep.obs:
        obs_by_t.setdefault(o.t, {})[o.rid] = o

    bad = 0
    carrier_steps = 0
    for step in getattr(policy, "history", []):
        carriers = getattr(step, "carriers", ())
        if not carriers:
            continue
        carrier_steps += 1
        row = obs_by_t.get(round(step.t, 3), {})
        for rid in carriers:
            ob_c = row.get(rid)
            if ob_c is not None and abs(ob_c.p_meas - ob_c.p_req) >= band:
                bad += 1
                break
    m.bad_cmd_rate = (bad / carrier_steps) if carrier_steps else 0.0

    m.cascade_count = sum(len(getattr(s, "writebacks", [])) for s in getattr(policy, "history", []))

    rec_steps = [
        (s.t, ev)
        for s in getattr(policy, "history", [])
        for ev in getattr(s, "recover_events", [])
        if ev.get("kind") == "recover_step"
    ]
    if ep.spec.expect_recovery:
        # 应恢复：记录恢复时延与恢复级数
        m.recovery_delay_s = (
            (min(t for t, _ in rec_steps) - ep.spec.probe_at) if rec_steps else None
        )
        m.recovery_steps = len(rec_steps)
    elif ep.spec.probe_at > 0.0:
        # 不得误恢复（试探失败）：出现任何 recover_step 即误触发
        m.recovery_false_steps = len(rec_steps)
    if (
        ep.spec.event is Truth.LOCAL_LIMIT
        and not ep.spec.expect_recovery
        and ep.spec.probe_at <= 0.0
    ):
        m.recovery_false_steps = len(rec_steps)

    all_t = sorted({round(r.t, 3) for r in ep.plant})
    pcc = [abs(station_actual_at(ep, t) - ep.station_plan_at(t)) for t in all_t]
    m.pcc_resid_mean_kw = sum(pcc) / len(pcc) if pcc else None
    return m
