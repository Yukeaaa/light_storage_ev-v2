"""E3-Full 分层门判定（审查结论28/29 定稿：E3-M 主门 / E3-X 跨池佐证门 / 复杂模型止损门）。

门结构：
- E3-M Caltech 主门（逐 split）：M1 日等权候选率 CI 下界 ≥1%；M2 日候选能量占比中位
  ≥0.5%；M3 A2/A3 消除 ≤80%（超限 = 复杂模型止损，单独判定）；M4 非单月
  （审查结论29 NB-2：hard M4 = n_months_with_opp ≥ 2；top_month/top_day 仅 concentration
  diagnostic / review evidence，不造 outlier cutoff）。
- E3-X JPL current-only 跨池佐证门（逐 split）：X1 日候选能量占比中位 ≥0.5%；
  X2 非单月；X3 候选表唯一性（n_dup_cycles==0）。不作率 CI 新硬门槛。
- Cross-pool 门（逐 split）：caltech 能量占比 ∧ jpl 能量占比 各自 ≥0.5%。

正式判定优先级（test split）：
  ① 数据/唯一性/provenance FAIL → HARD STOP（由 runner 抛异常，不入 verdict）
  ② A2/A3 消除 >80% → STOP_COMPLEX_MODEL
  ③ Caltech test 主门 FAIL → FORMAL_FAIL_MAIN
  ④ Caltech PASS 但 cross-pool 门 FAIL → FORMAL_FAIL_CROSS_POOL
  ⑤ 全部满足 → E3 PASS
另：审查结论29 NB-1 review_required 拆 main（Caltech train/val PASS 而 test 主门 FAIL）
与 cross_pool（双轨 train/val + cross-pool 全 PASS 而 test FAIL）；避免 JPL train 已 FAIL
却被错误标记为标准"情况二"。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from patent_preexperiment.e3_full.stats import MAIN_PROXY


def _ci_lower(audit: dict[str, Any], proxy: str = MAIN_PROXY) -> float | None:
    ci = audit["day_cluster_ci95"].get(proxy) or {}
    ci95 = ci.get("ci95")
    return ci95[0] if ci95 else None


def caltech_split_gate(audit: dict[str, Any], stop: dict[str, Any]) -> dict[str, Any]:
    """Caltech 主门（逐 split）。M3 单独返回 elim 供止损判定。"""
    ci_lower = _ci_lower(audit)
    m1 = ci_lower is not None and ci_lower >= stop["caltech_a2_daily_ci_lower_rate"]

    share = audit["daily_energy_share_median"]
    m2 = share is not None and share >= stop["daily_energy_share_each_pool"]

    elim = audit.get("elimination_vs_A0", {})
    elim_points = {
        p: v["point"] for p, v in elim.items() if v.get("point") is not None
    }
    elim_max = max(elim_points.values()) if elim_points else None
    m3 = elim_max is not None and elim_max <= stop["max_baseline_elimination"]

    m4 = audit["concentration"]["n_months_with_opp"] >= 2

    all_pass = bool(m1 and m2 and m3 and m4)
    return {
        "m1_a2_daily_ci_lower_rate": m1,
        "m2_caltech_energy_share": m2,
        "m3_baseline_not_eliminated": m3,
        "m3_elim_max": elim_max,
        "m4_not_single_month": m4,
        # 审查结论29 NB-2：top_month/top_day 仅 concentration diagnostic / review evidence，
        # 不作 hard gate（此前未冻结数值化 outlier cutoff，不事后发明 threshold）。
        "m4_concentration_diagnostic": {
            "top_month_share": audit["concentration"].get("top_month_share_of_opp_energy"),
            "top_day_share": audit["concentration"].get("top_day_share_of_opp_energy"),
        },
        "all_pass": all_pass,
    }


def jpl_split_gate(audit: dict[str, Any], stop: dict[str, Any]) -> dict[str, Any]:
    """JPL current-only 跨池佐证门（逐 split）。不作率 CI 新硬门槛。"""
    share = audit["daily_energy_share_median"]
    x1 = share is not None and share >= stop["daily_energy_share_each_pool"]
    x2 = audit["concentration"]["n_months_with_opp"] >= 2
    x3 = audit["n_dup_cycles"] == 0
    all_pass = bool(x1 and x2 and x3)
    return {"x1_energy_share": x1, "x2_not_single_month": x2, "x3_uniqueness": x3,
            "x2_concentration_diagnostic": {
                "top_month_share": audit["concentration"].get("top_month_share_of_opp_energy"),
                "top_day_share": audit["concentration"].get("top_day_share_of_opp_energy"),
            },
            "all_pass": all_pass}


def cross_pool_gate(caltech_gate: dict[str, Any], jpl_gate: dict[str, Any]) -> dict[str, Any]:
    """跨池能量门：两证据池日候选能量占比各自 ≥0.5%。"""
    energy_pass = bool(
        caltech_gate["m2_caltech_energy_share"] and jpl_gate["x1_energy_share"]
    )
    return {"energy_share_each_pool_pass": energy_pass}


def formal_verdict(
    caltech_test: dict[str, Any],
    jpl_test: dict[str, Any],
    caltech_train: dict[str, Any],
    caltech_validation: dict[str, Any],
    jpl_train: dict[str, Any],
    jpl_validation: dict[str, Any],
    stop: dict[str, Any],
) -> dict[str, Any]:
    """test split 正式判定（优先级固定，JPL 不得 rescue Caltech）。

    审查结论29 NB-1：review_required 拆 main（Caltech train/val PASS）与 cross_pool
    （Caltech + JPL + cross-pool train/val 全 PASS），避免 JPL train 已 FAIL 却被
    错误标记为标准"情况二"。
    """
    reasons: list[str] = []

    elim_max = caltech_test["m3_elim_max"]
    if elim_max is not None and elim_max > stop["max_baseline_elimination"]:
        primary = "STOP_COMPLEX_MODEL"
        reasons.append(
            f"A2/A3 消除 {elim_max:.1%} > {stop['max_baseline_elimination']:.0%}，"
            "最强简单基线已基本解决，按协议停止复杂区间模型路线"
        )
    elif not caltech_test["all_pass"]:
        primary = "FORMAL_FAIL_MAIN"
        reasons.append("Caltech test 主门失败（JPL 不得 rescue）")
    elif not (
        jpl_test["all_pass"]
        and cross_pool_gate(caltech_test, jpl_test)["energy_share_each_pool_pass"]
    ):
        primary = "FORMAL_FAIL_CROSS_POOL"
        reasons.append("Caltech 成立但 JPL current-only 跨池能量/佐证门不足")
    else:
        primary = "E3_PASS"
        reasons.append("Caltech 主门 + cross-pool 门 + 浓度 + 基线消除全部通过")

    # NB-1：main_review 只看 Caltech train/val；cross_pool_review 看 Caltech+JPL+cross train/val
    main_train_val_pass = bool(
        caltech_train["all_pass"] and caltech_validation["all_pass"]
    )
    cross_train_pass = bool(
        main_train_val_pass
        and jpl_train["all_pass"]
        and cross_pool_gate(caltech_train, jpl_train)["energy_share_each_pool_pass"]
    )
    cross_val_pass = bool(
        main_train_val_pass
        and jpl_validation["all_pass"]
        and cross_pool_gate(caltech_validation, jpl_validation)["energy_share_each_pool_pass"]
    )
    test_pass = bool(
        caltech_test["all_pass"]
        and jpl_test["all_pass"]
        and cross_pool_gate(caltech_test, jpl_test)["energy_share_each_pool_pass"]
    )
    main_review_required = bool(main_train_val_pass and not caltech_test["all_pass"])
    cross_pool_review_required = bool(
        cross_train_pass and cross_val_pass and not test_pass
    )
    if main_review_required:
        reasons.append("Caltech train/val PASS 而 test 主门 FAIL → 情况二 main review")
    if cross_pool_review_required:
        reasons.append(
            "train/val 双轨 + cross-pool 全 PASS 而 test FAIL → 情况二 cross-pool review"
        )

    return {
        "primary": primary,
        "main_review_required": main_review_required,
        "cross_pool_review_required": cross_pool_review_required,
        "review_required": main_review_required or cross_pool_review_required,
        "reasons": reasons,
    }


def formal_exit_code(verdict: dict[str, Any]) -> int:
    """正式门退出码：primary != E3_PASS → 1（fail-closed，STOP_COMPLEX_MODEL 也是 1）。"""
    return 0 if verdict["primary"] == "E3_PASS" else 1


# ---- 审查结论29 P0 治理：溯源 / SHA+clean hard gate / once-only sentinel 状态机 ----

# once-only 状态机：absent → started → completed（formal_test_exposure 填充）
# started 后即使崩溃，下次运行也硬拒（不自动获得第二次 test）。
_FORBIDDEN_STATES = {"started", "completed"}


def git_provenance(repo: Any) -> dict[str, Any]:
    """记录当前代码 SHA 与工作区洁净状态（git 不可用 → unknown，不猜测 clean）。"""
    try:
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        return {"code_sha": sha, "worktree_clean": not bool(status)}
    except Exception:
        return {
            "code_sha": "unknown", "worktree_clean": None,
            "note": "git 溯源不可用（无仓库/命令失败/超时），code_sha 未记录，不能据此声称 clean",
        }


def assert_clean_and_sha(
    provenance: dict[str, Any], expected_code_sha: str, require_clean: bool = True
) -> None:
    """审查结论29 P0-2：正式 test 前机器断言 code_sha != unknown、== expected、worktree clean。

    任何一项不满足即 hard STOP（不只是"记录"，而是阻止执行）。
    """
    sha = provenance.get("code_sha")
    clean = provenance.get("worktree_clean")
    if sha == "unknown" or sha is None:
        raise RuntimeError(
            f"hard STOP：git 溯源不可用（code_sha={sha!r}），正式 test 必须有可证明 code SHA"
        )
    if sha != expected_code_sha:
        raise RuntimeError(
            f"hard STOP：当前 HEAD {sha!r} != 最终 code-only SHA {expected_code_sha!r}；"
            "formal test 必须在最终 code-only baseline 上执行"
        )
    if require_clean and clean is not True:
        raise RuntimeError(
            "hard STOP：worktree 非洁净（有未提交改动）；formal test 前必须 clean worktree"
        )


def _read_provenance(provenance_path: Path) -> dict[str, Any] | None:
    if not provenance_path.exists():
        return None
    payload: dict[str, Any] = json.loads(provenance_path.read_text(encoding="utf-8"))
    return payload


def assert_formal_test_not_started_or_exposed(provenance_path: Path) -> None:
    """审查结论29 P0-1：provenance state ∈ {started, completed} 或 formal_test_exposure 非空
    → hard STOP。started 后即使崩溃，也不自动获得第二次 test。
    """
    payload = _read_provenance(provenance_path)
    if payload is None:
        return
    state = payload.get("state")
    if state in _FORBIDDEN_STATES:
        raise RuntimeError(
            f"R1-E3 formal test already {state!r} (file: {provenance_path}); "
            "rerun prohibited（started 后即使崩溃也不自动获得第二次 test）"
        )
    exposure = payload.get("formal_test_exposure")
    if exposure:
        raise RuntimeError(
            f"R1-E3 formal test already exposed at {exposure!r} "
            f"(file: {provenance_path}); rerun prohibited"
        )


def write_started_sentinel(provenance_path: Path, pre_run: dict[str, Any]) -> None:
    """审查结论29 P0-1：在读取任何 test outcome 之前写 started sentinel。

    state=started 后即使程序崩溃，下次运行 assert_formal_test_not_started_or_exposed 也硬拒。
    """
    sentinel = {
        "experiment_id": "E3_Full_R1_replication",
        "record_type": "formal_test_state",
        "state": "started",
        "started_at_code_sha": pre_run.get("code_sha"),
        "note": (
            "started sentinel：formal test 已启动；即使本次运行崩溃，"
            "下次 assert_formal_test_not_started_or_exposed 仍硬拒（不自动获得第二次 test）"
        ),
    }
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(json.dumps(sentinel, ensure_ascii=False, indent=2), encoding="utf-8")


def seal_completed(
    provenance_path: Path, pre_run: dict[str, Any], post_run: dict[str, Any]
) -> None:
    """审查结论29 P0-1：test 完成后封存 state=completed + formal_test_exposure。"""
    payload = _read_provenance(provenance_path) or {}
    payload.update({
        "state": "completed",
        "formal_test_exposure": pre_run.get("code_sha"),
        "pre_run": pre_run,
        "post_run": post_run,
        "record_type": "formal_exposure",
        "note": (
            "runner 自封存：正式 test 已执行一次（state=completed）；此后任何重跑被硬拒。"
            "test 冻结结论以本文件与 e3_full_summary.json 为准。"
        ),
    })
    provenance_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def frozen_gate_exit_code(summary_path: Path) -> int:
    """只读冻结门：读已冻结 e3_full_summary.json 返回 formal_exit_code（绝不重算/写盘）。"""
    if not summary_path.exists():
        raise FileNotFoundError(f"frozen summary 不存在：{summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return formal_exit_code(summary["r1_verdict_on_test"])
