"""模块 2：Capability State Update（权 1【c】/【e】、权 4、权 5、权 9、说明书 §7 / §10）。

- 更新依据 = **经归因确认的执行证据**（不是内部状态量的直接映射）；
- 更新对象 = **该资源自己的持续能力知识**；
- 单边资源只维护其存在的那一侧（说明书 §12）；
- 恢复按分级方式执行，每一级须经实际执行结果连续确认；
  任一级不满足则**回退至该级恢复前的值**（权 9 + 说明书 §13.3）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import DIR_UP, AttributionResult, CapabilityState, Obs, ResourceSpec


def init_capability(spec: ResourceSpec, cfg: dict[str, Any], t0: float = 0.0) -> CapabilityState:
    """初始化（说明书 §10.3 的「无历史」路径：取额定能力）。"""
    up = spec.up_limit()
    down = spec.down_limit()
    p0 = float(cfg["capability"]["init_confidence"])
    return CapabilityState(
        rid=spec.rid,
        up_bound=up,
        down_bound=down,
        up_conf=p0 if up > 0 else 0.0,
        down_conf=p0 if down > 0 else 0.0,
        last_confirmed_t=t0,
        init_source="rated",
    )


def apply_capability_update(
    state: CapabilityState, res: AttributionResult, obs: Obs, cfg: dict[str, Any]
) -> dict[str, Any] | None:
    """确认「持续可用能力受限」后收缩对应方向的能力边界。返回更新事件（无更新则为 None）。"""
    if not res.allows_update:
        return None
    c = cfg["capability"]
    observed = abs(obs.p_meas)          # 观测到的可持续水平
    d = res.direction
    delta = float(c["conf_step"])

    if d == DIR_UP:
        return _shrink(state, obs, "up", observed, delta)
    return _shrink(state, obs, "down", observed, delta)


def _shrink(
    state: CapabilityState, obs: Obs, side: str, observed: float, delta: float
) -> dict[str, Any] | None:
    if side == "up":
        old = state.up_bound
        new = max(0.0, min(old, observed))
        if new >= old - 1e-9:
            state.up_conf = min(1.0, state.up_conf + delta * 0.25)
            return None
        state.up_bound = new
        state.up_conf = min(1.0, state.up_conf + delta)
    else:
        old = state.down_bound
        new = max(0.0, min(old, observed))
        if new >= old - 1e-9:
            state.down_conf = min(1.0, state.down_conf + delta * 0.25)
            return None
        state.down_bound = new
        state.down_conf = min(1.0, state.down_conf + delta)
    state.last_confirmed_t = obs.t
    return {"kind": "shrink", "rid": state.rid, "side": side, "old": old, "new": new, "t": obs.t}


# ---------------------------------------------------------------- 分级恢复


@dataclass
class RecoveryTrack:
    """单个资源、单个方向的恢复进度。"""

    rid: str
    direction: int
    confirm_streak: int = 0
    prev_confirmed: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


def _stage_targets(rated: float, cfg: dict[str, Any]) -> list[float]:
    return [round(rated * float(f), 3) for f in cfg["recovery"]["stage_fractions"]]


def maybe_recover(
    state: CapabilityState,
    spec: ResourceSpec,
    obs: Obs,
    track: RecoveryTrack,
    cfg: dict[str, Any],
) -> dict[str, Any] | None:
    """分级恢复：在存在正向试探请求且偏差落在带内的连续周期后，逐级扩大边界。

    任一级在确认后出现偏差 → 回退至该级恢复前的值（prev_confirmed）。
    """
    r = cfg["recovery"]
    band = float(cfg["attribution"]["deviation_band_kw"])
    confirm_n = int(r["confirm_n"])
    rated = spec.p_rated
    d = track.direction
    cur = state.bound(d)

    requested = (obs.p_req > 0) if d == DIR_UP else (obs.p_req < 0)
    if not requested:
        track.confirm_streak = 0
        return None

    # 闸 1：必须存在**试探请求**——要求幅度须超过当前边界一个判据带，否则"无偏差"不构成能力证据
    if abs(obs.p_req) <= cur + band:
        track.confirm_streak = 0
        return None

    # 闸 2：须已越过控制响应观察窗（与归因判据 3 同源），避免把响应过程误当作恢复证据
    win = float(cfg["attribution"]["response_window_s"])
    if obs.cmd_sent_t > 0.0 and (obs.t - obs.cmd_sent_t) < win:
        track.confirm_streak = 0
        return None

    dev = abs(obs.p_meas - obs.p_req)
    if dev > band:
        track.confirm_streak = 0
        # 恢复试探失败 → 回退至该级恢复前已确认的值
        if track.prev_confirmed is not None and cur > track.prev_confirmed + 1e-9:
            rollback = track.prev_confirmed
            _set_bound(state, d, rollback, float(r["post_recover_confidence"]))
            ev = {
                "kind": "recover_rollback",
                "rid": state.rid,
                "side": "up" if d == DIR_UP else "down",
                "old": cur,
                "new": rollback,
                "t": obs.t,
            }
            track.events.append(ev)
            track.prev_confirmed = None
            return ev
        return None

    # 偏差在带内 → 累计连续确认
    track.confirm_streak += 1
    if track.confirm_streak < confirm_n:
        return None

    targets = [x for x in _stage_targets(rated, cfg) if x > cur + 1e-9]
    if not targets:
        track.confirm_streak = 0
        return None
    nxt = targets[0]
    track.prev_confirmed = cur
    _set_bound(state, d, nxt, float(r["post_recover_confidence"]))
    track.confirm_streak = 0
    ev = {
        "kind": "recover_step",
        "rid": state.rid,
        "side": "up" if d == DIR_UP else "down",
        "old": cur,
        "new": nxt,
        "t": obs.t,
    }
    track.events.append(ev)
    return ev


def _set_bound(state: CapabilityState, d: int, value: float, conf: float) -> None:
    if d == DIR_UP:
        state.up_bound = value
        state.up_conf = conf
    else:
        state.down_bound = value
        state.down_conf = conf


# ---------------------------------------------------------------- 执行回写（模块 5 的一半）


def writeback_carrier(
    state: CapabilityState, obs: Obs, cfg: dict[str, Any]
) -> dict[str, Any] | None:
    """承接资源执行结果 → 回写**该承接资源自己**的能力状态（权 1【e】）。

    承接失败（实际执行结果不满足确认条件）时收缩其对应方向边界——即为权 7 的"维持该承接资源
    经实际执行结果修正后的能力边界"。
    """
    band = float(cfg["attribution"]["deviation_band_kw"])
    d = DIR_UP if obs.p_req > 0 else -DIR_UP
    under = abs(obs.p_req) - abs(obs.p_meas)
    if under < band:
        return None
    side = "up" if d == DIR_UP else "down"
    return _shrink(
        state, obs, side, abs(obs.p_meas), float(cfg["capability"]["conf_step"])
    )
