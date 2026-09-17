# Family A 第二轮：4 件核心文献 claim-level 核验留痕

> **日期**：2026-09-17
> **性质**：探索轨 3-a 第二轮（Family A Second-Level Attack）的**证据留痕**，不是结论文件。
> **纪律**：本项目口径 —— *读落地页不算审计*。本目录保存 4 件文献的**权利要求原文**与元数据，
> 供结构矩阵（`structure_matrix.md`）与 V0.2 报告引用。
> **不得**作为 A/C 第一波申请文本的支持或证据；**不改变** `core-patent=NO-GO / Round 5=NOT STARTED`。

## 检索通道与证据等级

| 文献 | 通道 | 是否拿到**编号权项全文** | 本文件 |
|---|---|---|---|
| US20250326322A1 | patents.google.com/patent/US20250326322A1/en | ✅ 权 1–53（含独立权 1/14/26/27/40/53） | `US20250326322A1_claims.txt` |
| WO2024105191A1 | freepatentsonline.com/WO2024105191A1.html | ✅ 权 1–34 | `WO2024105191A1_claims.txt` |
| US12165224B2 | freepatentsonline.com/12165224.html | ✅ 权 1–20 | `US12165224B2_claims.txt` |
| CN111098724B | patents.google.com/patent/CN111098724B/en | ✅ 权 1–8 | `CN111098724B_claims.txt` |

### 通道失败记录（重要，避免重复踩坑）

- **Google Patents 的 claim 区是前端渲染**：WO2024105191A1 与 US12165224B2 经 Google Patents
  抓取时**只返回 Description / Definitions 段，claim 段为空**。若就此下结论，会重复
  `f764a0a` 中 CN120197914B 的错误（*凭摘要/首项权利要求下结论*）。
- **Espacenet 旧版 URL 已失效**：`worldwide.espacenet.com/publicationDetails/claims?...`
  只返回导航壳，无正文。
- **可用替代**：`freepatentsonline.com` 对本轮两件 US/WO **均给出编号权项全文**。

## 元数据

| 文献 | 标题 | 权利人 | 优先权日 | 公开/授权日 | 权项数 |
|---|---|---|---|---|---|
| US20250326322A1 | Power and energy reservation system (PERS) and method for electric vehicle (EV) charging | Barrellcharge Solutions Inc | 2024-04-22 | 2025-10-23（A1 公开） | 53 |
| WO2024105191A1 | System and method for mitigating delays and uncertainties in electric vehicle fleet charging by optimally sizing an energy-time reserve to maintain a vehicle readiness service level | Hitachi Energy Ltd | 2022-11-18 | 2024-05-23（A1 公开） | 34 |
| US12165224B2 | Electric vehicle charging reservation timeslot reallocation | Kyndryl Inc | 2021-12-10 | 2024-12-10（授权） | 20 |
| CN111098724B | 电动汽车预约充电控制方法及系统 | 长城汽车股份有限公司 | 2018-10-29（申请日） | 2023-09-05（授权） | 8 |

> **注意**：US20250326322A1 与 WO2024105191A1 均为 **A1 公开文本**，非授权文本，
> 权利范围可能变动；引用时须写明所据文本版本。
