#!/usr/bin/env python3
"""H-A5 cheap-knockout —— 退化 provenance 场景（探索轨 3-a 第二轮）。

口径声明（勿越界）
------------------
* 本脚本只做 **机制可行性 knock-out**，**不是**收益量化、**不是**部署证据。
* 场景为 **人工构造的退化 LP**，不含任何真实数据；结论**不得**用于 A 轨 R5 7/7 论证。
* 只回答一个问题：

      在"容量保障等级（firm / conditional）撤回"时，一个已承诺服务的
      **容量来源（provenance）**是否为复现某一控制轨迹所必需？
      即：是否存在**不携带 provenance 的普通方案**能给出**完全相同**的 P_i(t)？

* 判据（用户生死门）：若存在 → 该机制主要是账务/业务语义或普通优先级设计，
  **不应**继续包装成技术机制。

策略
----
B5-recompute      每周期从零重解，无 provenance。并列最优时用两种规范 tie-break：
                  proportional（等权对称解）/ identity_order（按服务顺序优先）。
B6-parametrized   每周期 MILP + **上周期类别分解作为参数携带**（最强常规基线）。
H-A5-state        持久台账：commit -> consume -> invalidate/reallocate -> recover。

运行
----
    ..\\..\\..\\venv\\Scripts\\python.exe run.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

STEP = 1  # kW 网格；退化 LP 用整数网格可精确枚举，无需外部求解器

# --------------------------------------------------------------------------- #
# 场景定义
# --------------------------------------------------------------------------- #


@dataclass
class Service:
    """一个已承诺服务。

    ``firm`` / ``cond`` 是 **承诺时刻** 写入的容量来源分解（firm + cond == demand）。
    该分解在承诺时刻通常是**退化**的 —— 目标函数不唯一确定它（见 commit_time_tied_optima）。
    """

    name: str
    label: str
    demand: int          # kW，本周期最大有用功率
    firm: int            # kW，承诺时由 firm capacity 支撑的份额
    cond: int            # kW，承诺时由 conditional capacity 支撑的份额


@dataclass
class Scenario:
    name: str
    description: str
    c_firm: int
    c_cond: list[int]
    services: list[Service]


SCENARIOS: list[Scenario] = [
    Scenario(
        name="S1_single_withdrawal_symmetric",
        description=(
            "对称双服务、单次撤回。A 完全 firm 支撑且不可中断，B 完全 cond 支撑。"
            "用于暴露：目标函数对来源分解完全不敏感（承诺时刻退化）。"
        ),
        c_firm=100,
        c_cond=[100, 0, 100],
        services=[
            Service("A", "critical", 80, 80, 0),
            Service("B", "deferrable", 80, 0, 80),
        ],
    ),
    Scenario(
        name="S2_split_funding_episode",
        description=(
            "三服务、**部分混合支撑**、两周期撤回 episode。"
            "B 的承诺跨两个保障等级（50 firm + 30 cond），C 全部 cond 支撑。"
            "检验：按 **来源混合** 作废 与 按 **服务身份/顺序** 作废 是否给出相同轨迹。"
        ),
        c_firm=100,
        c_cond=[100, 0, 0, 100],
        services=[
            Service("A", "critical", 50, 50, 0),
            Service("B", "logistics_deadline", 80, 50, 30),
            Service("C", "deferrable", 20, 0, 20),
        ],
    ),
]


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #


def commit_time_tied_optima(svc: list[Service], c_firm: int, c_cond: int) -> list[tuple[int, ...]]:
    """承诺时刻的并列最优 **来源分解** 枚举。

    前提：容量足以满足全部需求（总量唯一 = demand），故只有来源分解退化。
    返回 (f_1,c_1,f_2,c_2,...) 的完整最优集。
    """
    if sum(s.demand for s in svc) > c_firm + c_cond:
        return []
    out: list[tuple[int, ...]] = []

    def rec(i: int, sf: int, sc: int, acc: list[tuple[int, int]]) -> None:
        if sf > c_firm or sc > c_cond:
            return
        if i == len(svc):
            out.append(tuple(v for pair in acc for v in pair))
            return
        d = svc[i].demand
        for f in range(0, d + 1, STEP):
            rec(i + 1, sf + f, sc + (d - f), acc + [(f, d - f)])

    rec(0, 0, 0, [])
    return sorted(set(out))


def allocate_headroom(
    out: list[tuple[int, int]],
    svc: list[Service],
    c_firm: int,
    c_cond: int,
) -> list[tuple[int, int]]:
    """把剩余容量按"先 firm 后 cond"补给最欠服务的服务（等权目标）。

    记账语义：firm 余量产生的份额记为 firm 支撑，cond 余量产生的记为 cond 支撑。
    """
    res = list(out)
    served = [f + c for f, c in res]
    firm_head = c_firm - sum(f for f, _ in res)
    cond_head = c_cond - sum(c for _, c in res)
    for idx, s in enumerate(svc):
        gap = s.demand - served[idx]
        if gap <= 0:
            continue
        f, c = res[idx]
        g = min(gap, max(firm_head, 0))
        f += g
        gap -= g
        firm_head -= g
        g = min(gap, max(cond_head, 0))
        c += g
        cond_head -= g
        res[idx] = (f, c)
    return res


def b5_recompute(svc: list[Service], c_firm: int, c_cond: int, tie: str) -> list[int]:
    """无 provenance。每周期从零重解，并列最优用规范 tie-break 挑选。"""
    cap = c_firm + c_cond
    dem = [s.demand for s in svc]
    total = sum(dem)
    if total <= cap:
        return dem[:]
    if tie == "proportional":
        return [int(d * cap // total) for d in dem]
    if tie == "identity_order":
        out: list[int] = []
        remain = cap
        for d in dem:
            give = min(d, remain)
            out.append(give)
            remain -= give
        return out
    raise ValueError(tie)


def b6_parametrized(
    svc: list[Service],
    c_firm: int,
    c_cond: int,
    prev: list[tuple[int, int]],
    prev_cond_cap: int,
) -> list[tuple[int, int]]:
    """每周期 MILP + 上周期类别分解作为 **参数** 携带（最强常规基线）。"""
    scale = (c_cond / prev_cond_cap) if prev_cond_cap > 0 else 0.0
    out: list[tuple[int, int]] = []
    for (f, c), s in zip(prev, svc, strict=True):
        c2 = min(int(c * scale) if scale > 0 else 0, s.demand)
        f2 = min(f, s.demand - c2)
        out.append((f2, c2))
    sf = sum(f for f, _ in out)
    if sf > c_firm and sf > 0:
        out = [(int(f * c_firm // sf), c) for f, c in out]
    return allocate_headroom(out, svc, c_firm, c_cond)


def ha5_state(
    svc: list[Service],
    c_firm: int,
    c_cond: int,
    ledger: list[dict],
) -> tuple[list[tuple[int, int]], list[dict]]:
    """持久台账 commit -> consume -> invalidate/reallocate -> recover。

    ledger[j] = {"firm", "cond", "invalidated_cond", "lineage"}
    与 B6 的差别只有两处（都发生在撤回/恢复事件上）：
      * invalidate：按 **来源混合** 作废 cond 支撑的份额；
      * recover   ：C_cond 回升时按被作废量归还 cond 义务（B6 无此规则）。
    """
    work = [dict(e) for e in ledger]

    # --- recover --------------------------------------------------------- #
    total_inv = sum(e["invalidated_cond"] for e in work)
    if c_cond > 0 and total_inv > 0:
        credit = min(c_cond, total_inv)
        for e in work:
            inv = e["invalidated_cond"]
            back = int(inv * credit // total_inv) if total_inv else 0
            e["cond"] += back
            e["invalidated_cond"] = inv - back
            if back:
                e["lineage"].append(f"recover:+{back}")

    # --- invalidate ------------------------------------------------------ #
    cur_cond = sum(e["cond"] for e in work)
    if c_cond < cur_cond and cur_cond > 0:
        ratio = c_cond / cur_cond
        for e in work:
            before = e["cond"]
            after = int(before * ratio)
            if before - after:
                e["invalidated_cond"] += before - after
                e["lineage"].append(f"invalidate:-{before - after}")
            e["cond"] = after

    # --- consume（按需求上限截断）--------------------------------------- #
    out: list[tuple[int, int]] = []
    for e, s in zip(work, svc, strict=True):
        f = min(e["firm"], s.demand)
        c = min(e["cond"], s.demand - f)
        out.append((f, c))

    sf = sum(f for f, _ in out)
    if sf > c_firm and sf > 0:
        out = [(int(f * c_firm // sf), c) for f, c in out]

    # --- reallocate（firm 余量 -> firm 支撑；cond 余量 -> cond 支撑）----- #
    out = allocate_headroom(out, svc, c_firm, c_cond)

    new_ledger: list[dict] = []
    for (f, c), e in zip(out, work, strict=True):
        e["firm"], e["cond"] = f, c
        e["lineage"] = list(e["lineage"])
        new_ledger.append(e)
    return out, new_ledger


# --------------------------------------------------------------------------- #
# 指标
# --------------------------------------------------------------------------- #


def trajectory_delta(a: list[list[int]], b: list[list[int]]) -> int:
    return max(
        (abs(x - y) for ra, rb in zip(a, b, strict=True) for x, y in zip(ra, rb, strict=True)),
        default=0,
    )


def wrong_invalidation(svc: list[Service], served: list[int]) -> int:
    """被削减到 **低于 firm 支撑份额** 的电量（kWh，Δt=1h）—— 来源规则禁止的削减。"""
    return sum(max(0, s.firm - x) for s, x in zip(svc, served, strict=True))


def commitment_reversal(traj: list[list[int]]) -> int:
    n = 0
    for j in range(len(traj[0])):
        for t in range(1, len(traj) - 1):
            if traj[t][j] < traj[t - 1][j] and traj[t + 1][j] > traj[t][j]:
                n += 1
    return n


def recovery_inconsistency(traj: list[list[int]], pre: list[int], restore_t: int) -> int:
    for k, row in enumerate(traj[restore_t:], start=0):
        if row == pre:
            return k
    return -1


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def run_scenario(sc: Scenario) -> dict:
    svc = sc.services
    n = len(sc.c_cond)

    ties = commit_time_tied_optima(svc, sc.c_firm, sc.c_cond[0])

    keys = ["B5-proportional", "B5-identity_order", "B6-parametrized", "H-A5-state"]
    traj: dict[str, list[list[int]]] = {k: [] for k in keys}
    wrong: dict[str, int] = {k: 0 for k in keys}
    flips = 0

    prev_b6 = [(s.firm, s.cond) for s in svc]
    ledger = [
        {"firm": s.firm, "cond": s.cond, "invalidated_cond": 0, "lineage": []} for s in svc
    ]
    prev_cond_cap = sc.c_cond[0]

    for t in range(n):
        cc = sc.c_cond[t]
        rows = {
            "B5-proportional": b5_recompute(svc, sc.c_firm, cc, "proportional"),
            "B5-identity_order": b5_recompute(svc, sc.c_firm, cc, "identity_order"),
            "B6-parametrized": [f + c for f, c in b6_parametrized(
                svc, sc.c_firm, cc, prev_b6, prev_cond_cap)],
        }
        out_pairs, new_ledger = ha5_state(svc, sc.c_firm, cc, ledger)
        rows["H-A5-state"] = [f + c for f, c in out_pairs]

        for k, row in rows.items():
            traj[k].append(row)
            wrong[k] += wrong_invalidation(svc, row)

        canon = [
            (s.firm, int(s.cond * cc // sc.c_cond[0]) if sc.c_cond[0] else 0) for s in svc
        ]
        if [(e["firm"], e["cond"]) for e in new_ledger] != canon:
            flips += 1

        prev_b6 = b6_parametrized(svc, sc.c_firm, cc, prev_b6, prev_cond_cap)
        ledger = new_ledger
        prev_cond_cap = cc

    restore_t = next((i for i, c in enumerate(sc.c_cond) if i > 0 and c > 0), n - 1)
    pre = traj["H-A5-state"][0]

    return {
        "scenario": sc.name,
        "description": sc.description,
        "c_firm": sc.c_firm,
        "c_cond": sc.c_cond,
        "services": [
            {"name": s.name, "label": s.label, "demand": s.demand, "firm": s.firm, "cond": s.cond}
            for s in svc
        ],
        "commit_time_tied_optima": len(ties),
        "trajectories": traj,
        "metrics": {
            "N_provenance_flip": flips,
            "E_wrong_invalidation_kWh": wrong,
            "N_commitment_reversal": {k: commitment_reversal(v) for k, v in traj.items()},
            "T_recovery_inconsistency": {
                k: recovery_inconsistency(v, pre, restore_t) for k, v in traj.items()
            },
            "max_trajectory_delta_vs_HA5": {
                k: trajectory_delta(traj["H-A5-state"], v) for k, v in traj.items()
            },
            "reproduces_HA5_exactly": [
                k for k in keys if traj[k] == traj["H-A5-state"]
            ],
        },
    }


def main() -> None:
    out = {
        "caliber": "mechanism-plausibility only; synthetic degenerate LP; not deployment evidence",
        "results": [run_scenario(sc) for sc in SCENARIOS],
    }

    dest = Path(__file__).resolve().parents[2] / "results" / "raw" / "ha5_knockout"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "knockout_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines: list[str] = ["# H-A5 cheap-knockout —— 原始结果", ""]
    for r in out["results"]:
        lines += [
            f"## {r['scenario']}",
            "",
            r["description"],
            "",
            f"- 输入：C_firm={r['c_firm']} kW，C_cond={r['c_cond']} kW",
            f"- 承诺时刻并列最优来源分解数 = **{r['commit_time_tied_optima']}**",
            "",
            "| 策略 | " + " | ".join(f"P{i+1}" for i in range(len(r["c_cond"]))) + " |",
            "|---|" + "---|" * len(r["c_cond"]),
        ]
        for k, v in r["trajectories"].items():
            lines.append(f"| {k} | " + " | ".join(str(row) for row in v) + " |")
        m = r["metrics"]
        lines += [
            "",
            f"- N_provenance_flip = {m['N_provenance_flip']}",
            f"- E_wrong_invalidation = {m['E_wrong_invalidation_kWh']} kWh",
            f"- N_commitment_reversal = {m['N_commitment_reversal']}",
            f"- T_recovery_inconsistency = {m['T_recovery_inconsistency']}",
            f"- 轨迹最大偏差 vs H-A5 = {m['max_trajectory_delta_vs_HA5']}",
            f"- **与 H-A5 轨迹逐点相同者**：{m['reproduces_HA5_exactly']}",
            "",
        ]
    (dest / "knockout_result.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n[written] {dest}")


if __name__ == "__main__":
    main()
