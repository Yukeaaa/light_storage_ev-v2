# ruff: noqa: E501

"""批量 OCR 全文转换脚本（ocrmypdf + PyMuPDF 提取）。

流程：
1. 从台账 CSV 读取所有扉页级 PDF 的 lit_id、文件名、子库。
2. 对每份 PDF：
   a. 用 ocrmypdf --language chi_sim+eng 在临时目录注入文本层。
   b. 用 PyMuPDF (pymupdf) 逐页提取注入后的文本。
   c. 输出 .fulltext.md 到 converted_ocr/<子库>/。
3. 更新台账 CSV：处理成功的行证据层级 → 全文级(OCR)。

用法：
    python batch_ocr_fulltext.py [--ids 17,18,19] [--dry-run]

不指定 --ids 时处理全部扉页级 PDF。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pymupdf  # PyMuPDF

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC_ROOT = Path(r"D:\Users\Micko\Documents\工作\华润集控\光储充\相关文献")
LIT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = LIT_ROOT / "converted_ocr"
LEDGER_CSV = LIT_ROOT / "manifests" / "literature_ledger.csv"
LOG_CSV = LIT_ROOT / "manifests" / "batch_ocr_fulltext_log.csv"


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def ocrmypdf_ocr(src: Path, dst: Path) -> None:
    """用 ocrmypdf 给 PDF 注入文本层（chi_sim+eng）."""
    cmd = [
        "ocrmypdf",
        "--language", "chi_sim+eng",
        "--force-ocr",
        "--output-type", "pdf",
        "--jobs", "4",
        str(src),
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"ocrmypdf failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )


def extract_text(ocr_pdf: Path) -> tuple[list[str], int]:
    """用 PyMuPDF 逐页提取文本，返回 (pages_text, total_cjk)."""
    doc = pymupdf.open(str(ocr_pdf))
    pages_text = []
    total_cjk = 0
    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text("text")
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        total_cjk += cjk
        pages_text.append(text)
    doc.close()
    return pages_text, total_cjk


def write_fulltext_md(
    out_path: Path,
    src_path: Path,
    pages_text: list[str],
    total_cjk: int,
    dpi: int = 0,
) -> None:
    """写入带页码标记的全文 Markdown."""
    header = (
        f"<!--\n"
        f"source: {src_path}\n"
        f"sha256: {sha256_of(src_path)}\n"
        f"ocred_at: {datetime.now().isoformat(timespec='seconds')}\n"
        f"ocr_pages: {len(pages_text)} tool: ocrmypdf chi_sim+eng + pymupdf extract\n"
        f"total_cjk: {total_cjk}\n"
        f"note: 全文 OCR 底稿，仅用于权利要求级复核引用，OCR 错漏以源 PDF 为准\n"
        f"-->\n\n"
    )
    chunks = []
    for i, text in enumerate(pages_text):
        chunks.append(f"<!-- page {i + 1} -->\n\n{text}")
    out_path.write_text(header + "\n\n".join(chunks), encoding="utf-8")


def append_log(rel_path: str, sha: str, pages: int, total_cjk: int, elapsed: float, status: str, error_msg: str = "") -> None:
    new_log = not LOG_CSV.exists()
    with LOG_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["rel_path", "sha256_12", "pages", "total_cjk", "elapsed_s", "status", "error", "ocred_at"])
        w.writerow([rel_path, sha[:12], pages, total_cjk, round(elapsed, 1), status, error_msg, datetime.now().isoformat(timespec="seconds")])


def update_ledger(lit_ids_success: list[int]) -> None:
    """将成功的 lit_id 在台账中更新为全文级(OCR)."""
    df_exists = LEDGER_CSV.exists()
    if not df_exists:
        print("[WARN] ledger CSV not found, skipping update")
        return
    import pandas as pd
    df = pd.read_csv(LEDGER_CSV)
    mask = df["lit_id"].isin(lit_ids_success) & (df["证据层级"] == "扉页级")
    n_updated = int(mask.sum())
    if n_updated:
        df.loc[mask, "证据层级"] = "全文级(OCR)"
        df.to_csv(LEDGER_CSV, index=False, encoding="utf-8-sig")
        print(f"[LEDGER] updated {n_updated} row(s) to 全文级(OCR)")
    else:
        print("[LEDGER] no rows to update")


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch OCR fulltext for frontpage-only PDFs")
    parser.add_argument("--ids", type=str, default="", help="Comma-separated lit_ids to process (empty=all)")
    parser.add_argument("--dry-run", action="store_true", help="List targets only, do not process")
    args = parser.parse_args()

    # Load ledger
    df = pd.read_csv(LEDGER_CSV)
    fp_mask = df["证据层级"] == "扉页级"
    targets = df[fp_mask].copy()

    if args.ids.strip():
        id_list = [int(x.strip()) for x in args.ids.split(",")]
        targets = targets[targets["lit_id"].isin(id_list)]
        print(f"[FILTER] selected {len(targets)} of {df[fp_mask].shape[0]} frontpage rows (ids={id_list})")
    else:
        print(f"[ALL] {len(targets)} frontpage rows to process")

    if args.dry_run:
        for _, r in targets.iterrows():
            print(f"  lit_id={int(r['lit_id']):3d}  [{r['子库']}] {r['文件名']}")
        return

    # Process each
    lit_ids_success = []
    n_total = len(targets)
    for idx, (_, r) in enumerate(targets.iterrows(), 1):
        lit_id = int(r["lit_id"])
        fname = r["文件名"]
        sublib = r["子库"]
        rel_path = f"{sublib}/{fname}" if sublib != "顶层" else fname

        src = SRC_ROOT / sublib / fname if sublib != "顶层" else SRC_ROOT / fname
        if not src.exists():
            print(f"[{idx:2d}/{n_total}] SKIP src missing: {src.name}")
            append_log(rel_path, "", 0, 0, 0, "SKIP_SRC_MISSING", "source PDF not found")
            continue

        sha = sha256_of(src)
        out_dir = OUT_DIR / sublib
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (src.stem + ".fulltext.md")

        # Skip if fulltext already exists
        if out_path.exists():
            cjk_check = sum(1 for ch in out_path.read_text(encoding="utf-8") if "\u4e00" <= ch <= "\u9fff")
            if cjk_check > 100:
                print(f"[{idx:2d}/{n_total}] SKIP already done (cjk={cjk_check}): {fname[:40]}")
                lit_ids_success.append(lit_id)
                continue

        print(f"[{idx:2d}/{n_total}] OCR: {fname[:45]}")
        t0 = time.time()
        pages_text = []
        total_cjk = 0
        n_pages = 0
        error_msg = ""
        status = "FAIL"

        try:
            with tempfile.TemporaryDirectory(prefix="ocr_") as tmpdir:
                tmp_ocr = Path(tmpdir) / "ocr_output.pdf"
                # Step 1: ocrmypdf
                print(f"  ocrmypdf...", flush=True)
                ocrmypdf_ocr(src, tmp_ocr)
                # Step 2: PyMuPDF extract
                print(f"  extract...", flush=True)
                pages_text, total_cjk = extract_text(tmp_ocr)
                n_pages = len(pages_text)

            if total_cjk < 50:
                raise RuntimeError(f"Very low CJK count ({total_cjk}), OCR likely failed")

            # Step 3: write
            write_fulltext_md(out_path, src, pages_text, total_cjk)
            status = "OK"
            lit_ids_success.append(lit_id)
            elapsed = round(time.time() - t0, 1)
            print(f"  OK pages={n_pages} cjk={total_cjk} {elapsed}s")

        except Exception as exc:
            error_msg = str(exc)[:300]
            elapsed = round(time.time() - t0, 1)
            status = f"FAIL:{type(exc).__name__}"
            print(f"  FAIL after {elapsed}s: {error_msg[:120]}")

        append_log(rel_path, sha[:12], n_pages, total_cjk, round(time.time() - t0, 1), status, error_msg)

    # Update ledger
    if lit_ids_success:
        update_ledger(lit_ids_success)

    print(f"\n[DONE] success={len(lit_ids_success)}/{n_total}")


if __name__ == "__main__":
    import pandas as pd
    main()
