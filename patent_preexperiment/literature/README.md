# literature/ — 相关文献整理留痕目录

本目录存放用户提供文献库（`D:\Users\Micko\Documents\工作\华润集控\光储充\相关文献`，108 篇 PDF）的**转换产物、清单与工具**。源 PDF 一律只读、不改动、不复制入库。台账结论与使用指南见 `reports/literature/01_相关文献台账_108篇处理留痕与五步链威胁初判.md`（2026-09-07）。

## 目录结构

```
literature/
├── converted/            # 42 篇有文本层 PDF 的 MarkItDown 全文（UTF-8，头部含溯源注释）
│   ├── 顶层/  可信/  大模型/
├── converted_ocr/        # 65 个图像件（CNIPA 专利）的扉页 OCR 文本（*.frontpage.md，仅第 1 页、至多 2 页，非全文）
│   ├── 顶层/  大模型/
├── manifests/            # 四份清单（均为 UTF-8-SIG CSV，Excel 可直开）
│   ├── text_layer_probe.csv    # 文本层三诊：页数/字符数/status（ok / image_only / error）
│   ├── conversion_log.csv      # 转换日志：全量 SHA256、大小、mtime、conv_status、工具、耗时
│   ├── ocr_frontpage_log.csv   # 扉页 OCR 日志：OCR 页码、字符数、状态
│   └── literature_ledger.csv   # 台账主表（108 行，关联 SHA256 短哈希 + 相关度/威胁/五步链初判）
└── tools/                # 四个可复现脚本（只读源文件）
```

## 处理链路（2026-09-07）

1. `tools/probe_textlayer.py`：pypdfium2 全页文本统计 → 42 有文本层 / 65 纯图像件 / 1 报错。
2. `tools/convert_batch.py`：markitdown 0.1.7（pdfplumber 0.11.10 / pypdfium2 5.13.0）库内调用转 42 篇全文；报错件走 pypdfium2 → pdfplumber → pdftotext(poppler) 三级回退仍失败，判定文件损坏（`大模型\大模型技术赋能电力系统的应用及技术路线展望.pdf`，待人工副本）。
3. `tools/ocr_frontpage.py`：rapidocr-onnxruntime 1.4.4 + pypdfium2 220dpi 渲染，对 66 个图像/损坏件做扉页 OCR，65 成功（2 篇低信息）。
4. `tools/build_ledger.py`：结构化初判（7 个摘要批次产出，见 reports/literature/02、03 号附录）与 conversion_log 的 SHA256 关联成台账主表，108 行全部匹配。

## 复现命令（仓库根目录）

```bash
venv/Scripts/python.exe patent_preexperiment/literature/tools/probe_textlayer.py
venv/Scripts/python.exe patent_preexperiment/literature/tools/convert_batch.py
venv/Scripts/python.exe patent_preexperiment/literature/tools/ocr_frontpage.py
venv/Scripts/python.exe patent_preexperiment/literature/tools/build_ledger.py
```

## 关键口径与坑

- **Windows 中文控制台必须 `PYTHONUTF8=1`**（或在库内调用 + 显式 `encoding="utf-8"` 写文件），否则 MarkItDown CLI 输出经 cp936 转码乱码。
- 图像件只做**扉页级** OCR：台账中公开号/申请人/摘要均为初判（信息可信度低），引用前必须回全文；`*.frontpage.md` 不是全文。
- 去重：`人工智能在储能技术中的应用进展 (1).pdf` 与无后缀版 SHA256 完全相同（台账 62/63 号合并）；`基于大模型驱动的电网智能体自适应优化` 两文件 SHA256 不同但公开号同为 CN122334622A（96/97 号，同一专利重复下载）。源文件均未删除。
- 转换瑕疵件（引用细节需回原文）：顶层 11 号（2017 全角错序）、顶层 9 号（文末串入他文 2 页）、顶层 13 号（刊名由 DOI 前缀推断）、可信 43 号（OCR 破碎）、可信 44 号（含 19 个 NUL 字节，Read 工具会拒读，grep 加 `-a`）、大模型 53 号（含异常字节，同上）。
- 治理定位：本目录与 reports/literature/ 是**文献整理与方向探索支撑**，不构成新的检索行为，不改变 core-patent status = NO-GO、PO-SEARCH-1 收口、D3 禁令、M2 HOLD；如需把其中文献纳入答审对比集，按 patent_definition/12 号"解析性重比对"口径执行。
