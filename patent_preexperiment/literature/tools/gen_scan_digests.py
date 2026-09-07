# ruff: noqa: E501 —— 中文路径串刻意保持单行

"""机制扫描矩阵定向摘要生成器（07 号方法 §3，主循环混合方案）。

对 65 篇 OCR 全文生成定向摘要（digest），供主循环分优先级读取：
- P1（高相关篇目）：权利要求书起 4500 字 + 发明内容起 2500 字；
- P2（其余）：权利要求书起 1600 字（通常覆盖权利要求 1）。
找不到"权利要求"标记时回退取头部。输出 manifests/mechanism_scan/digests/lit_NN.md。

用法：
    venv/Scripts/python.exe patent_preexperiment/literature/tools/gen_scan_digests.py
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

LIT_ROOT = Path(__file__).resolve().parents[1]
LEDGER = LIT_ROOT / "manifests" / "literature_ledger.csv"
OUT_DIR = LIT_ROOT / "manifests" / "mechanism_scan" / "digests"

P1 = {17, 19, 25, 26, 27, 28, 29, 30, 39, 40, 41, 71, 78, 87, 94, 96, 104}
P1_CLAIMS = 4500
P1_CONTENT = 2500
P2_CLAIMS = 1600


def slice_from(text: str, marker: str, n: int) -> str:
    i = text.find(marker)
    if i < 0:
        return ""
    return text[i : i + n]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with LEDGER.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_p1 = n_p2 = 0
    for r in rows:
        if r["证据层级"] != "全文级(OCR)":
            continue
        lit = int(r["lit_id"])
        stem = r["文件名"][:-4]
        src = LIT_ROOT / "converted_ocr" / r["子库"] / f"{stem}.fulltext.md"
        text = src.read_text(encoding="utf-8")
        # 去页标记与多余空白，压缩读取量
        text = re.sub(r"<!-- page \d+ -->", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        tier = "P1" if lit in P1 else "P2"
        if tier == "P1":
            claims = slice_from(text, "权利要求", P1_CLAIMS)
            content = slice_from(text, "发明内容", P1_CONTENT)
            body = (
                f"# lit{lit} {stem} [{tier}] {r['公开号_出处']}\n\n"
                f"## 权利要求起\n{claims or text[:2500]}\n\n## 发明内容起\n{content}"
            )
            n_p1 += 1
        else:
            claims = slice_from(text, "权利要求", P2_CLAIMS)
            body = f"# lit{lit} {stem} [{tier}] {r['公开号_出处']}\n\n{claims or text[:1200]}"
            n_p2 += 1
        (OUT_DIR / f"lit{lit}.md").write_text(body, encoding="utf-8")
    print(f"P1={n_p1} P2={n_p2} digests written to {OUT_DIR}")


if __name__ == "__main__":
    main()
