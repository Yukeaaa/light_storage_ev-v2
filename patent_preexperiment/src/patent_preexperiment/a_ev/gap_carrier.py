"""模块 3：Gap Mapping（权 1【d】前半、说明书 §8）
模块 4：Carrier Selection（权 1【d】后半、权 6、权 7、权 8、说明书 §9）

关键纪律（说明书 §8.2 / §8.3）：
- 缺口**由经归因确认的执行偏差**确定，**不由能力状态反推**；
- 站级 / 资源物理运行约束的作用点在**承接层**，不得反过来改变已观测出的缺口。
"""

from __future__ import annotations

from typing import Any

from .types import (
    DIR_DOWN,
    DIR_UP,
    AttributionResult,
    CapabilityState,
    Dispatch,
    Obs,
    ResourceSpec,
    StationGap,
)

# ---------------------------------------------------------------- 模块 3


def station_gap(confirmed: list[tuple[str, AttributionResult]]) -> StationGap:
    """由经确认的执行偏差做等效换算与方向聚合（同向累加 / 异向相抵取净）。"""
    up = sum(r.magnitude for _, r in confirmed if r.direction == DIR_UP)
    down = sum(r.magnitude for _, r in confirmed if r.direction == DIR_DOWN)
    rids = [rid for rid, _ in confirmed]
    if abs(up - down) < 1e-9:
        return StationGap(t=float("nan"), direction=0, magnitude=0.0, contributors=rids)
    if up > down:
        return StationGap(t=float("nan"), direction=DIR_UP, magnitude=up - down, contributors=rids)
    return StationGap(t=float("nan"), direction=DIR_DOWN, magnitude=down - up, contributors=rids)


# ---------------------------------------------------------------- 模块 4


def feasible_headroom(
    spec: ResourceSpec,
    obs: Obs,
    state: CapabilityState,
    direction: int,
    cfg: dict[str, Any],
) -> float:
    """其他可控资源在当前方向上的可承接贡献（受能力边界 + 资源物理运行约束限制）。"""
    ph = cfg["physical"]
    if obs.temp_c > float(ph["temp_max_c"]):
        return 0.0
    if direction == DIR_UP:
        if not spec.bidirectional:
            return 0.0
        if obs.soc <= float(ph["soc_min_discharge"]):
            return 0.0
        head = max(0.0, state.up_bound - max(0.0, obs.p_meas))
    else:
        if obs.soc >= float(ph["soc_max_charge"]):
            return 0.0
        head = max(0.0, state.down_bound - max(0.0, -obs.p_meas))
    return head


def _score(
    strategy: str,
    head: float,
    state: CapabilityState,
    direction: int,
    obs: Obs,
    spec: ResourceSpec,
    switch_count: int,
    cfg: dict[str, Any],
) -> float:
    conf = state.conf(direction)
    if strategy == "contribution":
        return head
    if strategy == "confidence":
        return conf
    if strategy == "min_switch":
        return -float(switch_count)
    if strategy == "soc_margin":
        # 向上承接偏好高 SOC，向下承接偏好低 SOC
        return obs.soc if direction == DIR_UP else (1.0 - obs.soc)
    w = cfg["carrier"]["weights"]
    soc_pref = obs.soc if direction == DIR_UP else (1.0 - obs.soc)
    return (
        float(w["contribution"]) * (head / max(1e-9, spec.p_rated))
        + float(w["confidence"]) * conf
        + float(w["soc_margin"]) * soc_pref
    )


def select_carriers(
    gap: StationGap,
    specs: dict[str, ResourceSpec],
    obs_by: dict[str, Obs],
    states: dict[str, CapabilityState],
    sources: set[str],
    excluded: set[str],
    switch_counts: dict[str, int],
    cfg: dict[str, Any],
    strategy: str | None = None,
) -> list[Dispatch]:
    """方向兼容性判断 → 基于可承接贡献与资源物理运行约束选择承接资源及其功率修正量。

    `sources` = 产生偏差的资源（不选自己承接，对应"其他可控资源"）；
    `excluded` = **当前功率修正事务**中被排除的资源（权 7，事务级、非持久资格）。
    """
    if gap.direction == 0 or gap.magnitude <= 0.0:
        return []
    strat = strategy or str(cfg["carrier"]["strategy"])
    band = float(cfg["attribution"]["deviation_band_kw"])

    cands: list[tuple[float, str, float]] = []
    for rid, spec in specs.items():
        if rid in sources or rid in excluded:
            continue
        obs = obs_by.get(rid)
        if obs is None:
            continue
        head = feasible_headroom(spec, obs, states[rid], gap.direction, cfg)
        if head < band:
            continue
        sc = _score(
            strat, head, states[rid], gap.direction, obs, spec,
            switch_counts.get(rid, 0), cfg,
        )
        cands.append((sc, rid, head))
    # 预设的确定性排序规则：得分降序，同分按 rid 字典序（保证可复现）
    cands.sort(key=lambda x: (-x[0], x[1]))

    dispatches: list[Dispatch] = []
    remaining = gap.magnitude
    for _, rid, head in cands:
        if remaining < band:
            break
        take = min(head, remaining)
        corr = take if gap.direction == DIR_UP else -take
        dispatches.append(
            Dispatch(
                t=gap.t,
                carrier_rid=rid,
                correction=corr,
                direction=gap.direction,
                reason=f"{strat}",
            )
        )
        remaining -= take
    return dispatches


def residual_gap(gap: StationGap, dispatches: list[Dispatch]) -> float:
    """经承接后仍存在的剩余待补偿站级功率缺口（权 8 的触发量）。"""
    if gap.direction == 0:
        return 0.0
    served = sum(abs(d.correction) for d in dispatches if d.direction == gap.direction)
    return max(0.0, gap.magnitude - served)
