"""E3-Full（R1 / E0F-06 E3 部分）：双轨人口按 train/validation/test 分别复现 E3 机会审计。

R1 协议（审查结论28 定稿 + 审查结论26 治理）：
- 双轨人口：E3-M = caltech main（L1∧role==main）；E3-X = jpl current_only
  （L1∧role==current_only_fallback∧field_mode==current_only）。逐 split 硬切分，各自独立统计。
- 沿用 K1 E3-Lite 冻结管线（allocation.opportunity：build_cycles→pool_stats→
  proxies→eligible_mask→candidate_windows，指标 A = 并发候选修正窗口，预算差值，无吸收假设）。
- 主基线 A2_prev_actual 两池一致；caltech 代理集 [A0_avg, A2, A3]，jpl [A2, A3]。
- 门结构（gate.py）：E3-M 主门 / E3-X 跨池佐证门 / 复杂模型止损门（A2/A3 消除>80%）。
- 治理：code-only commit → clean worktree → test 只跑一次 → evidence-only commit
  （assert_formal_test_not_exposed 锁；formal_exit_code fail-closed）。
- 随机种子：e0_full.yaml seeds（bootstrap=42, n_boot=2000）。

术语纪律：只称"预算差值/并发候选修正窗口"，不称"可回收能力"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.e3_full.gate import (
    assert_formal_test_not_exposed,
    caltech_split_gate,
    cross_pool_gate,
    formal_exit_code,
    formal_verdict,
    frozen_gate_exit_code,
    git_provenance,
    jpl_split_gate,
)
from patent_preexperiment.e3_full.loader import (
    load_caltech_main,
    load_jpl_current_only,
    split_minutes,
)
from patent_preexperiment.e3_full.stats import (
    CALTECH_PROXIES,
    JPL_PROXIES,
    MAIN_PROXY,
    audit_to_serializable,
    pool_audit,
)

IMPL = Path(__file__).resolve().parents[2]  # patent_preexperiment 实现区
REPO = IMPL.parent  # 仓库根（git 溯源用）
MINUTE_ROOT = IMPL / "datasets" / "session_response_1min"
REGISTRY = IMPL / "data_registry" / "e0_full_split_registry.parquet"
E0_CFG = load_yaml(IMPL / "configs" / "e0_full.yaml")
OUT = IMPL / "results" / "raw" / "E3F"
PROVENANCE = OUT / "e3_full_provenance.json"
SEEDS = E0_CFG["seeds"]
BOOT_SEED: int = SEEDS["bootstrap"]
N_BOOT: int = SEEDS["n_boot"]
STOP = E0_CFG["k1_replication_stop_lines"]["e3"]

CAL_POOL = "caltech.California_Garage_01"
JPL_POOL = "jpl.Arroyo_Garage_01.current_only"

MINUTE_COLUMNS = [
    "session_id", "station_id", "site", "garage", "split", "role",
    "sample_layer", "field_mode", "timestamp_utc", "disconnect_time",
    "actual_power_kw", "pilot_power_kw",
]


def _write_fail_cases(cand: pd.DataFrame, split: str, pool_tag: str) -> None:
    """抽取 20 个候选案例（按主基线候选能量降序，AGENTS.md 每实验 ≥20 失败案例）。"""
    opp = cand[cand[f"candidate_{MAIN_PROXY}"]]
    top = opp.nlargest(20, f"candidate_energy_{MAIN_PROXY}_kwh").copy()
    top["fail_type"] = "candidate_window_cycle"
    top["split"] = split
    top.to_csv(OUT / f"e3_full_{split}_{pool_tag}_fail_cases.csv", index=False)


def _per_split(split: str, cal_df: pd.DataFrame, jpl_df: pd.DataFrame) -> dict:
    """单 split：双轨人口各自池审计 → 门判定。"""
    cal_sub = split_minutes(cal_df, split)
    jpl_sub = split_minutes(jpl_df, split)

    cal_audit = pool_audit(cal_sub, CAL_POOL, CALTECH_PROXIES, BOOT_SEED, N_BOOT)
    jpl_audit = pool_audit(jpl_sub, JPL_POOL, JPL_PROXIES, BOOT_SEED, N_BOOT)

    cal_cand = cal_audit.pop("_cand")
    jpl_cand = jpl_audit.pop("_cand")
    cal_cand.to_parquet(OUT / f"e3_full_{split}_caltech_candidate.parquet", index=False)
    jpl_cand.to_parquet(OUT / f"e3_full_{split}_jpl_candidate.parquet", index=False)
    _write_fail_cases(cal_cand, split, "caltech")
    _write_fail_cases(jpl_cand, split, "jpl")

    cal_gate = caltech_split_gate(cal_audit, STOP)
    jpl_gate = jpl_split_gate(jpl_audit, STOP)
    cross = cross_pool_gate(cal_gate, jpl_gate)

    return {
        "split": split,
        "caltech": {**audit_to_serializable(cal_audit), "gate": cal_gate},
        "jpl_current_only": {**audit_to_serializable(jpl_audit), "gate": jpl_gate},
        "cross_pool": cross,
    }


def run_e3_full(provenance_path: Path = PROVENANCE) -> dict:
    """E3-Full 正式运行（test 只跑一次，审查结论26 治理）。"""
    assert_formal_test_not_exposed(provenance_path)
    pre_run = git_provenance(REPO)
    OUT.mkdir(parents=True, exist_ok=True)

    registry = pd.read_parquet(REGISTRY)
    cal_df = load_caltech_main(MINUTE_ROOT, registry, columns=MINUTE_COLUMNS)
    jpl_df = load_jpl_current_only(MINUTE_ROOT, registry, columns=MINUTE_COLUMNS)

    per_split = [_per_split(s, cal_df, jpl_df) for s in ("train", "validation", "test")]

    by_split = {d["split"]: d for d in per_split}
    verdict = formal_verdict(
        caltech_test=by_split["test"]["caltech"]["gate"],
        jpl_test=by_split["test"]["jpl_current_only"]["gate"],
        caltech_train=by_split["train"]["caltech"]["gate"],
        caltech_validation=by_split["validation"]["caltech"]["gate"],
        stop=STOP,
    )

    summary = {
        "experiment_id": "E3_Full_R1_replication",
        "protocol": "R1 E3 双轨人口硬切分复现（审查结论28），test 只跑一次",
        "populations": {
            "E3_M_caltech_main": "L1_strict_matched ∧ role==main ∧ split∈{train,validation,test}",
            "E3_X_jpl_current_only": (
                "L1_strict_matched ∧ role==current_only_fallback ∧ "
                "field_mode==current_only ∧ split∈{train,validation,test}"
            ),
        },
        "proxies": {
            "caltech": CALTECH_PROXIES,
            "jpl_current_only": JPL_PROXIES,
            "main_baseline": MAIN_PROXY,
        },
        "seeds": {"bootstrap": BOOT_SEED, "n_boot": N_BOOT},
        "stop_lines": STOP,
        "method": (
            "连续时间历史：每会话补齐 5min 网格，组内(session,run) shift(1)/rolling，"
            "5min 网格断档冷启动；指标A=并发候选修正窗口（预算差值，无吸收假设）；"
            "主门基线=A2_prev_actual（候选量最低可执行简单基线）；精确配对 eligible_mask"
        ),
        "terminology": "仅'预算差值/并发候选修正窗口'，不称'可回收能力'",
        "provenance": {
            "pre_run": pre_run,
            "post_run": None,
            "formal_test_exposure": None,
            "discipline": (
                "审查结论26：code-only commit → clean worktree → test → evidence-only commit。"
                "本 runner 正式运行前 assert_formal_test_not_exposed 检查未封存；"
                "运行后写 provenance 封存 formal_test_exposure，此后禁止重跑。"
            ),
        },
        "per_split": per_split,
        "r1_verdict_on_test": {
            "primary": verdict["primary"],
            "review_required": verdict["review_required"],
            "reasons": verdict["reasons"],
            "exit_code": formal_exit_code(verdict),
        },
    }
    (OUT / "e3_full_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    post_run = git_provenance(REPO)
    summary["provenance"]["post_run"] = post_run
    summary["provenance"]["formal_test_exposure"] = pre_run["code_sha"]
    (OUT / "e3_full_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    seal = {
        "experiment_id": "E3_Full_R1_replication",
        "record_type": "formal_exposure",
        "formal_test_exposure": pre_run["code_sha"],
        "pre_run": pre_run,
        "post_run": post_run,
        "note": (
            "runner 自封存：正式 test 已执行一次，此后 assert_formal_test_not_exposed "
            "将拒绝任何重跑；test 冻结结论以本文件与 e3_full_summary.json 为准。"
        ),
    }
    PROVENANCE.write_text(json.dumps(seal, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    if "--read-frozen" in sys.argv:
        sys.exit(frozen_gate_exit_code(OUT / "e3_full_summary.json"))
    sys.exit(formal_exit_code(run_e3_full()["r1_verdict_on_test"]))
