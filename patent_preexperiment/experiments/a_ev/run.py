"""A-EV 场景台入口（A 案算法参考实现 + 可控真值场景）— V0.2 pre-freeze。

用法（在 patent_preexperiment/ 下）：
    PYTHONPATH=src python experiments/a_ev/run.py                      # 正式评价集
    PYTHONPATH=src python experiments/a_ev/run.py --set robustness     # 稳健性矩阵
    PYTHONPATH=src python experiments/a_ev/run.py --set commissioning  # 标定（不评价）
    PYTHONPATH=src python experiments/a_ev/run.py --freeze             # 标定并写锁文件
    PYTHONPATH=src python experiments/a_ev/run.py --check-lock         # 校验锁

⚠️ 本实验为**机制与管线验证**，运行于**合成场景**：
   - 产出**不是效果结论**，不得写入权利要求或申请文本；
   - 不得用于替代 A 轨 R5 7/7；
   - 阈值遵循「先冻结产生规则 → commissioning 落数值并加锁」，正式实验后不得依结果调整。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from patent_preexperiment.a_ev.runner import (  # noqa: E402
    LockError,
    check_lock,
    freeze,
    load_cfg,
    run_all,
    run_commissioning,
    write_outputs,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A-EV 机制与管线验证（合成场景，非效果结论）")
    ap.add_argument("--config", default=str(ROOT / "configs" / "a_ev_v0.yaml"))
    ap.add_argument("--out", default=str(ROOT / "results" / "raw" / "A_EV"))
    ap.add_argument("--set", dest="which", default="evaluation",
                    choices=["evaluation", "robustness", "commissioning"])
    ap.add_argument("--freeze", action="store_true", help="跑标定并写锁文件")
    ap.add_argument("--check-lock", action="store_true", help="校验配置与锁文件一致")
    args = ap.parse_args(argv)

    cfg = load_cfg(args.config)
    lock_path = pathlib.Path(args.config).with_suffix(".lock.json")
    out = pathlib.Path(args.out)
    phase = str(cfg.get("experiment", {}).get("phase", "synthetic_regression"))

    if args.freeze:
        if phase == "formal":
            print("[A-EV] 拒绝冻结：phase=formal 下不得重新标定（须按变更纪律回退 phase 重走流程）")
            return 3
        try:
            lock = freeze(cfg, lock_path)
        except LockError as e:
            print(f"[A-EV] 拒绝冻结：{e}")
            return 3
        print(f"[A-EV] 标定完成 → 锁文件 {lock_path}")
        print(json.dumps(lock["resolved_thresholds"], ensure_ascii=False, indent=2))
        return 0

    if args.check_lock:
        ok, msg = check_lock(cfg, lock_path)
        print(f"[A-EV] {msg}")
        return 0 if ok else 2

    if phase == "formal" and args.which == "commissioning":
        print("[A-EV] 拒绝运行：formal 阶段不再运行标定集（commissioning 与正式评价严格分离）")
        return 3
    if phase == "formal":
        # formal 阶段每次运行都强制验锁：缺锁 / 哈希不匹配 / resolved 缺失 → 拒绝
        ok, msg = check_lock(cfg, lock_path)
        if not ok:
            print(f"[A-EV] 拒绝运行：phase=formal 且锁校验失败 —— {msg}")
            return 3

    if args.which == "commissioning":
        rep = run_commissioning(cfg)
        out.mkdir(parents=True, exist_ok=True)
        js = out / "a_ev_commissioning.json"
        js.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[A-EV] [commissioning] 标定结果 -> {js}")
        print(f"  p95 阶跃响应时间(s): {rep['p95_step_response_time_s']}")
        print(f"  噪声 σ(kW): {rep['noise_sigma_kw']}")
        sug = json.dumps(rep["suggested_thresholds"], ensure_ascii=False)
        print(f"  按预注册规则建议阈值: {sug}")
        return 0

    try:
        result = run_all(cfg, args.which, None, lock_path)
    except LockError as e:
        print(f"[A-EV] 拒绝运行：{e}")
        return 3
    tag = "a_ev_v0_2" if args.which == "evaluation" else f"a_ev_v0_2_{args.which}"
    js, cs = write_outputs(result, out, tag)
    print(f"[A-EV] [{args.which}] config_hash={result['config_hash'][:12]}")
    print(f"[A-EV] summary  -> {js}")
    print(f"[A-EV] episodes -> {cs}")
    t = result["thresholds"]
    src = {"lock": "锁(resolved)", "rules": "规则"}.get(t["source"], "标量回落")
    print(f"      阈值来源={src}  "
          f"band={ {k: round(v, 3) for k, v in t['band_by_rid'].items()} }  "
          f"window={t['window_s']}s  persistence={t['persistence_n']}  confirm={t['confirm_n']}")
    print(f"{'policy':16s} {'EMUR':>8s} {'RLD_full':>9s} {'RLD_stdy':>9s} {'BOUND_ERR':>10s} "
          f"{'BADCMD':>7s} {'casc':>5s} {'recov_d':>8s} {'recov_f':>8s}")
    for pname, s in result["summary"].items():
        if s["n_episodes"] == 0:
            continue
        emur = s["emur"]["rate"]
        mark = " *空真" if s["emur_is_vacuous"] else ""
        print(
            f"{pname:16s} {_f4(emur) + mark:>8s} {_f(s['resid_full_mean_kw']):>9s} "
            f"{_f(s['resid_steady_mean_kw']):>9s} {_f(s['bound_err_mean_kw']):>10s} "
            f"{_f(s['bad_cmd_rate']):>7s} {s['cascade_count']:>5d} "
            f"{_f(s['recovery_delay_s']):>8s} {s['recovery_false_steps']:>8d}"
        )
    return 0


def _f(v: Any) -> str:
    return "n/a" if v is None else f"{v:.2f}"


def _f4(v: Any) -> str:
    return "n/a" if v is None else f"{v:.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
