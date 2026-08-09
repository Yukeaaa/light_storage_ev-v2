"""R1 正式门 runner 治理（审查结论26）：退出码与代码溯源。

- formal_exit_code：R1 正式门判定 PASS → 0，FAIL → 1（P0：FAIL 不得返回 0）。
- git_provenance：记录运行时代码 SHA 与工作区洁净状态（P1），缺失时显式
  "unknown"，不猜测。E3 起要求 code-only commit → clean worktree → test →
  evidence-only commit 分离，运行时记录与提交分离共同构成可审计溯源。
"""

from __future__ import annotations

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
