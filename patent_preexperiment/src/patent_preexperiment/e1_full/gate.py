"""R1 正式门 runner 治理（审查结论26/27）：退出码、代码溯源与正式 test 重跑锁。

- formal_exit_code：R1 正式门判定 PASS → 0，FAIL → 1（P0：FAIL 不得返回 0）。
- git_provenance：记录运行时代码 SHA 与工作区洁净状态（P1），缺失时显式
  "unknown"，不猜测。E3 起要求 code-only commit → clean worktree → test →
  evidence-only commit 分离，运行时记录与提交分离共同构成可审计溯源。
- assert_formal_test_not_exposed：正式 test exposure 已落盘（provenance 文件含
  非空 formal_test_exposure）后硬拒绝重跑，防止冻结结论被静默覆盖（P0）。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def formal_exit_code(summary: dict[str, Any]) -> int:
    """正式门退出码：test split 判定 PASS → 0，FAIL → 1。

    之前 `bool(summary)` 恒真导致 FAIL 也返回 0；现显式读取
    `r1_verdict_on_test.verdict`，任何非 "PASS" 判定一律返回 1（fail-closed）。
    """
    verdict = summary["r1_verdict_on_test"]["verdict"]
    return 0 if verdict == "PASS" else 1


def git_provenance(repo: Path) -> dict[str, Any]:
    """记录当前代码 SHA 与工作区洁净状态。

    git 不可用/无仓库/超时 → code_sha="unknown"、worktree_clean=None，
    并在 note 中说明，避免把不可证明状态误记为 clean。
    """
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


def assert_formal_test_not_exposed(provenance_path: Path) -> None:
    """正式 test exposure 后禁止重跑：provenance 文件存在且含非空 formal_test_exposure → STOP。

    run.py 正式入口在**任何计算/写盘之前**调用本函数；一旦冻结（如 E1 的
    e1_full_provenance.json，formal_test_exposure=44fa88c），任何调用方直接
    RuntimeError，不产生任何输出，防止冻结结论被覆盖（P0）。
    """
    if provenance_path.exists():
        payload = json.loads(provenance_path.read_text(encoding="utf-8"))
        exposure = payload.get("formal_test_exposure")
        if exposure:
            raise RuntimeError(
                "R1-E1 formal test already exposed at "
                f"{exposure!r} (file: {provenance_path}); rerun prohibited"
            )


def frozen_gate_exit_code(summary_path: Path) -> int:
    """只读冻结门：读已冻结 e1_full_summary.json 返回 formal_exit_code。

    绝不重算、不写任何输出；用于 CI/决策会议确认 E1 gate 状态（正式 test 只跑
    一次后永久只读）。
    """
    if not summary_path.exists():
        raise FileNotFoundError(f"frozen summary 不存在：{summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return formal_exit_code(summary)
