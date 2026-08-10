"""P1 runner：`--fit-train-edges` / `--formal-test` / `--read-frozen`。

    python -m experiments.p1.run --fit-train-edges   # train-only，产出 p1_train_edges.json
    python -m experiments.p1.run --formal-test        # 单次 exposure（Review 批准后执行）
    python -m experiments.p1.run --read-frozen        # 只读冻结 verdict
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from patent_preexperiment.p1.runner import (
    read_frozen,
    run_fit_train_edges,
    run_formal_test,
)

IMPL = Path(__file__).resolve().parents[2]


def main() -> int:
    args = sys.argv[1:]
    if "--fit-train-edges" in args:
        out = run_fit_train_edges(IMPL)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if "--formal-test" in args:
        out = run_formal_test(IMPL)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if "--read-frozen" in args:
        out = read_frozen(IMPL)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
