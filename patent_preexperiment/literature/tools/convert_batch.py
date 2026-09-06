"""相关文献批量转换脚本（留痕版）。

职责：
1. 对 相关文献 目录下全部 PDF 计算 SHA256（去重与完整性留痕）；
2. 对文本层三诊（text_layer_probe.csv）判定为可转的 PDF 用 MarkItDown 转出 Markdown；
3. 三诊报错文件走回退链：pypdfium2 → markitdown(pdfplumber) → pdftotext(poppler)；
4. 输出 conversion_log.csv：源文件哈希/大小/时间、转换状态、输出路径、字符统计、
   工具与耗时——后续台账与审查均以该日志为口径。

不修改任何源文件。复现：
    venv/Scripts/python.exe patent_preexperiment/literature/tools/convert_batch.py
"""

# ruff: noqa: E501 —— 中文文档串/台账数据行刻意保持单行，超过 100 字符列宽

from __future__ import annotations

import csv
import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pypdfium2 as pdfium
from markitdown import MarkItDown

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC_ROOT = Path(r"D:\Users\Micko\Documents\工作\华润集控\光储充\相关文献")
LIT_ROOT = Path(__file__).resolve().parents[1]
PROBE_CSV = LIT_ROOT / "manifests" / "text_layer_probe.csv"
OUT_DIR = LIT_ROOT / "converted"
LOG_CSV = LIT_ROOT / "manifests" / "conversion_log.csv"

TOOLCHAIN = "markitdown 0.1.7 (pdfplumber 0.11.10 / pypdfium2 5.13.0)"


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def extract_pypdfium2(path: Path) -> str:
    pdf = pdfium.PdfDocument(str(path))
    parts = []
    for i in range(len(pdf)):
        try:
            parts.append(pdf[i].get_textpage().get_text_range())
        except Exception:  # noqa: BLE001
            continue
    pdf.close()
    return "\n\n".join(parts)


def extract_pdftotext(path: Path) -> str:
    out = path.with_suffix(".pdftotext.txt")
    try:
        subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(path), str(out)],
            check=True,
            capture_output=True,
            timeout=300,
        )
        return out.read_text(encoding="utf-8", errors="replace")
    finally:
        if out.exists():
            out.unlink()


def main() -> None:
    probe = {
        r["rel_path"]: r
        for r in csv.DictReader(PROBE_CSV.open(encoding="utf-8-sig"))
    }
    md = MarkItDown()
    rows = []
    dup_seen: dict[str, str] = {}
    pdfs = sorted(SRC_ROOT.rglob("*.pdf"))
    print(f"total pdfs: {len(pdfs)}")

    for idx, src in enumerate(pdfs, 1):
        rel = str(src.relative_to(SRC_ROOT))
        probe_row = probe.get(rel, {})
        t0 = time.time()
        h = sha256_of(src)
        dup_note = ""
        if h in dup_seen:
            dup_note = f"duplicate_of:{dup_seen[h]}"
        else:
            dup_seen[h] = rel

        subdir = src.parent.name if src.parent != SRC_ROOT else "顶层"
        out_dir = OUT_DIR / subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (src.stem + ".md")

        status = "skipped_image_only"
        tool = ""
        text = ""
        if probe_row.get("status", "").startswith("error"):
            # 三级回退链
            for name, fn in (
                ("pypdfium2-retry", extract_pypdfium2),
                ("markitdown-pdfplumber", lambda p: md.convert(str(p)).markdown),
                ("pdftotext-poppler", extract_pdftotext),
            ):
                try:
                    text = fn(src)
                except Exception as exc:  # noqa: BLE001
                    text = ""
                    print(f"  fallback {name} failed: {type(exc).__name__}")
                if text and text.strip():
                    status = "converted"
                    tool = f"fallback:{name}"
                    break
        elif probe_row.get("status") == "ok":
            try:
                result = md.convert(str(src))
                text = getattr(result, "markdown", None) or getattr(
                    result, "text_content", ""
                )
                status = "converted" if text.strip() else "empty_output"
                tool = TOOLCHAIN if text.strip() else ""
            except Exception as exc:  # noqa: BLE001
                status = f"error: {type(exc).__name__}"
                text = ""

        if text.strip() and not out_path.exists():
            header = (
                f"<!--\nsource: {SRC_ROOT / rel}\nsha256: {h}\n"
                f"converted_at: {datetime.now().isoformat(timespec='seconds')}\n"
                f"tool: {tool or TOOLCHAIN}\n-->\n\n"
            )
            out_path.write_text(header + text, encoding="utf-8")

        out_chars = len(text)
        out_cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        if status == "skipped_image_only":
            out_path_col = ""
            out_chars = out_cjk = 0
        else:
            out_path_col = str(out_path.relative_to(LIT_ROOT))

        rows.append(
            {
                "rel_path": rel,
                "subdir": subdir,
                "size_bytes": src.stat().st_size,
                "sha256": h,
                "mtime": datetime.fromtimestamp(src.stat().st_mtime).isoformat(
                    timespec="seconds"
                ),
                "probe_status": probe_row.get("status", ""),
                "conv_status": status,
                "tool": tool,
                "out_rel_path": out_path_col,
                "out_chars": out_chars,
                "out_cjk_chars": out_cjk,
                "elapsed_s": round(time.time() - t0, 2),
                "note": dup_note,
            }
        )
        print(
            f"[{idx:3d}/{len(pdfs)}] {status:20s} cjk={out_cjk:7d} {rel}",
            flush=True,
        )

    with LOG_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"written {LOG_CSV}")
    from collections import Counter

    print("conv_status:", dict(Counter(r["conv_status"] for r in rows)))
    dups = [r for r in rows if r["note"]]
    for r in dups:
        print("DUP:", r["rel_path"], "->", r["note"])


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    main()
