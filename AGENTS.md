# AGENTS.md

光储充（光伏-储能-充电）专利选题**预实验**工程（重启版）。目标不是做出最强算法，而是按"问题是否真实 → 是否可观测 → 简单基线是否够用 → 闭环是否改善 → 能否形成专利证据链"的顺序，产出可审计的 Go/No-Go 证据。

## 权威协议（先读，按它实现）

- `docs/工商业园区光储充_专利方向确定详细预实验计划书_V2.0.md` 是唯一执行协议。实验编号 E0–E8、阈值网格、Go/条件Go/No-Go 门、输出目录与每个实验的最少文件、12 周计划、阶段门模板全在其中。不要另起炉灶或自创实验体系。
- 工程落地细节（目录结构、数据契约、配置/预注册模板、模块接口、实施里程碑、首批 E0 任务）见 `docs/预实验工程实施方案与实验设计_V1.0.md`，它是 V2.0 的工程化/研究化实施方案，不改变实验编号与门标准。
- 上一版预实验在 `D:\JobWorkspaces\light_storage_ev`（v1：合成数据 + 动态能力匹配/滚动优化方向），效果不好已放弃，教训记录在 V2.0 §1.2（行为预测/自适应/鲁棒调度同效或收益不稳）。v1 仅可作代码与工具链参考，**不要沿用其合成数据方法与结论口径**。
- 主候选 D1-R（基于充电响应状态识别的可执行功率区间生成 + 同池回收重分配）；D2-R/D3-R 只有在 D1 链条中显示独立控制价值才升级。E1 问题强度与 E3 重分配机会任一不成立，不进入复杂模型。

## 数据（在仓库外）

- 仓库 `data/` 只有 `readme.md`，数据实际在 `D:\Users\Micko\Documents\工作\华润集控\光储充\数据`（路径含中文和空格，脚本中必须加引号）。
- 主数据集 `ACN-data/acn_project/` 已构建完成、可直接用：
  - `manifests/static_api_mapping.csv`：关联主表（96,467 行），`match_status` = matched 40,644 / static_only 45,233 / api_only 10,590。严格会话验证只用 `matched`；static_only 仅用于响应机制扩展。
  - `gold/benchmark_5min|15min/`：115 个桩点的 5/15 分钟基准，只含 matched 会话，覆盖 4 个车库（CG1、Arroyo、Parking Lot、office001）。用于 E3 控制池审计与 E4 回放。
  - 原始时序 `ACN-data/ACN-Data-Static/`（2018-05 ~ 2020-12，85,877 个文件，约 4.49 亿行）；API 会话元数据在 `acn_full/`。
  - 质量细节、字段覆盖、复现命令见 `ACN-data/acn_project/README.md`；数据下载/令牌约定见 `ACN-data/AGENTS.md`（令牌只从环境变量 `ACN_API_TOKEN` 读取，绝不落盘；不运行 timeseries 模式）。
- 必须遵守的口径：
  - 功率优先级：实测 Power → Voltage×Current（computed）→ 额定电压×Current（estimated 并标记）。额定电压：jpl=192.7V（按 kWhDelivered 校准，240V 假设高估 17.7%）、caltech=240V、office001=240V。
  - 字段覆盖：pilot 仅 46,173/85,877 文件、state 57,654、power 60,292；**JPL 约 90% 文件只有 current** —— current-only 回退是必做项，pilot 不能作为全量必要输入。
  - 能量一致性：caltech/office001 中位偏差 <1%（高可信主集）；jpl 中位 -5.3%、p95 +49.9%（聚合可用，会话级必须离群过滤并做敏感性）。
  - 低覆盖/异常月份 2019-12、2020-02、2020-04、2020-12 及 2021 全年只作 stress/敏感性，不进主切分（切分规则见 V2.0 §6.4）。
- UCSD 数据在 `UCSD-Microgrid-Database/`（BatteryStorage / ChargePointEV / PVGenerator / BuildingLoadWithEV 等），供 E7 站级嵌入；`UrbanEV/` 另作参考。

## 实验治理红线（勿违反）

- 预注册：阈值按 V2.0 §4.3 网格（1 分钟主粒度，P_on / δ_r / δ_p / T_event / 初始与尾段排除 / pilot 阶跃）在训练/验证集确定；测试集冻结后只跑一次，禁止在测试集上逐图调参。失败后新增方案必须新版本 + 新测试协议。
- 切分：站点时间顺序 60/20/20；Office001 只做外部验证，禁止用其结果改阈值。样本层 L0–L3 按 V2.0 §2.3 定义。
- 禁止在线特征：未来 disconnect / 最终 kWhDelivered / future doneChargingTime / 真实 SOC / 真实剩余需求 / 准确未来离场 / BMS 限功率 / PCS 拒绝原因。这些只能作离线标签或评价。
- 术语纪律：pilot 与 actual 的差异只能称"导引/允许电流与实际响应差异"，不得称"命令失败/拒绝"；只有自然 pilot 正阶跃验证过增量响应的才能谈"可吸收余量"；只用观察值称"预算差值"而非"可回收能力"；未通过 E4.1 验证的响应仿真器不得输出闭环收益结论。
- 统计：同会话/池/日/预算下配对比较；会话/日级 cluster bootstrap 95%CI，不把分钟点当独立样本；绝对量与相对量同报；必须报最差站点/月份/会话；每实验至少抽取 20 个失败案例。D1-R 主指标顺序：高估/未执行功率电量 → 站级预算跟踪残差 → 交付影响 → 动作与运行时间。

## 执行顺序与现状

- 顺序：E0 数据冻结 → E1 问题强度 → E2 可执行响应区间 → E3 重分配机会 → E4 闭环回放 → E5/E6（条件）→ E7 UCSD → E8 专利决策。E0.1–E0.5（数据注册表+哈希、1 分钟会话表、控制池表、split 注册表、普通控制器/分配器基线单测）全部通过才进 E1；基线单测失败时暂停所有候选比较。
- 当前仓库已完成 `patent_preexperiment/` 工程骨架与主要实验产物：`configs/`、`data_registry/`、`datasets/`（git 忽略，可重建）、`src/`、`experiments/`、`results/raw/`、`reports/`、`tests/` 均已存在。
- E0-Full D0 数据链验收十门 PASS；E1/E3/R1/P1/P2/P2.1/E7-FAST 与 CORE-SEARCH 多轮报告已归档。当前 **A 轨**状态以 CORE-SEARCH 决策链为权威：**core-patent status = NO-GO** —— 在 A 轨**真实部署/效果证据口径**下，当前仍无成熟 GO 核心专利；与此同时，PD 发明设计轨已形成 **A、C 两件第 1 波核心专利候选**（详见下文「PD 轨状态同步（2026-09-08 → 09-10）」），**该定位不改变 core-patent = NO-GO 与 Round 5 = NOT STARTED**。两者是不同轨道的两套口径，不可互相推导。E7-FAST/M2 只作为已验证车辆侧模块（VALID MODULE）和窄防御性候选包 HOLD：D2 EV 层 M2 双重上调限制有效，但不足以支撑系统级核心专利 GO。`patent_preexperiment/reports/patent_definition/01_claim_tree_v3_e7_fast.md`、`02_prior_art_element_map_v3_e7_fast.md`、`03_tech_disclosure_e7_fast_v3.md` 是 E7-FAST 阶段历史包，不再是当前核心专利权威。
- D3 recovery 已由 P2.1A formal FAIL 移除；D3/BESS/PCC 系统效果经 corrective audit 后 train+val FAIL、test CONDITIONAL，只能作弱从属/背景，不得引用旧 D3 系统收益数字。
- CORE-SEARCH 最新状态：Round 4 Decision #07 已关闭。R4-A BESS tracking/capability = **STOP**（A1S-2：S1 时区归一伪强；S0 preferred 但 paper power RMSE/MAD 未能 ±15% 复现；`09419f3` STRONG 永久 suspended；A1b/system layer BLOCKED）；R4-C EVSE availability = **CLOSED**（事件存在但 operational magnitude 不足，不进 R4-C1，不做子集/极端事件救援）；R4-B transformer thermal = **DEFER / real thermal telemetry only**；R4-D PV/PCS availability = **NOT STARTED / adequate real state data required**。Round 1-4 retrospective 已冻结 Round 5 七条启动条件；R5-P0/P0b pre-launch data scouting 对 P1 transformer / P2 PV-PCS / P3 DC charger module / P4 BESS rack-PCS 初筛和 targeted search 后，0 个 family 满足 7/7。R5 data acquisition spec 已冻结 P2/P1 最小字段合同与 intake gate；当前仍是 **core-patent status = NO-GO / 不启动 Round 5**。
- 2026-09-06 专利目标已冻结：`patent_preexperiment/reports/patent_definition/04_专利目标冻结_多设备动态可用能力边界与协同功率控制.md` —— 发明对象 = 设备动态可用能力边界 → 站级耦合可行域 → 跨设备功率重分配 → 执行反馈修正边界的闭环；P1/P2/P4/充电设备（M2）为其物理锚点，**锚点化不改变各锚点证据状态**（D3 禁令、M2 HOLD、NO-GO 均不变）。
- **PD 轨（发明设计，2026-09-06 增设；2026-09-07 方法论转变修订见 `patent_definition/13_治理修订二_专利探索方法论转变与多候选并行.md`）**：`patent_definition/06_治理修订_…` 冻结纠偏——"有真实数据证明"≠"能否设计核心专利"；R5 7/7 重定义角色为**真实部署问题与效果证据升级门**（标准与 NOT STARTED 状态不变），不再是发明设计启动门。**13 号方法论转变松绑 PD 轨**：(a) 从单链扩成多候选并行——专利候选池 A–H（注册表 `reports/patent_pool/00_专利候选池注册表_A-H.md`），当前五步链 = 候选 A，不再独占；(b) 解除"产出仅限文档/禁代码/controller/收益量化结论"绝对限制，允许 cheap-knockout 对"可验证部分"用公开数据/benchmark/仿真做量化推演、允许机制验证用小原型代码；**保留** v1 教训红线"禁止无验证证据时用合成数据/纯设计文档自证收益"，效果级结论仍须 A 轨 R5 7/7；(c) 已有相近专利≠禁区，同热点下换"对象/状态变量/触发条件/连接关系/执行方式"即成另一机制；(d) 评审用五问（①真实矛盾 ②设备/数据/状态/动作 ③可实施机制 ④手头能验证哪部分 ⑤现有技术接哪），问"能验证哪一部分"而非"能否证明整个发明"。升级链 = 机制拆解 → PO-SEARCH-1 强制深查 →（达标才可）权利要求草案 → 证据升级仍须 R5 7/7。核心机制拆解见 `patent_definition/07_核心发明机制拆解_…`：发明核心收窄为"执行偏差确认的动态能力边界修正 + 跨设备定向转移"（M1 检测→M2 分类→M3 边界收缩→M4 缺口→M5 定向转移→M6 确认/恢复闭环），M3–M6 标注 UNVALIDATED；设计约束：**不得仅以 SOC/近期执行偏差的简单经验函数作为能力边界收缩的核心判定依据**（RD-2 硬门证据，限其数据/协议口径，非普适禁令）；数据问句改为"能验证 M1–M6 哪个环节"。数据对 PD 的分环节映射：M1←M5BAT 残差分布；M2←M5BAT 描述性 + OpenCEM（告警印证分支因寄存器语义未解码 BLOCKED）；M3–M6 无数据，纯设计。
- 治理三轨（同见 04 文件 §7 + 06/13 号治理修订）：**A 轨** = 核心专利证据轨，R5 7/7 唯一准入，Round 5 NOT STARTED（不变）；**B 轨** = 机制发现轨，独立编号 RD-*（不挂 R5），允许真实公开数据/benchmark/标注仿真，只产出机制发现与方向淘汰，禁闭环收益结论；**PD 轨** = 发明设计轨（06 号增设、13 号方法论转变修订），多候选并行 A–H、允许 cheap-knockout 量化推演与小原型、保留 v1 自证收益红线（详见 13 号）。**A 轨 R5 7/7、core-patent = NO-GO、Round 5 NOT STARTED 均不变**。**RD-1 = STOP AT A1（2026-09-06 终判）**：站级一致性硬门 FAIL——站级测量含稳定辅电/损耗与瞬态项、schedule 站级列是净交换量，原 station↔unit 归因链不成立（A0 语义冻结 `configs/research_discovery/rd1_a0.yaml` 继续有效；终判见 `reports/research_discovery/RD-1_A0A1_…§8`）。继任 **RD-2**（单元级执行偏差与状态相关性）已预注册并执行完毕：**硬门 FAIL → STOP（2026-09-06）**——C vs B3 改善 +0.214 kW 但 block-bootstrap 95%CI [-0.374,+0.455] 含 0，且 B3 劣于 B0（SOC 条件化无结构）；单元执行偏差存在（MAE 12.8–22.8 kW ≈ 额定 2–3.6%，对称散布）但不可由 SOC/recent-response 解释。**RD-1+RD-2 双 STOP，M5BAT 线对 E4 素材贡献穷尽**；B 轨当前无存活任务，新 RD 任务须绑定新数据源重新预注册。PO-SEARCH-1 = SURVIVE WITH CONDITIONS（`patent_definition/05_…`）：A 层单要素全 crowded、C 层未见整体闭环披露，空白点收窄至 E4 连接（执行确认的能力边界）；E4 证据只能来自具备"站级触发+设备边界+执行反馈"的新真实数据源；深查清单（CN 专利空间、US20160336765A1 claims、Applied Energy 执行偏差论文、OFO 约束学习支线 + 用户指定 5 新焦点）已在 `patent_definition/08_PO-SEARCH-1_强制深查结果.md` 执行完毕：判定 **PASS WITH CONDITIONS**（2026-09-06 纠错后口径）——强威胁分别触及能力边界/反馈/降额恢复/约束学习等邻域（部分对象触及多个 M 环），但公开时间线未观察到单篇完整连接"M2 偏差成因分类→M3 方向化可信边界状态机→M5 异构等效余量映射→M6 执行确认式维持/恢复"区别链（最强威胁 CN122203352A 仅片段级）；条件 1 **已解除（2026-09-07）**：用户提供 CNIPA 公布文本 PDF（SHA256 `bc07a75e…43a5cfe`），CN122203352A 权利要求 10 条全文复核 = **非 knockout**——其全链为单台 BESS+PCS 构网控制、P_cap=P_rated·k_SOC·k_SOH·k_T 标量状态因子降额，无计划-执行偏差、无成因分类、无跨设备转移；定位为**第一最近现有技术**进入背景技术引用（复核见 `patent_definition/10_CN122203352A权利要求级复核_条件1解除.md`，三重区别：触发源/边界语义/闭环范围）；条件 2 = 独立权项必须锚定组合链，不得以"动态能力边界"单点为主体。prior-art 检索面收口，不再扩大。**Claim Draft v1 已开（2026-09-07，`patent_definition/11_权利要求语言草案v1_…`）**：方法独立权 = 权 1 六段式（E1–E7；末段 E7→E4 回环"维持、继续修正或恢复可信能力边界"为必要句，防退化为 corrective dispatch）；从属顺序 D1→D2→D3→D7→D6→D4→D5→D8 = 权 2–9（先核心状态机后工程实现）；系统独立权 = 权 10 六单元镜像；10 号报告口径已修订（说明书=定向抽查非全文审计；反向比对仅用于现有技术区分、非侵权/FTO 结论）。**工程现实性反审（2026-09-07，`patent_definition/12_工程现实性反审_…`）：v1 独立权判定过窄（7 项，风险中等），不推倒重来、抽象一级**——发明本体收敛为五步链"偏差证据→能力归因→方向化可用能力状态→跨资源承接→执行反馈回写"（核心 A–D）；三分类标签/双迟滞/双向独立置信度/确定性排序/PCC 二级确认/分级恢复/设备类别表/至少两种类型/站级计划降级全部降为从属（v1 细节转为答审退守位）；"异构"改功能异构定义；已对 08 冻结证据集做解析性重比对（五对象均不覆盖五步链，总判定不变），未新开检索、不触发重开条款。v2 全量语言待 12 §4 评审后展开，说明书骨架顺延 13 号。core-patent status = NO-GO 不变。
- **相关文献台账（2026-09-07，`reports/literature/01_相关文献台账_108篇处理留痕与五步链威胁初判.md`）**：用户提供文献库（顶层光储充 42 / 可信 8 / 大模型 58，共 108 篇 PDF）已按"文本层三诊 → MarkItDown 全文转换（42 篇）→ 扉页 OCR（65 篇 CNIPA 专利）/1 篇损坏待人工"完成整理与结构化初判，SHA256 全量留痕于 `literature/manifests/`（台账主表 `literature_ledger.csv`，产物在 `literature/converted|converted_ocr/`，工具脚本 `literature/tools/`）。结论（证据等级已钉牢，2026-09-07 修订）：**在"41 篇唯一全文 + 65 篇专利扉页/摘要初判"的证据层级下，未观察到已确认披露五步链连续两环（S1+S3 或 S3+S4）的文献；65 篇图像件仅完成扉页级低置信度筛查，不能据此排除其全文存在更深层组合机制——"未观察到"不升级为"108 篇全文均不存在"**。与 PO-SEARCH-1 收口一致；10 篇片段级；4 篇待全文核实。本次整理的价值定位是三件可靠结论：S3 动态能力/可用容量单点拥挤、S4 缺口驱动跨资源补偿常见、区别必须压在"执行偏差→能力归因→方向化能力状态更新→跨资源承接→执行反馈回写"五步链（与 12 号一致）。台账 CSV 有"证据层级"列（全文级/扉页级/损坏），扉页级"无覆盖"不得解读为全文排除。该整理不构成新检索行为、不改变既有判定；"可信"一词多义（TEE/数据空间/容量置信度/智能体权限），说明书须将"可信能力边界"限定于设备功率语境。**CN122371331A 已完成权利要求级全文复核（2026-09-07，`reports/literature/04_…`，全文 OCR 底稿 `literature/converted_ocr/顶层/…fulltext.md`）：非 knockout，定级片段级(偏强)、108 篇最近邻，列第二最近现有技术（与 CN122203352A 双锚互补）**——其 S1 偏差证据覆盖（未执行电量/储能偏差量）、储能偏差修正下时段储能电量（S3 弱触及）、缺口由储能按 SOC 边界承接（S4 部分同构）、执行结果回写下一时段计划输入（S5 计划滚动形态），但无成因分类、无方向化可信边界状态机、无异构等效余量映射、无边界维持/恢复，五步链条不闭合；四条区别性撰写指引见 04 号 §5（E1 偏差须成因可区分、E4/E5 须边界状态方向化更新、E5/E6 须等效余量映射、E7→E4 回环动作者须是边界确认/恢复而非任务量顺延）。

## PD 轨状态同步（2026-09-08 → 09-10）｜权威状态索引

> **本节定位**：只做**状态索引与文件索引**，不重复研究报告内容（原文仍在各产物文件中）。本次仅同步 Sep 8–10 的 PD 状态，**不改变任何实验门、不改变任何权利要求、不改变 A 轨任何判定**。

### 两条状态并排（务必勿混）

```text
【正式证据状态】（A 轨口径，未变）
core-patent = NO-GO
Round 5     = NOT STARTED
A-M3–M6     = UNVALIDATED

【PD 专利组合状态】（发明设计轨口径，2026-09-10）
A = 第 1 波核心专利候选
C = 第 1 波核心专利候选
B = 第 2 波独立改进专利
F = 第 3 波条件触发防御/配套专利
```

**读法**：PD 组合状态描述的是**发明设计成熟度与申请波次**，**不是**真实部署/效果证据等级。看到 A/C 为"核心专利候选"**不等于** R5 已通过；看到 NO-GO 也**不等于** A/C 不能继续设计。

### 1. 候选收敛状态

A/C/B/F 四条已收敛为当前组合；**D/E = HOLD**、**H = HOLD（防御/配套，待查重）**、**G = 研究储备**（数据弱，暂不闭环验证）。**不再广开新候选**；确需新增用下一可用字母并同步注册表 `reports/patent_pool/00_专利候选池注册表_A-H.md`。

### 2. B/C/F 最新结论（2026-09-08/09）

- **B = PASS**，核心创新点 = **B2 持续时长-能量耦合 + B5 承诺后剩余包络**（全库空白）；最强近邻仅覆盖 2 环。
- **C = PASS**；**OpenCEM cheap validation = PASS（强）**——4 个资格状态自然出现、双向降级与恢复可观测、资源集合成员变化非平凡。注意：该验证为**机制级**证据，非效果级。
- **F = PASS，但核心收窄至 F4→F5→F6**；F1/F2 已 crowded；存在组合攻击面（lit104 提供 F2→F3，lit75/lit71 提供 F4/F5 强 Neighbor）。

### 3. A/B/C/F 边界冻结（状态对象级）

| 候选 | 保护的状态对象 |
|---|---|
| A | `directional_capability_state`（方向化可用能力状态） |
| B | `station_flexibility_envelope`（站级时变灵活性包络） |
| C | `control_qualification`（控制参与资格） |
| F | `physical_verdict` + `authorization_state` + `execution_state`（三层安全状态链） |

**两处最易互吞的边界 —— 必须按「更新对象」区分，不得按数据类型（连续/离散）区分**：

- **C 的 `control_qualification` vs F5 的 `authorization_state`**：C 是**设备持久属性**（这台设备当前能不能被控制），F5 是**动作瞬时判定**（这次动作能不能执行）。F5 独立权必须包含 C 资格之外的**独立判定维度**（风险等级、动作类型、操作者/Agent 权限），否则退化为 C 的 pass-through、F 的创造性被 C 吞噬。
- **F6 的 `execution_state` vs A 的 M6**：F6 更新**本次控制事务/动作状态**（AUTHORIZED → SENT → ACKED/FAILED/UNCERTAIN → ROLLBACK/DEGRADED/HUMAN），A-M6 更新**设备持续能力知识**（capability_state → maintain/shrink/recover）。冻结边界：**F6 不更新设备未来可用能力；A-M6 不负责本次控制事务的撤销与安全退出**。

### 4. 第一波状态（A + C）

**C 侧 —— 全部已关闭/就绪**：

```text
C Claim Draft v1.2          = PASS（权 1 / 权 10 / 从属梯 D1–D8 全 PASS）
lit45 逐限定项反打           = PASS WITH CONDITIONS
C Claim 阶段                = CLOSED
C 说明书骨架 V1             = PASS WITH DRAFTING GUARDS（已执行完毕）
C 说明书全文 V1             = 已出（§1–§15 + 附录 A 内部证据档）
```

**A 侧**：独立权 v2 五段已就绪（`patent_definition/12_工程现实性反审_…` §4），**仍等 12 §4 用户评审收口**，尚未展开 A 说明书骨架。

### 5. A+C 协调规则（2026-09-10 冻结）

- 两案说明书**各自 self-contained**；同日/近同时窗协调提交；**不以另一申请作为支持来源**（不做 incorporation by reference，不写"参见另一申请"）。
- **必要技术特征隔离**：A 独立实施例**不要求** C 存在；C 独立实施例**不要求** A 存在。最强单条检验 = "**删除对方全部内容后，本案说明书仍可完整实施**"。
- **共享基础设施**（设备通信接口、遥测与时戳对齐、数据质量检查、EMS/边缘控制器、设备类型清单）**不作为任一案的主要创造性贡献**，也不构成核心机制的必要限定；不得进入任一案独立权。
- **可选组合实施例可有**，但必须：以"可选地/在另一实施例中"引入、**不进独立权**、不写成互为必要特征、**不用于独立性论证**。
- **数据披露两层制**：正式申请文本不披露数据集名/字段名/统计值（如 OpenCEM、`outstatus`、`sysalarmflag`）；这些只进**内部证据档**（如 C 说明书全文脚注的附录 A）。
- **法律隔离基础 = 被更新的技术对象**，**不是**"连续 vs 离散"这类数据类型——后者任一方在答审中调整表达形式就会自我动摇。

完整条款（含 8 维必要技术特征隔离表、三层材料划分、9 项独立性检查表、"通信/资源/运行"三个边界易混词）见 `reports/patent_pool/A+C_第1波说明书并排协调_V1.md`。

### 6. 下一步（PD 轨）

**A 说明书骨架 → A+C 第二轮并排校验**（各案全文就绪后互相校验术语与污染）。

**不要把 B/F 提前拉进第一波全文起草** —— B 为第 2 波、F 为第 3 波条件触发（F 的触发条件 = 新公开专利 ≥3 篇触及 F4/F5/F6）。

### 优先读取清单（PD 轨，按序）

```text
reports/patent_pool/A-B-C-F_横向组合与专利组合架构评审_V1.md      # 组合总架构与定位
reports/patent_pool/C_独立权架构反审_V1.md                        # C 机制冻结基线（内部版本 V2）
reports/patent_pool/C_控制资格状态机_Claim_Draft_v1.2.md          # C 权利要求权威稿
reports/patent_pool/C_Claim_v1_lit45_逐限定项反打.md              # C 主引证压力测试
reports/patent_pool/A+C_第1波说明书并排协调_V1.md                 # 跨案隔离与协调规则
reports/patent_pool/C_控制资格状态机_说明书全文_V1.md             # C 说明书全文（附录 A 为内部证据档，不进正式文本）
```

### PD 轨治理纪律（稳定条款）

- **版本规则**：改动**权利要求语言** → **新建版本文件** + 旧版加 superseded 页眉保留；仅改措辞/状态登记/open items → **就地修订**，不新建文件。判据 = 问"权项正文有没有被动"。
- **改版后必做**：diff 独立权文本，确认**字节级未变**；若未变，则既有的 prior-art 压力测试结论**继续有效、不重跑**，并在新版文件中写明该不变量。
- **红线**：禁收益量化；数据集名/字段名/统计值只进实施例不进权利要求；权项不写死枚举名（用"至少 N 个等级"上位表述）；内部文献台账编号（lit_id）与内部策略语言不得进入正式申请文本；证据只作 enablement。
- **回写要求**：PD 轨每完成一个阶段，**同步回写本节**，避免下次会话上下文断层。

## 环境与工具链

- 仓库根有 `venv/`（Python 3.12.7），当前工程配置在 `patent_preexperiment/pyproject.toml`：Python ≥3.11、src 布局、pytest（testpaths=tests, pythonpath=src）、ruff（line-length=100, select E/F/I/UP/B）、mypy strict；依赖 pandas/pyarrow/PyYAML/matplotlib，dev 依赖含 pytest/ruff/mypy。
- 常规验证在 `patent_preexperiment/` 下运行：`..\venv\Scripts\python.exe -m pytest` 与 `..\venv\Scripts\ruff.exe check`。CI 应同时执行 pytest 与 ruff，避免测试绿但质量门不绿。
- acn_project 的构建脚本（`ACN-data/*.py`）依赖 `ACN-data\.venv` 里的 pandas/pyarrow/acnportal，复现基准时用那个环境。

## 文档命名约定（2026-09-06 起）

- 新增报告/文档一律用中文文件名，保留 CORE-SEARCH、R5-P2 等编号与判定锚点（如 `CORE-SEARCH_R5_P2_OpenCEM数据准入前审计_REJECT判定.md`）；正文优先中文，注意可读性。已有英文命名的历史文件不回溯改名。
