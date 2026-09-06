"""图像件 PDF 扉页 OCR 脚本（留痕版）。

职责：对文本层三诊判定为 image_only / error 的 PDF（全部为扫描图像件，多为 CNIPA
专利公开文本），仅渲染并 OCR 第 1 页（信息不足时加第 2 页，上限 2 页），提取
公开号/申请人/标题/摘要等扉页信息。不做全文 OCR；输出文件名以 .frontpage.md 结尾，
并在文件头明确标注"扉页 OCR 非全文"。

输出：
    literature/converted_ocr/<子库>/<原名>.frontpage.md
    literature/manifests/ocr_frontpage_log.csv

复现：
    venv/Scripts/python.exe patent_preexperiment/literature/tools/ocr_frontpage.py
"""

# ruff: noqa: E501 —— 中文文档串/台账数据行刻意保持单行，超过 100 字符列宽

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
PROBE_CSV = LIT_ROOT / "manifests" / "text_layer_probe.csv"
OUT_DIR = LIT_ROOT / "converted_ocr"
LOG_CSV = LIT_ROOT / "manifests" / "ocr_frontpage_log.csv"
SCALE = 220 / 72  # 220 DPI
MIN_CJK_PAGE1 = 30  # 第 1 页低于该中文字符数则追加第 2 页


def ocr_page(engine: RapidOCR, page: pdfium.PdfPage) -> tuple[str, int]:
    pil = page.render(scale=SCALE).to_pil().convert("RGB")
    result, _ = engine(np.asarray(pil))
    if not result:
        return "", 0
    lines = [item[1] for item in result]
    text = "\n".join(lines)
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return text, cjk


def main() -> None:
    probe = list(csv.DictReader(PROBE_CSV.open(encoding="utf-8-sig")))
    targets = [
        r
        for r in probe
        if r["status"] == "image_only" or r["status"].startswith("error")
    ]
    print(f"targets: {len(targets)}")
    engine = RapidOCR()
    rows = []
    for idx, row in enumerate(targets, 1):
        rel = row["rel_path"]
        src = SRC_ROOT / rel
        t0 = time.time()
        subdir = src.parent.name if src.parent != SRC_ROOT else "顶层"
        out_dir = OUT_DIR / subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (src.stem + ".frontpage.md")
        pages_done: list[int] = []
        texts: list[str] = []
        status = "ok"
        try:
            pdf = pdfium.PdfDocument(str(src))
            n_pages = len(pdf)
            text1, cjk1 = ocr_page(engine, pdf[0])
            pages_done.append(1)
            texts.append(text1)
            if cjk1 < MIN_CJK_PAGE1 and n_pages > 1:
                text2, _ = ocr_page(engine, pdf[1])
                pages_done.append(2)
                texts.append(text2)
            pdf.close()
        except Exception as exc:  # noqa: BLE001
            status = f"error: {type(exc).__name__}"
            texts = []
        joined = "\n\n".join(t for t in texts if t)
        cjk_total = sum(1 for ch in joined if "\u4e00" <= ch <= "\u9fff")
        if joined.strip() and status == "ok":
            header = (
                f"<!--\nsource: {src}\nocred_at: {datetime.now().isoformat(timespec='seconds')}\n"
                f"ocr_pages: {pages_done} (扉页 OCR，非全文；全文未数字化)\n"
                "tool: rapidocr-onnxruntime 1.4.4 + pypdfium2 render 220dpi\n-->\n\n"
            )
            out_path.write_text(header + joined, encoding="utf-8")
        rows.append(
            {
                "rel_path": rel,
                "subdir": subdir,
                "probe_status": row["status"],
                "ocr_status": status,
                "pages_ocr": ";".join(map(str, pages_done)),
                "out_rel_path": str(out_path.relative_to(LIT_ROOT))
                if joined.strip()
                else "",
                "out_cjk_chars": cjk_total,
                "elapsed_s": round(time.time() - t0, 2),
            }
        )
        print(
            f"[{idx:3d}/{len(targets)}] {status:24s} pages={pages_done} cjk={cjk_total:5d} {rel}",
            flush=True,
        )
    with LOG_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"written {LOG_CSV}")
    ok = sum(1 for r in rows if r["ocr_status"] == "ok" and r["out_cjk_chars"] > 0)
    print(f"summary: total={len(rows)} ok_with_text={ok}")


if __name__ == "__main__":
    main()
