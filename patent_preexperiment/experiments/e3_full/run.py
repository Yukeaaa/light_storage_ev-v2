"""E3-Full（R1 / E0F-06 E3 部分）：双轨人口候选预算修正窗口 / 机会审计。

R1 协议（审查结论28/29/30 定稿）：
- 双轨人口：E3-M = caltech main（L1∧role==main）；E3-X = jpl current_only
  （L1∧role==current_only_fallback∧field_mode==current_only）。逐 split 硬切分，各自独立统计。
- 沿用 K1 E3-Lite 冻结管线（指标 A = 并发候选修正窗口，预算差值，无吸收假设）。
- 主基线 A2_prev_actual 两池一致；caltech [A0_avg, A2, A3]，jpl [A2, A3]。
- 门结构（gate.py）：E3-M 主门 / E3-X 跨池佐证门 / 复杂模型止损门。
- 审查结论30 P0 治理：
  --pretest --expected-code-sha X   HEAD==X ∧ clean → 只读 train/val（不读 test）
                                    → results/work/E3F_pretest/ → 人工审阅
  --formal-test --expected-code-sha X
    assert formal state absent → load+validate pretest manifest（SHA/contract）
    → HEAD==X ∧ clean=true → write started sentinel（含 pretest hash）
    → 只读 test（不读 train/val）→ 嵌入 frozen pretest train/val → formal verdict
    → results/raw/E3F/ → seal completed
  --read-frozen                   只读冻结门
  formal mode 永远 require_clean=True（无 bypass）。
- 随机种子：e0_full.yaml seeds（bootstrap=42, n_boot=2000）。

术语纪律：只称"预算差值/并发候选修正窗口"，不称"可回收能力"。
"""

from __future__ import annotations

import hashlib
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
    PRETEST_SPLITS,
    TEST_ONLY_SPLITS,
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
PRETEST_SUMMARY = PRETEST_OUT / "e3_full_pretest_summary.json"
FORMAL_SUMMARY = FORMAL_OUT / "e3_full_summary.json"
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


def _sha256_of_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _write_fail_cases(cand: pd.DataFrame, split: str, pool_tag: str, out_dir: Path) -> dict:
    """审查结论29 NB-3：组合 top positive candidate + high-concurrency no-candidate，
    确保至少 20 个；若整个 split valid cycles 不足 20 → insufficient_failure_cases=true。
    """
    energy_col = f"candidate_energy_{MAIN_PROXY}_kwh"
    opp = cand[cand[f"candidate_{MAIN_PROXY}"]].copy()
    top_pos = opp.nlargest(FAIL_CASE_TARGET, energy_col)
    top_pos["fail_type"] = "candidate_window_cycle"

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


def _common_meta() -> dict:
    """pretest 与 formal summary 共用的元数据（contract fingerprint）。"""
    return {
        "proxies": {"caltech": CALTECH_PROXIES, "jpl_current_only": JPL_PROXIES,
                    "main_baseline": MAIN_PROXY},
        "seeds": {"bootstrap": BOOT_SEED, "n_boot": N_BOOT},
        "stop_lines": STOP,
        "populations": {
            "E3_M_caltech_main": "L1_strict_matched ∧ role==main",
            "E3_X_jpl_current_only": (
                "L1_strict_matched ∧ role==current_only_fallback ∧ field_mode==current_only"
            ),
        },
        "method": (
            "连续时间历史：每会话补齐 5min 网格，组内(session,run) shift(1)/rolling，"
            "5min 网格断档冷启动；指标A=并发候选修正窗口（预算差值，无吸收假设）；"
            "主门基线=A2_prev_actual；精确配对 eligible_mask；evaluable-day K1 exact 口径"
        ),
        "terminology": "仅'预算差值/并发候选修正窗口'，不称'可回收能力'",
    }


def _validate_pretest_manifest(expected_code_sha: str) -> dict:
    """审查结论30 P0-4：formal-test 读取并验证 pretest manifest（在 started sentinel 之前）。

    校验：mode=pretest、splits_run==[train,validation]、pretest.provenance.code_sha==expected、
    contract fingerprint（proxies/seeds/stop_lines/populations）与当前一致。
    """
    if not PRETEST_SUMMARY.exists():
        raise RuntimeError(
            "hard STOP：pretest manifest 不存在（results/work/E3F_pretest/）；"
            "formal test 前必须先跑 --pretest 并人工审阅 train/val"
        )
    manifest = json.loads(PRETEST_SUMMARY.read_text(encoding="utf-8"))
    if manifest.get("mode") != "pretest":
        got_mode = manifest.get("mode")
        raise RuntimeError(f"hard STOP：pretest manifest mode != pretest（got {got_mode})")
    if manifest.get("splits_run") != ["train", "validation"]:
        got_splits = manifest.get("splits_run")
        raise RuntimeError(
            f"hard STOP：pretest manifest splits_run != [train,validation]（got {got_splits})"
        )
    pre_sha = manifest.get("provenance", {}).get("pre_run", {}).get("code_sha")
    if pre_sha != expected_code_sha:
        raise RuntimeError(
            f"hard STOP：pretest code_sha {pre_sha!r} != expected {expected_code_sha!r}；"
            "formal test 必须基于已审阅的同一 code-only baseline"
        )
    # contract fingerprint 一致性
    meta = _common_meta()
    for k in ("proxies", "seeds", "stop_lines", "populations"):
        if manifest.get(k) != meta[k]:
            raise RuntimeError(
                f"hard STOP：pretest manifest {k} 与当前 prereg contract 不一致；"
                "formal test 必须基于同一 contract"
            )
    return manifest


def run_pretest(expected_code_sha: str) -> dict:
    """审查结论30 P0-1/P0-3：HEAD==X ∧ clean → 只读 train/validation（predicate-pushdown，
    不读 test）→ results/work/E3F_pretest/。"""
    pre_run = git_provenance(REPO)
    assert_clean_and_sha(pre_run, expected_code_sha)  # clean/SHA hard gate（formal-quality）
    PRETEST_OUT.mkdir(parents=True, exist_ok=True)

    registry = pd.read_parquet(REGISTRY)
    cal_df = load_caltech_main(
        MINUTE_ROOT, registry, columns=MINUTE_COLUMNS, splits=PRETEST_SPLITS
    )
    jpl_df = load_jpl_current_only(
        MINUTE_ROOT, registry, columns=MINUTE_COLUMNS, splits=PRETEST_SPLITS
    )

    per_split = [_per_split(s, cal_df, jpl_df, PRETEST_OUT) for s in PRETEST_SPLITS]
    summary = {
        "experiment_id": "E3_Full_R1_replication",
        "mode": "pretest",
        "protocol": "R1 E3 双轨人口 pretest（train+validation，审查结论30 P0-1 不读 test）",
        "splits_run": list(PRETEST_SPLITS),
        **_common_meta(),
        "provenance": {"pre_run": pre_run},
        "per_split": per_split,
        "note": "pretest 不产 r1_verdict_on_test；test 冻结结论须 --formal-test 产出",
    }
    PRETEST_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def run_formal_test(expected_code_sha: str) -> dict:
    """审查结论30 P0-3/P0-4：formal transaction（顺序固定，manifest 验证在 sentinel 之前）。

    assert no previous exposure → load+validate pretest manifest → clean/SHA hard gate
    → write started sentinel（含 pretest hash）→ 只读 test → 嵌入 frozen pretest train/val
    → formal verdict → seal completed。
    formal mode 永远 require_clean=True（无 bypass）。
    """
    # ① assert no previous exposure
    assert_formal_test_not_started_or_exposed(PROVENANCE)
    # ② load + validate pretest manifest（在 started sentinel 之前；不涉及 test outcome）
    pretest_manifest = _validate_pretest_manifest(expected_code_sha)
    pretest_hash = _sha256_of_file(PRETEST_SUMMARY)
    # ③ clean/SHA hard gate
    pre_run = git_provenance(REPO)
    assert_clean_and_sha(pre_run, expected_code_sha)  # require_clean 默认 True，formal 无 bypass
    # ④ write started sentinel（在读取任何 test outcome 之前）
    write_started_sentinel(
        PROVENANCE, pre_run,
        pretest_summary_sha256=pretest_hash,
        subjects=[CAL_POOL, JPL_POOL],
    )
    FORMAL_OUT.mkdir(parents=True, exist_ok=True)

    # ⑤ 只读 test（不重算 train/val）
    registry = pd.read_parquet(REGISTRY)
    cal_test_df = load_caltech_main(
        MINUTE_ROOT, registry, columns=MINUTE_COLUMNS, splits=TEST_ONLY_SPLITS
    )
    jpl_test_df = load_jpl_current_only(
        MINUTE_ROOT, registry, columns=MINUTE_COLUMNS, splits=TEST_ONLY_SPLITS
    )
    test_split = _per_split("test", cal_test_df, jpl_test_df, FORMAL_OUT)

    # ⑥ 嵌入 frozen pretest train/val（引用已审阅 manifest，不重算）
    pretest_by_split = {d["split"]: d for d in pretest_manifest["per_split"]}
    per_split = [pretest_by_split["train"], pretest_by_split["validation"], test_split]

    by_split = {d["split"]: d for d in per_split}
    verdict = formal_verdict(
        caltech_test=by_split["test"]["caltech"]["gate"],
        jpl_test=by_split["test"]["jpl_current_only"]["gate"],
        caltech_train=by_split["train"]["caltech"]["gate"],
        caltech_validation=by_split["validation"]["caltech"]["gate"],
        jpl_train=by_split["train"]["jpl_current_only"]["gate"],
        jpl_validation=by_split["validation"]["jpl_current_only"]["gate"],
        stop=STOP,
    )
    summary = {
        "experiment_id": "E3_Full_R1_replication",
        "mode": "formal-test",
        "protocol": "R1 E3 正式 test（test 只跑一次，审查结论30 P0 治理）",
        "splits_run": ["train", "validation", "test"],
        "train_val_source": "frozen pretest manifest（embedded，not recomputed）",
        "pretest_summary_sha256": pretest_hash,
        **_common_meta(),
        "provenance": {"pre_run": pre_run},
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
    FORMAL_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    post_run = git_provenance(REPO)
    summary["provenance"]["post_run"] = post_run
    summary["provenance"]["formal_test_exposure"] = pre_run["code_sha"]
    FORMAL_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    seal_completed(PROVENANCE, pre_run, post_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def _parse_args(argv: list[str]) -> tuple[str, str | None]:
    """解析 CLI：返回 (mode, expected_code_sha)。

    审查结论30 CLI 治理：无 --no-require-clean（formal 永远 require_clean=True）。
    """
    if "--read-frozen" in argv:
        return "read-frozen", None
    if "--pretest" in argv:
        sha = _extract_sha(argv)
        if not sha:
            raise SystemExit("--pretest 必须配 --expected-code-sha <最终 code-only SHA>")
        return "pretest", sha
    if "--formal-test" in argv:
        sha = _extract_sha(argv)
        if not sha:
            raise SystemExit("--formal-test 必须配 --expected-code-sha <最终 code-only SHA>")
        return "formal-test", sha
    raise SystemExit(
        "用法：run.py --pretest --expected-code-sha <SHA> | "
        "--formal-test --expected-code-sha <SHA> | --read-frozen"
    )


def _extract_sha(argv: list[str]) -> str | None:
    for i, a in enumerate(argv):
        if a == "--expected-code-sha" and i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    mode, expected_sha = _parse_args(sys.argv[1:])
    if mode == "read-frozen":
        sys.exit(frozen_gate_exit_code(FORMAL_SUMMARY))
    if mode == "pretest":
        assert expected_sha is not None
        run_pretest(expected_sha)
        sys.exit(0)
    assert expected_sha is not None
    summary = run_formal_test(expected_sha)
    sys.exit(formal_exit_code(summary["r1_verdict_on_test"]))
