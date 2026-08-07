"""E0F-01/01.1 运行器：全量输入 manifest + 数据质量审计 + connectionTime 审计 + 冻结产物。

依据：V2.1 §10；审查结论7 §5；审查结论9；审查结论10（P0-1/P0-2/P1）。
用法：python experiments/e0_full/run.py [--workers N] [--reuse-manifest] [--allow-dirty-code]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from patent_preexperiment.e0_full.input_audit import run_e0f01

REPO = Path(__file__).resolve().parents[3]
IMPL = REPO / "patent_preexperiment"
CONFIG = IMPL / "configs" / "e0_full.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="E0F-01/01.1 全量输入审计")
    parser.add_argument("--workers", type=int, default=1, help="扫描并行进程数")
    parser.add_argument(
        "--reuse-manifest",
        action="store_true",
        help="复用已存在的 manifest（迭代用；正式冻结默认全量重扫）",
    )
    parser.add_argument(
        "--allow-dirty-code",
        action="store_true",
        help="允许在存在未提交代码时生成 frozen baseline（仅调试用，正式冻结禁止）",
    )
    args = parser.parse_args()

    outputs = run_e0f01(
        cfg_path=CONFIG,
        workers=args.workers,
        reuse_manifest=args.reuse_manifest,
        require_clean_baseline=not args.allow_dirty_code,
    )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    quality_path = IMPL / "data_registry" / "e0_full_quality_summary.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    print("stop_lines passed:", quality["stop_lines"]["passed"])
    print("checks:", json.dumps(quality["stop_lines"]["checks"], ensure_ascii=False))
    return None


if __name__ == "__main__":
    sys.exit(main())
