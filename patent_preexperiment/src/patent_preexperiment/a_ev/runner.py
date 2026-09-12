"""A-EV 评估 harness：场景 × 策略 → 逐 episode 指标 → 汇总。

用法：
    PYTHONPATH=src python -m patent_preexperiment.a_ev.runner \
        --config ../configs/a_ev_v0.yaml --out ../results/raw/A_EV
或经 `experiments/a_ev/run.py` 调用。

**纪律**：
- 本 harness 在**合成场景**上运行，产出**不是效果结论**；
- 三类场景集严格分离：`evaluation`（正式评价）/ `commissioning`（标定，不评价）/
  `robustness`（稳健性矩阵）；
- 阈值遵循"先冻结产生规则、commissioning 后落数值并加锁"；`formal` 阶段要求已加锁。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pathlib
from dataclasses import asdict
from typing import Any

from .algorithm import AEVPipeline
from .baselines import ANoState, ANoWriteback, BaselineB0, BaselineB1, BaselineB2
from .metrics import EpisodeMetrics, evaluate
from .scenario import (
    ScenarioSpec,
    commissioning_scenarios,
    default_scenarios,
    default_site,
    robustness_scenarios,
    run_episode,
)
from .thresholds import build_thresholds
from .types import DIR_UP, Truth

POLICIES: dict[str, Any] = {
    "A": AEVPipeline,
    "A_no_state": ANoState,
    "A_no_writeback": ANoWriteback,
    "B0_no_gate": BaselineB0,
    "B1_static_derate": BaselineB1,
    "B2_error_rolling": BaselineB2,
}

#: 不维护持久能力状态 ⇒ EMUR 恒为 0（**空真**），报告中必须标注
MEMORYLESS = frozenset({"A_no_state", "B2_error_rolling"})

LOCK_KEYS = ("experiment.config_hash", "experiment.locked_at", "lock")


def load_cfg(path: str | pathlib.Path) -> dict[str, Any]:
    import yaml

    with open(path, encoding="utf-8") as fh:
        return dict(yaml.safe_load(fh) or {})


def config_hash(cfg: dict[str, Any]) -> str:
    """配置内容哈希（剔除加锁字段自身，保证可复算）。"""
    d = json.loads(json.dumps(cfg, sort_keys=True, default=str))
    exp = d.get("experiment", {})
    exp.pop("config_hash", None)
    exp.pop("locked_at", None)
    d.pop("lock", None)
    blob = json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def scenarios_for(cfg: dict[str, Any], which: str) -> list[ScenarioSpec]:
    if which == "evaluation":
        return default_scenarios(cfg)
    if which == "commissioning":
        return commissioning_scenarios(cfg)
    if which == "robustness":
        return robustness_scenarios(cfg)
    raise ValueError(f"unknown scenario set: {which}")


# ---------------------------------------------------------------- 汇总


def _rate(rs: list[EpisodeMetrics], num_attr: str, den_attr: str) -> dict[str, Any]:
    num = sum(getattr(r, num_attr) for r in rs)
    den = sum(getattr(r, den_attr) for r in rs)
    return {"numer": num, "denom": den, "rate": (num / den) if den else None}


def _mean(vals: list[float]) -> float | None:
    return (sum(vals) / len(vals)) if vals else None


def summarize(rows: list[EpisodeMetrics]) -> dict[str, Any]:
    per_policy: dict[str, Any] = {}
    for pname in POLICIES:
        rs = [r for r in rows if r.policy == pname]
        lim = [r for r in rs if r.name.startswith(("S3", "S5", "S6"))]
        per_policy[pname] = {
            "n_episodes": len(rs),
            "emur": _rate(rs, "emur_numer", "emur_denom"),
            "noise": _rate(rs, "noise_numer", "noise_denom"),
            "emur_by_class": _merge_classes(rs),
            # 主指标 2：**两个窗口同时汇报**（只报稳态会隐藏归因门的确认延迟成本）
            "resid_full_mean_kw": _mean([r.resid_full_mean_kw for r in lim
                                         if r.resid_full_mean_kw is not None]),
            "resid_full_energy_kwh": _mean([r.resid_full_energy_kwh for r in lim
                                            if r.resid_full_energy_kwh is not None]),
            "resid_steady_mean_kw": _mean([r.resid_steady_mean_kw for r in lim
                                           if r.resid_steady_mean_kw is not None]),
            "resid_steady_energy_kwh": _mean([r.resid_steady_energy_kwh for r in lim
                                              if r.resid_steady_energy_kwh is not None]),
            "pcc_resid_full_mean_kw": _mean([r.pcc_resid_full_mean_kw for r in lim
                                             if r.pcc_resid_full_mean_kw is not None]),
            "bound_err_mean_kw": _mean([r.bound_err_mean_kw for r in lim
                                        if r.bound_err_mean_kw is not None]),
            "bad_cmd_rate": _mean([r.bad_cmd_rate for r in rs if r.bad_cmd_rate is not None]),
            "cascade_count": sum(r.cascade_count for r in rs),
            "recovery_delay_s": next(
                (r.recovery_delay_s for r in rs if r.name == "S7_recovery_ok"), None
            ),
            "recovery_steps": sum(r.recovery_steps for r in rs if r.name == "S7_recovery_ok"),
            "recovery_false_steps": sum(
                r.recovery_false_steps for r in rs if r.name == "S8_recovery_fail"
            ),
            "emur_is_vacuous": pname in MEMORYLESS,
        }
    return per_policy


def _merge_classes(rs: list[EpisodeMetrics]) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    for r in rs:
        for k, v in (r.emur_by_class or {}).items():
            cur = out.setdefault(k, {"numer": 0, "denom": 0})
            cur["numer"] += v["numer"]
            cur["denom"] += v["denom"]
    for v in out.values():
        v["rate"] = (v["numer"] / v["denom"]) if v["denom"] else None
    return out


# ---------------------------------------------------------------- 主流程


def run_all(
    cfg: dict[str, Any],
    which: str = "evaluation",
    policies: list[str] | None = None,
) -> dict[str, Any]:
    if which == "commissioning":
        raise ValueError(
            "commissioning 集只做标定，不跑 A-vs-baseline 评价（见 run_commissioning）"
        )
    specs = default_site(cfg)
    thr = build_thresholds(cfg, specs)
    scenarios = scenarios_for(cfg, which)
    names = policies or list(POLICIES)
    if which == "robustness":
        # 稳健性矩阵只跑 A 与关键的整链基线（避免组合爆炸）
        names = policies or ["A", "B0_no_gate", "B1_static_derate", "B2_error_rolling"]
    rows: list[EpisodeMetrics] = []
    for scenario in scenarios:
        for pname in names:
            policy = POLICIES[pname](specs, cfg)
            ep = run_episode(scenario, specs, cfg, policy)
            rows.append(evaluate(ep, policy, cfg))
    return {
        "note": "合成场景机制验证，非效果结论；阈值须按预注册规则冻结",
        "scenario_set": which,
        "config_hash": config_hash(cfg),
        "thresholds": {
            "band_by_rid": thr.band_by_rid,
            "window_s": thr.window_s,
            "persistence_n": thr.persistence_n,
            "confirm_n": thr.confirm_n,
            "rule_based": thr.is_rule_based,
        },
        "episodes": [asdict(r) for r in rows],
        "summary": summarize(rows),
    }


def run_commissioning(cfg: dict[str, Any]) -> dict[str, Any]:
    """**标定**：只在 commissioning 场景集上测设备阶跃响应时间与噪声水平。

    不跑 A-vs-baseline 评价、不产出任何效果指标——这是"commissioning 数据不进入正式
    评价"的机械保证。产出的建议值随后按预注册规则写入锁文件。
    """
    specs = default_site(cfg)
    thr = build_thresholds(cfg, specs)
    out: list[dict[str, Any]] = []
    rise_by_rid: dict[str, list[float]] = {}
    noise_by_rid: dict[str, list[float]] = {}

    for sc in commissioning_scenarios(cfg):
        policy = AEVPipeline(specs, cfg)
        ep = run_episode(sc, specs, cfg, policy)
        dt = sc.dt
        plant = {(round(r.t, 3), r.rid): r for r in ep.plant}
        obs = {(round(o.t, 3), o.rid): o for o in ep.obs}

        # 阶跃响应时间：从试探下发起，真实输出进入目标 ±2% 阶跃幅度的时刻
        if sc.probe_at > 0.0:
            rid = sc.target_rid
            sign = 1.0 if sc.direction == DIR_UP else -1.0
            base = float(cfg["schedule"]["base_setpoint_kw"][rid])
            tgt = base + sign * sc.probe_magnitude
            tol = 0.02 * abs(sc.probe_magnitude)
            t_rise = None
            k = 0
            while sc.probe_at + k * dt <= sc.horizon:
                t = round(sc.probe_at + k * dt, 3)
                row = plant.get((t, rid))
                if row is not None and abs(row.p_meas_true - tgt) <= tol:
                    t_rise = t - sc.probe_at
                    break
                k += 1
            if t_rise is not None:
                rise_by_rid.setdefault(rid, []).append(t_rise)
            out.append({"scenario": sc.name, "rid": rid, "step_rise_s": t_rise})

        # 噪声：静止段上 (观测 − 真实) 的标准差
        n_noise = 0
        for (t, rid), o in obs.items():
            if t < 20.0:
                row = plant.get((t, rid))
                if row is not None:
                    noise_by_rid.setdefault(rid, []).append(o.p_meas - row.p_meas_true)
                    n_noise += 1
        out.append({"scenario": sc.name, "noise_samples": n_noise})

    def _p95(xs: list[float]) -> float | None:
        if not xs:
            return None
        s = sorted(xs)
        idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
        return s[idx]

    def _std(xs: list[float]) -> float | None:
        if len(xs) < 2:
            return None
        mu = sum(xs) / len(xs)
        return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))

    p95_by_rid = {rid: _p95(v) for rid, v in rise_by_rid.items()}
    sigma_by_rid = {rid: _std(v) for rid, v in noise_by_rid.items()}
    prov = cfg.get("thresholds_provenance") or {}
    band_rule = dict(prov.get("deviation_band", {}))
    win_rule = dict(prov.get("response_window", {}))
    p95_all = [v for v in p95_by_rid.values() if v is not None]
    p95_worst = max(p95_all) if p95_all else None

    suggested: dict[str, Any] = {
        "response_window_s": (
            None if p95_worst is None else p95_worst + float(win_rule.get("margin_s", 0.0))
        ),
        "band_by_rid": {
            s.rid: max(
                float(band_rule.get("meter_resolution_kw", 0.0)),
                float(band_rule.get("k_sigma", 0.0))
                * ((sigma_by_rid.get(s.rid) or 0.0) or float(band_rule.get("noise_sigma_kw", 0.0))),
                float(band_rule.get("alpha", 0.0)) * s.p_rated,
            )
            for s in specs
        },
    }
    return {
        "note": "标定结果；标定集与正式评价集严格分离，标定数据不得用于评价",
        "config_hash": config_hash(cfg),
        "steps": out,
        "p95_step_response_time_s": p95_by_rid,
        "noise_sigma_kw": sigma_by_rid,
        "suggested_thresholds": suggested,
        "scalar_fallback": {
            "band_by_rid": thr.band_by_rid,
            "window_s": thr.window_s,
            "persistence_n": thr.persistence_n,
            "confirm_n": thr.confirm_n,
        },
    }


def freeze(cfg: dict[str, Any], lock_path: pathlib.Path) -> dict[str, Any]:
    """运行标定 → 按预注册规则算出设备相关阈值 → 写入锁文件（不改配置本身）。"""
    import datetime as _dt

    rep = run_commissioning(cfg)
    lock = {
        "locked_at": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "config_hash": config_hash(cfg),
        "phase_at_lock": cfg.get("experiment", {}).get("phase"),
        "suggested_thresholds": rep["suggested_thresholds"],
        "p95_step_response_time_s": rep["p95_step_response_time_s"],
        "noise_sigma_kw": rep["noise_sigma_kw"],
        "note": "冻结后不得依正式结果调整；如需变更须记录变更理由并重新计算哈希",
    }
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    return lock


def check_lock(cfg: dict[str, Any], lock_path: pathlib.Path) -> tuple[bool, str]:
    if not lock_path.exists():
        return False, f"未找到锁文件 {lock_path}"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    cur = config_hash(cfg)
    if lock.get("config_hash") != cur:
        return False, f"配置哈希不匹配：锁={lock.get('config_hash')[:12]} 当前={cur[:12]}"
    return True, f"锁校验通过（{lock.get('locked_at')}）"


def write_outputs(
    result: dict[str, Any], out_dir: str | pathlib.Path, tag: str = "a_ev_v0_2"
) -> tuple[pathlib.Path, pathlib.Path]:
    d = pathlib.Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    js = d / f"{tag}_summary.json"
    js.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    cs = d / f"{tag}_episodes.csv"
    with open(cs, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        cols = [
            "name", "policy", "phase", "emur_numer", "emur_denom", "emur_rate",
            "noise_numer", "noise_denom", "noise_rate",
            "resid_full_mean_kw", "resid_full_energy_kwh",
            "resid_steady_mean_kw", "resid_steady_energy_kwh",
            "bound_err_mean_kw", "bad_cmd_rate", "cascade_count",
            "recovery_delay_s", "recovery_steps", "recovery_false_steps",
            "pcc_resid_full_mean_kw",
        ]
        w.writerow(cols)
        for e in result["episodes"]:
            w.writerow([e.get(c) for c in cols])
    return js, cs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A-EV 评估 harness（合成场景，非效果结论）")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default="results/raw/A_EV")
    ap.add_argument("--set", dest="which", default="evaluation",
                    choices=["evaluation", "robustness", "commissioning"])
    ap.add_argument("--policy", action="append", default=None,
                    help="只跑指定策略（可重复）；默认全部")
    ap.add_argument("--freeze", action="store_true", help="跑标定并写锁文件")
    ap.add_argument("--check-lock", action="store_true", help="校验配置与锁文件一致")
    args = ap.parse_args(argv)

    cfg = load_cfg(args.config)
    lock_path = pathlib.Path(args.config).with_suffix(".lock.json")
    phase = str(cfg.get("experiment", {}).get("phase", "synthetic_regression"))
    locked = bool(cfg.get("experiment", {}).get("thresholds_locked"))

    if args.freeze:
        lock = freeze(cfg, lock_path)
        print(f"[A-EV] 标定完成 → 锁文件 {lock_path}")
        print(json.dumps(lock["suggested_thresholds"], ensure_ascii=False, indent=2))
        return 0

    if args.check_lock:
        ok, msg = check_lock(cfg, lock_path)
        print(f"[A-EV] {msg}")
        return 0 if ok else 2

    if phase == "formal" and not locked:
        print("[A-EV] 拒绝运行：phase=formal 但 thresholds_locked=false（须先 --freeze 并加锁）")
        return 3
    if args.which == "commissioning":
        rep = run_commissioning(cfg)
        js = pathlib.Path(args.out) / "a_ev_commissioning.json"
        js.parent.mkdir(parents=True, exist_ok=True)
        js.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[A-EV] commissioning 标定结果 -> {js}")
        print(json.dumps(rep["suggested_thresholds"], ensure_ascii=False, indent=2))
        return 0

    result = run_all(cfg, args.which, args.policy)
    tag = "a_ev_v0_2" if args.which == "evaluation" else f"a_ev_v0_2_{args.which}"
    js, cs = write_outputs(result, args.out, tag)
    print(f"[A-EV] [{args.which}] config_hash={result['config_hash'][:12]} -> {js}")
    print(f"[A-EV] episodes -> {cs}")
    for pname, s in result["summary"].items():
        if s["n_episodes"] == 0:
            continue
        print(
            f"  {pname:16s} EMUR={_fmt4(s['emur']['rate'])} ({s['emur']['numer']}/"
            f"{s['emur']['denom']}){' *空真' if s['emur_is_vacuous'] else ''}  "
            f"RESID_full={_fmt(s['resid_full_mean_kw'])}  "
            f"RESID_steady={_fmt(s['resid_steady_mean_kw'])}  "
            f"BADCMD={_fmt(s['bad_cmd_rate'])}  cascade={s['cascade_count']}"
        )
    return 0


def _fmt(v: Any) -> str:
    return "n/a" if v is None else f"{v:.2f}"


def _fmt4(v: Any) -> str:
    return "n/a" if v is None else f"{v:.4f}"


__all__ = ["POLICIES", "Truth", "check_lock", "config_hash", "freeze", "load_cfg",
           "run_all", "run_commissioning", "summarize", "write_outputs"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
