"""文献文本层三诊脚本：递归扫描相关文献目录，输出每个 PDF 的页数与可提取文本量。

用途：在 MarkItDown 批量转换前判定哪些 PDF 有文本层（可直转）、哪些是纯图像件
（无文本层，MarkItDown 输出为空，需标注并在台账中单列）。只读 PDF，不做任何修改。

用法：
    venv/Scripts/python.exe patent_preexperiment/literature/tools/probe_textlayer.py

输出：
    patent_preexperiment/literature/manifests/text_layer_probe.csv
"""

# ruff: noqa: E501 —— 中文文档串/台账数据行刻意保持单行，超过 100 字符列宽

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(r"D:\Users\Micko\Documents\工作\华润集控\光储充\相关文献")
OUT = Path(__file__).resolve().parents[1] / "manifests" / "text_layer_probe.csv"


def cjk_count(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    pdfs = sorted(ROOT.rglob("*.pdf"))
    print(f"found {len(pdfs)} pdfs under {ROOT}")
    for idx, path in enumerate(pdfs, 1):
        rel = str(path.relative_to(ROOT))
        size = path.stat().st_size
        pages = -1
        chars = 0
        cjk = 0
        status = "ok"
        t0 = time.time()
        try:
            pdf = pdfium.PdfDocument(str(path))
            pages = len(pdf)
            for i in range(pages):
                try:
                    textpage = pdf[i].get_textpage()
                    text = textpage.get_text_range()
                    chars += len(text)
                    cjk += cjk_count(text)
                except Exception:  # noqa: BLE001 单页失败不中断
                    continue
            pdf.close()
            if chars == 0:
                status = "image_only"
        except Exception as exc:  # noqa: BLE001
            status = f"error: {type(exc).__name__}"
        rows.append(
            {
                "rel_path": rel,
                "subdir": path.parent.name if path.parent != ROOT else "(root)",
                "size_bytes": size,
                "pages": pages,
                "text_chars": chars,
                "cjk_chars": cjk,
                "status": status,
                "elapsed_s": round(time.time() - t0, 2),
            }
        )
        print(
            f"[{idx:3d}/{len(pdfs)}] {status:12s} pages={pages:4d} cjk={cjk:7d} {rel}",
            flush=True,
        )
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"written {OUT}")
    n_image = sum(1 for r in rows if r["status"] == "image_only")
    n_err = sum(1 for r in rows if r["status"].startswith("error"))
    print(
        f"summary: total={len(rows)} with_text={len(rows) - n_image - n_err} "
        f"image_only={n_image} error={n_err}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
