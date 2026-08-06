"""K0 运行器：冻结基线 + 最小数据校验（V2.1 §4.1）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from patent_preexperiment.registry.k0 import build_design_baseline, check_core_data

REPO = Path(__file__).resolve().parents[3]  # 仓库根
IMPL = REPO / "patent_preexperiment"


def main() -> None:
    for rel in ("data_registry/design_baseline.json", "data_registry/k0_data_check.json"):
        (IMPL / rel).parent.mkdir(parents=True, exist_ok=True)

    baseline = build_design_baseline(IMPL / "data_registry" / "design_baseline.json")
    check = check_core_data(IMPL / "data_registry" / "k0_data_check.json")

    print(json.dumps({"commit": baseline["commit"], "data_version": baseline["data_version"]}, ensure_ascii=False))
    print("manifest rows:", {k: v["rows"] for k, v in check["manifests"].items()})
    print("match_status ok:", check["match_status"]["ok"], "| gold ok:", check["gold"]["ok"], "| PASSED:", check["passed"])


if __name__ == "__main__":
    sys.exit(main())
