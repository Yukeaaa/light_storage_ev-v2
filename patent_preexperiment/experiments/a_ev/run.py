"""A-EV 场景台入口（A 案算法参考实现 + 可控真值场景）。

用法（在 patent_preexperiment/ 下）：
    PYTHONPATH=src python experiments/a_ev/run.py --config configs/a_ev_v0.yaml

⚠️ 本实验为**机制与管线验证**，运行于**合成场景**：
   - 产出**不是效果结论**，不得写入权利要求或申请文本；
   - 不得用于替代 A 轨 R5 7/7；
   - 阈值取自配置且为候选值，须在正式实验前冻结。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from patent_preexperiment.a_ev.runner import load_cfg, run_all, write_outputs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A-EV 机制与管线验证（合成场景，非效果结论）")
    ap.add_argument("--config", default=str(ROOT / "configs" / "a_ev_v0.yaml"))
    ap.add_argument("--out", default=str(ROOT / "results" / "raw" / "A_EV"))
    args = ap.parse_args(argv)

    cfg = load_cfg(args.config)
    result = run_all(cfg)
    js, cs = write_outputs(result, args.out)

    print(f"[A-EV] summary -> {js}")
    print(f"[A-EV] episodes -> {cs}")
    print(f"{'policy':20s} {'EMUR':>8s} {'NOISE':>8s} {'RESID(kW)':>10s} {'BOUND_ERR':>10s} "
          f"{'cascade':>8s} {'recov_delay':>12s} {'recov_false':>12s}")
    for pname, s in result["summary"].items():
        emur = s["emur"]["rate"]
        print(
            f"{pname:20s} {('n/a' if emur is None else f'{emur:.4f}'):>8s} "
            f"{_f(s['noise']['rate']):>8s} "
            f"{_f(s['resid_mean_kw']):>10s} {_f(s['bound_err_mean_kw']):>10s} "
            f"{s['cascade_count']:>8d} {_f(s['recovery_delay_s']):>12s} "
            f"{s['recovery_false_steps']:>12d}"
        )
    return 0


def _f(v) -> str:
    return "n/a" if v is None else f"{v:.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
