"""A-EV 评估 harness：场景 × 策略 → 逐 episode 指标 → 汇总。

用法：
    PYTHONPATH=src python -m patent_preexperiment.a_ev.runner \
        --config ../configs/a_ev_v0.yaml --out ../results/raw/A_EV
或经 `experiments/a_ev/run.py` 调用。

**纪律**：本 harness 在**合成场景**上运行，产出**不是效果结论**；
阈值取自配置且为**候选值，须在正式实验前冻结**。
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
from dataclasses import asdict
from typing import Any

from .algorithm import AEVPipeline
from .baselines import BaselineB0, BaselineB1, BaselineB2
from .metrics import EpisodeMetrics, evaluate
from .scenario import default_scenarios, default_site, run_episode

POLICIES: dict[str, Any] = {
    "A": AEVPipeline,
    "B0_no_gate": BaselineB0,
    "B1_static_derate": BaselineB1,
    "B2_error_rolling": BaselineB2,
}


def load_cfg(path: str | pathlib.Path) -> dict[str, Any]:
    import yaml

    with open(path, encoding="utf-8") as fh:
        return dict(yaml.safe_load(fh) or {})


def run_all(cfg: dict[str, Any], strategies: list[str] | None = None) -> dict[str, Any]:
    specs = default_site(cfg)
    scenarios = default_scenarios(cfg)
    _ = strategies  # 保留参数位：将来可只跑部分策略
    rows: list[EpisodeMetrics] = []

    for scenario in scenarios:
        for pname in POLICIES:
            policy = POLICIES[pname](specs, cfg)
            ep = run_episode(scenario, specs, cfg, policy)
            rows.append(evaluate(ep, policy, cfg))

    # ---------------- 汇总
    def _rate(rs: list[EpisodeMetrics], num_attr: str, den_attr: str) -> dict[str, Any]:
        num = sum(getattr(r, num_attr) for r in rs)
        den = sum(getattr(r, den_attr) for r in rs)
        return {"numer": num, "denom": den, "rate": (num / den) if den else None}

    per_policy = {}
    for pname in POLICIES:
        rs = [r for r in rows if r.policy == pname]
        locals_ = [r for r in rs if r.name.startswith(("S3", "S5", "S6"))]
        resid = [r.resid_mean_kw for r in locals_ if r.resid_mean_kw is not None]
        energy = [r.resid_energy_kwh for r in locals_ if r.resid_energy_kwh is not None]
        berr = [r.bound_err_mean_kw for r in locals_ if r.bound_err_mean_kw is not None]
        bad = [r.bad_cmd_rate for r in rs if r.bad_cmd_rate is not None]
        rec_ok = [r for r in rs if r.name == "S7_recovery_ok"]
        rec_fail = [r for r in rs if r.name == "S8_recovery_fail"]
        per_policy[pname] = {
            "emur": _rate(rs, "emur_numer", "emur_denom"),
            "noise": _rate(rs, "noise_numer", "noise_denom"),
            "emur_by_class": _merge_classes(rs),
            "resid_mean_kw": (sum(resid) / len(resid)) if resid else None,
            "resid_energy_kwh": (sum(energy) / len(energy)) if energy else None,
            "bound_err_mean_kw": (sum(berr) / len(berr)) if berr else None,
            "bad_cmd_rate": (sum(bad) / len(bad)) if bad else None,
            "cascade_count": sum(r.cascade_count for r in rs),
            "recovery_delay_s": (rec_ok[0].recovery_delay_s if rec_ok else None),
            "recovery_steps": sum(r.recovery_steps for r in rec_ok),
            "recovery_false_steps": sum(r.recovery_false_steps for r in rec_fail),
        }

    return {
        "note": "合成场景机制验证，非效果结论；阈值须实验前冻结",
        "config": cfg,
        "episodes": [asdict(r) for r in rows],
        "summary": per_policy,
    }


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


def write_outputs(
    result: dict[str, Any], out_dir: str | pathlib.Path
) -> tuple[pathlib.Path, pathlib.Path]:
    d = pathlib.Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    js = d / "a_ev_v0_summary.json"
    js.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    cs = d / "a_ev_v0_episodes.csv"
    with open(cs, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        cols = [
            "name", "policy", "emur_numer", "emur_denom", "emur_rate", "noise_numer", "noise_denom",
            "noise_rate", "resid_mean_kw", "resid_energy_kwh",
            "bound_err_mean_kw", "bad_cmd_rate", "cascade_count", "recovery_delay_s",
            "recovery_false_steps", "pcc_resid_mean_kw",
        ]
        w.writerow(cols)
        for e in result["episodes"]:
            w.writerow([e.get(c) for c in cols])
    return js, cs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A-EV 评估 harness（合成场景，非效果结论）")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default="results/raw/A_EV")
    args = ap.parse_args(argv)
    cfg = load_cfg(args.config)
    result = run_all(cfg)
    js, cs = write_outputs(result, args.out)
    print(f"[A-EV] summary -> {js}")
    print(f"[A-EV] episodes -> {cs}")
    for pname, s in result["summary"].items():
        emur = s["emur"]
        print(
            f"  {pname:18s} EMUR={_fmt4(emur['rate'])} ({emur['numer']}/{emur['denom']})  "
            f"NOISE={_fmt4(s['noise']['rate'])}  RESID={_fmt(s['resid_mean_kw'])} kW  "
            f"BOUND_ERR={_fmt(s['bound_err_mean_kw'])} kW  cascade={s['cascade_count']}  "
            f"recov_delay={_fmt(s['recovery_delay_s'])}s  recov_false={s['recovery_false_steps']}"
        )
    return 0


def _fmt(v: Any) -> str:
    return "n/a" if v is None else f"{v:.2f}"


def _fmt4(v: Any) -> str:
    return "n/a" if v is None else f"{v:.4f}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
