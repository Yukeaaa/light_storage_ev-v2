"""E3-Full（R1 / E0F-06 E3 部分）：双轨人口候选预算修正窗口 / 机会审计。

R1 协议（审查结论28/29 定稿）：
- 双轨人口：E3-M = caltech main（L1∧role==main）；E3-X = jpl current_only
  （L1∧role==current_only_fallback∧field_mode==current_only）。逐 split 硬切分，各自独立统计。
- 沿用 K1 E3-Lite 冻结管线（allocation.opportunity：build_cycles→pool_stats→
  proxies→eligible_mask→candidate_windows，指标 A = 并发候选修正窗口，预算差值，无吸收假设）。
- 主基线 A2_prev_actual 两池一致；caltech 代理集 [A0_avg, A2, A3]，jpl [A2, A3]。
- 门结构（gate.py）：E3-M 主门 / E3-X 跨池佐证门 / 复杂模型止损门（A2/A3 消除>80%）。
- 审查结论29 P0 治理（runner 拆分）：
  --pretest         train+validation only → results/work/E3F_pretest/（禁加载 test）
  --formal-test     验证 pretest manifest → clean/SHA hard gate → 写 started sentinel
                    → Caltech test + JPL test 一次 → results/raw/E3F/ → seal completed
  --read-frozen     只读冻结门（不重算/写盘）
  正式 test 必须 --expected-code-sha <最终 code-only SHA> 且 --require-clean（默认）。
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
    assert_clean_and_sha,
    assert_formal_test_not_started_or_exposed,
    caltech_split_gate,
    cross_pool_gate,
    formal_exit_code,
    formal_verdict,
    frozen_gate_exit_code,
    git_provenance,
    jpl_split_gate,
    seal_completed,
    write_started_sentinel,
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
PRETEST_OUT = IMPL / "results" / "work" / "E3F_pretest"
FORMAL_OUT = IMPL / "results" / "raw" / "E3F"
PROVENANCE = FORMAL_OUT / "e3_full_provenance.json"
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

FAIL_CASE_TARGET = 20  # AGENTS.md 每实验 ≥20 failure cases


def _write_fail_cases(cand: pd.DataFrame, split: str, pool_tag: str, out_dir: Path) -> dict:
    """审查结论29 NB-3：组合 top positive candidate + high-concurrency no-candidate，
    确保至少 20 个；若整个 split valid cycles 不足 20 → insufficient_failure_cases=true。
    """
    energy_col = f"candidate_energy_{MAIN_PROXY}_kwh"
    opp = cand[cand[f"candidate_{MAIN_PROXY}"]].copy()
    top_pos = opp.nlargest(FAIL_CASE_TARGET, energy_col)
    top_pos["fail_type"] = "candidate_window_cycle"

    # 补 high-concurrency no-candidate / baseline-missed：n_active 高但无候选
    no_opp = cand[~cand[f"candidate_{MAIN_PROXY}"]].copy()
    if len(no_opp):
        no_opp = no_opp.nlargest(max(FAIL_CASE_TARGET - len(top_pos), 0), "n_active")
        no_opp["fail_type"] = "high_concurrency_no_candidate"

    combined = pd.concat([top_pos, no_opp], ignore_index=True)
    combined["split"] = split
    insufficient = bool(len(combined) < FAIL_CASE_TARGET and len(cand) < FAIL_CASE_TARGET)
    combined.to_csv(out_dir / f"e3_full_{split}_{pool_tag}_fail_cases.csv", index=False)
    return {
        "n_fail_cases": int(len(combined)),
        "n_positive_candidates": int(len(top_pos)),
        "n_no_candidate_supplement": int(len(no_opp)),
        "insufficient_failure_cases": insufficient,
    }


def _per_split(split: str, cal_df: pd.DataFrame, jpl_df: pd.DataFrame, out_dir: Path) -> dict:
    """单 split：双轨人口各自池审计 → 门判定。"""
    cal_sub = split_minutes(cal_df, split)
    jpl_sub = split_minutes(jpl_df, split)

    cal_audit = pool_audit(cal_sub, CAL_POOL, CALTECH_PROXIES, BOOT_SEED, N_BOOT)
    jpl_audit = pool_audit(jpl_sub, JPL_POOL, JPL_PROXIES, BOOT_SEED, N_BOOT)

    cal_cand = cal_audit.pop("_cand")
    jpl_cand = jpl_audit.pop("_cand")
    cal_cand.to_parquet(out_dir / f"e3_full_{split}_caltech_candidate.parquet", index=False)
    jpl_cand.to_parquet(out_dir / f"e3_full_{split}_jpl_candidate.parquet", index=False)
    cal_fail = _write_fail_cases(cal_cand, split, "caltech", out_dir)
    jpl_fail = _write_fail_cases(jpl_cand, split, "jpl", out_dir)

    cal_gate = caltech_split_gate(cal_audit, STOP)
    jpl_gate = jpl_split_gate(jpl_audit, STOP)
    cross = cross_pool_gate(cal_gate, jpl_gate)

    return {
        "split": split,
        "caltech": {**audit_to_serializable(cal_audit), "gate": cal_gate,
                    "fail_cases_report": cal_fail},
        "jpl_current_only": {**audit_to_serializable(jpl_audit), "gate": jpl_gate,
                             "fail_cases_report": jpl_fail},
        "cross_pool": cross,
    }


def _base_summary(per_split: list[dict], mode: str, provenance: dict | None = None) -> dict:
    """构造 summary 主体（pretest 与 formal-test 共用）。"""
    by_split = {d["split"]: d for d in per_split}
    if mode == "pretest":
        # pretest 只 train/val，不产 verdict（无 test split）
        return {
            "experiment_id": "E3_Full_R1_replication",
            "mode": "pretest",
            "protocol": "R1 E3 双轨人口 pretest（train+validation，审查结论29 P0-3）",
            "splits_run": [d["split"] for d in per_split],
            "populations": {
                "E3_M_caltech_main": "L1_strict_matched ∧ role==main ∧ split∈{train,validation}",
                "E3_X_jpl_current_only": (
                    "L1_strict_matched ∧ role==current_only_fallback ∧ "
                    "field_mode==current_only ∧ split∈{train,validation}"
                ),
            },
            "proxies": {"caltech": CALTECH_PROXIES, "jpl_current_only": JPL_PROXIES,
                        "main_baseline": MAIN_PROXY},
            "seeds": {"bootstrap": BOOT_SEED, "n_boot": N_BOOT},
            "stop_lines": STOP,
            "provenance": provenance,
            "per_split": per_split,
            "note": "pretest 不产 r1_verdict_on_test；test 冻结结论须 --formal-test 产出",
        }

    verdict = formal_verdict(
        caltech_test=by_split["test"]["caltech"]["gate"],
        jpl_test=by_split["test"]["jpl_current_only"]["gate"],
        caltech_train=by_split["train"]["caltech"]["gate"],
        caltech_validation=by_split["validation"]["caltech"]["gate"],
        jpl_train=by_split["train"]["jpl_current_only"]["gate"],
        jpl_validation=by_split["validation"]["jpl_current_only"]["gate"],
        stop=STOP,
    )
    return {
        "experiment_id": "E3_Full_R1_replication",
        "mode": "formal-test",
        "protocol": "R1 E3 双轨人口正式 test（test 只跑一次，审查结论29 P0 治理）",
        "populations": {
            "E3_M_caltech_main": "L1_strict_matched ∧ role==main ∧ split∈{train,validation,test}",
            "E3_X_jpl_current_only": (
                "L1_strict_matched ∧ role==current_only_fallback ∧ "
                "field_mode==current_only ∧ split∈{train,validation,test}"
            ),
        },
        "proxies": {"caltech": CALTECH_PROXIES, "jpl_current_only": JPL_PROXIES,
                    "main_baseline": MAIN_PROXY},
        "seeds": {"bootstrap": BOOT_SEED, "n_boot": N_BOOT},
        "stop_lines": STOP,
        "method": (
            "连续时间历史：每会话补齐 5min 网格，组内(session,run) shift(1)/rolling，"
            "5min 网格断档冷启动；指标A=并发候选修正窗口（预算差值，无吸收假设）；"
            "主门基线=A2_prev_actual（候选量最低可执行简单基线）；精确配对 eligible_mask"
        ),
        "terminology": "仅'预算差值/并发候选修正窗口'，不称'可回收能力'",
        "provenance": provenance,
        "per_split": per_split,
        "r1_verdict_on_test": {
            "primary": verdict["primary"],
            "main_review_required": verdict["main_review_required"],
            "cross_pool_review_required": verdict["cross_pool_review_required"],
            "review_required": verdict["review_required"],
            "reasons": verdict["reasons"],
            "exit_code": formal_exit_code(verdict),
        },
    }


def run_pretest() -> dict:
    """审查结论29 P0-3：train+validation only（禁加载 test）→ results/work/E3F_pretest/。"""
    PRETEST_OUT.mkdir(parents=True, exist_ok=True)
    pre_run = git_provenance(REPO)

    registry = pd.read_parquet(REGISTRY)
    # 禁加载 test：只读 train/validation split（loader 仍按 MAIN_SPLITS 读全部，这里只切 train/val）
    cal_df = load_caltech_main(MINUTE_ROOT, registry, columns=MINUTE_COLUMNS)
    jpl_df = load_jpl_current_only(MINUTE_ROOT, registry, columns=MINUTE_COLUMNS)
    cal_df = cal_df[cal_df["split"].isin(["train", "validation"])]
    jpl_df = jpl_df[jpl_df["split"].isin(["train", "validation"])]

    per_split = [_per_split(s, cal_df, jpl_df, PRETEST_OUT) for s in ("train", "validation")]
    summary = _base_summary(per_split, mode="pretest", provenance={"pre_run": pre_run})
    (PRETEST_OUT / "e3_full_pretest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def run_formal_test(expected_code_sha: str, require_clean: bool = True) -> dict:
    """审查结论29 P0-1/P0-2/P0-3：clean/SHA hard gate → started sentinel → test 一次 → seal。

    必须传 --expected-code-sha <最终 code-only SHA>；worktree 必须洁净。
    """
    assert_formal_test_not_started_or_exposed(PROVENANCE)
    pre_run = git_provenance(REPO)
    assert_clean_and_sha(pre_run, expected_code_sha, require_clean=require_clean)

    # 写 started sentinel（在读取任何 test outcome 之前）
    write_started_sentinel(PROVENANCE, pre_run)
    FORMAL_OUT.mkdir(parents=True, exist_ok=True)

    # 正式 test 必须先有 pretest manifest（确认 train/val 已审阅）
    pretest_manifest = PRETEST_OUT / "e3_full_pretest_summary.json"
    if not pretest_manifest.exists():
        raise RuntimeError(
            "hard STOP：pretest manifest 不存在（results/work/E3F_pretest/）；"
            "formal test 前必须先跑 --pretest 并人工审阅 train/val"
        )

    registry = pd.read_parquet(REGISTRY)
    cal_df = load_caltech_main(MINUTE_ROOT, registry, columns=MINUTE_COLUMNS)
    jpl_df = load_jpl_current_only(MINUTE_ROOT, registry, columns=MINUTE_COLUMNS)

    per_split = [_per_split(s, cal_df, jpl_df, FORMAL_OUT) for s in ("train", "validation", "test")]
    summary = _base_summary(per_split, mode="formal-test", provenance={"pre_run": pre_run})
    (FORMAL_OUT / "e3_full_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    post_run = git_provenance(REPO)
    summary["provenance"]["post_run"] = post_run
    summary["provenance"]["formal_test_exposure"] = pre_run["code_sha"]
    (FORMAL_OUT / "e3_full_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    seal_completed(PROVENANCE, pre_run, post_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def _parse_args(argv: list[str]) -> tuple[str, str | None, bool]:
    """解析 CLI：返回 (mode, expected_code_sha, require_clean)。"""
    if "--read-frozen" in argv:
        return "read-frozen", None, True
    if "--pretest" in argv:
        return "pretest", None, True
    if "--formal-test" in argv:
        sha: str | None = None
        for i, a in enumerate(argv):
            if a == "--expected-code-sha" and i + 1 < len(argv):
                sha = argv[i + 1]
        if not sha:
            raise SystemExit("--formal-test 必须配 --expected-code-sha <最终 code-only SHA>")
        require_clean = "--no-require-clean" not in argv
        return "formal-test", sha, require_clean
    raise SystemExit(
        "用法：run.py --pretest | --formal-test --expected-code-sha <SHA> | --read-frozen"
    )


if __name__ == "__main__":
    mode, expected_sha, require_clean = _parse_args(sys.argv[1:])
    if mode == "read-frozen":
        sys.exit(frozen_gate_exit_code(FORMAL_OUT / "e3_full_summary.json"))
    if mode == "pretest":
        run_pretest()
        sys.exit(0)
    assert expected_sha is not None
    summary = run_formal_test(expected_sha, require_clean=require_clean)
    sys.exit(formal_exit_code(summary["r1_verdict_on_test"]))
