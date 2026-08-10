"""P1 runner：`--freeze-split` 冻结 office001 60/20/20 + SHA；
`--step0` 只读 train+validation 可行性审计。

调用序列（Review 55 授权）：
    python -m experiments.p1.step0.run --freeze-split   # code-only 冻结（不读任何 E1 结果）
    python -m experiments.p1.step0.run --step0          # train/validation-only feasibility audit
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from patent_preexperiment.p1.split import run_p1_split_freeze
from patent_preexperiment.p1.step0 import run_step0, write_step0_evidence, write_step0_report

IMPL = Path(__file__).resolve().parents[3]  # patent_preexperiment 实现区
REPO = IMPL.parent


def git_provenance() -> dict[str, object]:
    try:
        sha = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        return {"code_sha": sha, "worktree_clean": not bool(status)}
    except Exception:
        return {"code_sha": "unknown", "worktree_clean": None}


def main() -> int:
    args = sys.argv[1:]
    if "--freeze-split" in args:
        meta = run_p1_split_freeze(IMPL)
        meta["provenance"] = git_provenance()
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0

    if "--step0" in args:
        summary = run_step0(IMPL)
        summary["provenance"] = git_provenance()
        write_step0_evidence(IMPL, summary)
        write_step0_report(IMPL, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
