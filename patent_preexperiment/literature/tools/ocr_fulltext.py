# ruff: noqa: E501 —— 中文文档串刻意保持单行

"""单文件 PDF 全文 OCR 工具（留痕版）。

用途：对无文本层的关键复核对象做全文 OCR（当前仅 CN122371331A，源文件
`商业产业园区光储充多能互补协同优化方法及系统.pdf`）。与扉页工具不同，本工具
逐页渲染并 OCR 全部页面，输出带页码标记的全文 Markdown，供权利要求级复核引用；
每页字符数写入 ocr_fulltext_log.csv 留痕。仅产出复核底稿，不改变台账结论。

用法：
    venv/Scripts/python.exe patent_preexperiment/literature/tools/ocr_fulltext.py <顶层文件名.pdf> [dpi]

输出：
    literature/converted_ocr/<子库>/<原名>.fulltext.md（每页以 <!-- page N --> 分隔）
    literature/manifests/ocr_fulltext_log.csv（追加模式）
"""

from __future__ import annotations

import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from rapidocr_onnxruntime import RapidOCR

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC_ROOT = Path(r"D:\Users\Micko\Documents\工作\华润集控\光储充\相关文献")
LIT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = LIT_ROOT / "converted_ocr"
LOG_CSV = LIT_ROOT / "manifests" / "ocr_fulltext_log.csv"


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: ocr_fulltext.py <pdf filename under SRC_ROOT> [dpi]")
        sys.exit(2)
    rel = sys.argv[1]
    dpi = int(sys.argv[2]) if len(sys.argv) > 2 else 240
    src = SRC_ROOT / rel
    if not src.exists():
        print(f"not found: {src}")
        sys.exit(2)
    subdir = src.parent.name if src.parent != SRC_ROOT else "顶层"
    out_dir = OUT_DIR / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (src.stem + ".fulltext.md")

    engine = RapidOCR()
    pdf = pdfium.PdfDocument(str(src))
    n_pages = len(pdf)
    print(f"ocr fulltext: {rel} pages={n_pages} dpi={dpi}", flush=True)
    t0 = time.time()
    page_stats = []
    chunks = []
    for i in range(n_pages):
        tp = time.time()
        pil = pdf[i].render(scale=dpi / 72).to_pil().convert("RGB")
        result, _ = engine(np.asarray(pil))
        text = "\n".join(item[1] for item in result) if result else ""
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        page_stats.append((i + 1, cjk, round(time.time() - tp, 1)))
        chunks.append(f"<!-- page {i + 1} -->\n\n{text}")
        print(f"  page {i + 1:3d}/{n_pages} cjk={cjk:5d} {time.time() - tp:.1f}s", flush=True)
    pdf.close()

    header = (
        f"<!--\nsource: {src}\nsha256: {sha256_of(src)}\n"
        f"ocred_at: {datetime.now().isoformat(timespec='seconds')}\n"
        f"ocr_pages: {n_pages} dpi: {dpi}\n"
        "tool: rapidocr-onnxruntime 1.4.4 + pypdfium2 render\n"
        "note: 全文 OCR 底稿，仅用于权利要求级复核引用，OCR 错漏以源 PDF 为准\n-->\n\n"
    )
    out_path.write_text(header + "\n\n".join(chunks), encoding="utf-8")

    new_log = not LOG_CSV.exists()
    with LOG_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(
                ["rel_path", "sha256", "dpi", "pages", "page_cjk", "elapsed_s", "ocred_at"]
            )
        w.writerow(
            [
                rel,
                sha256_of(src),
                dpi,
                n_pages,
                ";".join(f"{p}:{c}" for p, c, _ in page_stats),
                round(time.time() - t0, 1),
                datetime.now().isoformat(timespec="seconds"),
            ]
        )
    total_cjk = sum(c for _, c, _ in page_stats)
    print(f"written {out_path} total_cjk={total_cjk} elapsed={time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
