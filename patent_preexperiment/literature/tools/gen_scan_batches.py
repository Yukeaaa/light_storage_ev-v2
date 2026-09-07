# ruff: noqa: E501 —— 中文路径串刻意保持单行

"""机制扫描矩阵批次清单生成器（07 号方法 §3）。

从台账选取全部可用全文行，按文件大小加权装盒（单盒 ≤450KB、≤10 篇），
输出 literature/manifests/mechanism_scan/batches.json 供抽取子代理消费。

用法：
    venv/Scripts/python.exe patent_preexperiment/literature/tools/gen_scan_batches.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

LIT_ROOT = Path(__file__).resolve().parents[1]
LEDGER = LIT_ROOT / "manifests" / "literature_ledger.csv"
OUT_DIR = LIT_ROOT / "manifests" / "mechanism_scan"

CAP_BYTES = 450 * 1024
MAX_DOCS = 10


def fulltext_path(row: dict) -> Path | None:
    stem = row["文件名"][:-4]
    if row["证据层级"] == "全文级":
        return LIT_ROOT / "converted" / row["子库"] / f"{stem}.md"
    if row["证据层级"] in ("全文级(OCR)", "全文级(重复件)"):
        return LIT_ROOT / "converted_ocr" / row["子库"] / f"{stem}.fulltext.md"
    return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with LEDGER.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    docs, skipped = [], []
    for r in rows:
        if r["证据层级"] in ("损坏",):
            skipped.append((r["lit_id"], r["证据层级"], "损坏占位"))
            continue
        if r["证据层级"] == "全文级(重复件)":
            skipped.append((r["lit_id"], r["证据层级"], "重复件，聚合时指向同哈希主行"))
            continue
        p = fulltext_path(r)
        if p is None or not p.exists():
            skipped.append((r["lit_id"], r["证据层级"], f"文件缺失: {p}"))
            continue
        docs.append(
            {
                "lit_id": int(r["lit_id"]),
                "sublib": r["子库"],
                "filename": r["文件名"],
                "doc_type": r["类型"],
                "pub_no": r["公开号_出处"],
                "org": r["机构"],
                "year": r["年份"],
                "evidence": "markitdown" if r["证据层级"] == "全文级" else "ocr",
                "prior_hint": f'{r["威胁评估"]}|{r["五步链覆盖要点"]}|{r["一句话要点"]}',
                "path": str(p.relative_to(LIT_ROOT)),
                "bytes": p.stat().st_size,
            }
        )

    # 大文件优先装盒（first-fit decreasing）
    docs.sort(key=lambda d: -d["bytes"])
    bins: list[list[dict]] = []
    for d in docs:
        placed = False
        for b in bins:
            if len(b) < MAX_DOCS and sum(x["bytes"] for x in b) + d["bytes"] <= CAP_BYTES:
                b.append(d)
                placed = True
                break
        if not placed:
            bins.append([d])
    bins.sort(key=lambda b: min(x["lit_id"] for x in b))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "generated_at": "2026-09-07",
        "method": "first-fit decreasing, cap 450KB, max 10 docs",
        "n_docs": len(docs),
        "n_batches": len(bins),
        "skipped": skipped,
        "batches": [
            {
                "batch": i + 1,
                "n_docs": len(b),
                "total_kb": round(sum(x["bytes"] for x in b) / 1024),
                "docs": sorted(b, key=lambda x: x["lit_id"]),
            }
            for i, b in enumerate(bins)
        ],
    }
    (OUT_DIR / "batches.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"docs={len(docs)} batches={len(bins)} skipped={skipped}")
    for b in out["batches"]:
        ids = ",".join(str(d["lit_id"]) for d in b["docs"])
        print(f'batch {b["batch"]:2d}: {b["n_docs"]:2d}篇 {b["total_kb"]:4d}KB ids=[{ids}]')


if __name__ == "__main__":
    main()
