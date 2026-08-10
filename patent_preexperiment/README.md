# patent-preexperiment：光储充专利预实验工程（R1 收敛审计完成 → Patent Definition 阶段）

> 本 README 的作用不是介绍代码，而是防止项目被误解为普通充电负荷预测、多车调度优化、
> 用户行为预测或通用光储充仿真平台。读任何代码、改任何配置、汇报任何结论之前，请先读本节。

## 1. 项目要解决的真实问题

工商业园区光储充系统中，充电桩向车辆下发 **pilot（导引/允许电流）**，但车辆实际执行功率
存在持续的、系统性的响应差异：同一时段内，桩侧可提供功率与车辆实际吸收功率不一致。
**EMS 给车辆安排了多少功率，不代表车辆下一刻真的能按这个功率执行**；若账面上按 7 kW
安排而车辆实际只有 4 kW，计划与实际的 3 kW 差值会迫使储能/电网/下一周期 EMS 补偿。
本项目的发明不是回答"剩下 3 kW 应该给谁"，而是回答更底层的问题：**在当前数据条件下，
有没有资格继续把这辆车当作 7 kW 的可执行负荷？** 若响应证据不足，就不盲信。

最终发明中心（Review 52 Final R1 Patent Gate）：

> 利用 EVSE/CSMS 在线实际响应形成**响应证据支持状态**；据当前可用信息条件选择
> **短时功率边界生成模式**（pilot-rich → response/history-derived boundary；
> current-only → history protective boundary；history insufficient → conservative
> fallback）；据所选边界**限制/降级/恢复 EMS 对该 EV/EV 池功率预算的控制权限**
> （不无条件按"分配功率−实际功率"释放差值）；以新的实际响应反馈更新支持状态，
> 实现保护降级与响应恢复的技术闭环。

## 2. 当前专利主轴（V2.1 → Review 52 收缩后）

原主轴 V2.1"充电响应状态识别 → 短时可执行功率区间 → 支持域内有界修正 → 支持域外保护回退"中，
**active bounded correction 降为从属/可选实施方式**；broad active D1-R/D1-A 不恢复；
不自动进入 E2/E4。D1 收缩为 **protective-only**：判断何时不能再信任原功率能力假设，
并切换到更保守的边界。术语纪律（AGENTS.md，违规即退回）：

- pilot 与 actual 的差异只能称"导引/允许电流与实际响应差异"，**不得**称"命令失败/拒绝"；
- 只用自然 pilot 正阶跃验证过增量响应的，才谈"可吸收余量"；
- 只用观察值称"预算差值"而非"可回收能力"；
- 未通过 E4.1 验证的响应仿真器不得输出闭环收益结论。

## 3. 已经证明与尚未证明（截至 Final R1 Patent Gate）

### 已证明（冻结样本、冻结阈值、负对照下）

| 结论 | 证据 | 位置 |
|---|---|---|
| ACN caltech 核心运行段存在持续响应差异，事件会话率 11.9%（停止线 5%） | E1-Lite（K1.2 阶段切断） | `reports/E1_Lite_gate.md` |
| 中位功率差 1.28 kW（工作功率 36.7%），6 个冻结月份逐月 ≥5% | 同上 | 同上 |
| 负对照成立：时间置换 7.2% ≪ 11.9%，最终冻结 bootstrap 95%CI [3.5, 5.8]pp（母体=2,941 会话） | K1.2.2 母体过滤 | `reports/K1_gate.md` |
| 最强简单基线 A2（上一周期实际功率）缓解但不消除：caltech 候选率 21.3%[日等权 CI 20.3–23.5]，消除 55.2%（≤80%） | E3-Lite | `reports/E3_Lite_gate.md` |
| 两证据池日候选能量独立过 0.5% 线（caltech 4.2% / jpl current-only 3.9%） | 同上 | 同上 |
| **Caltech E1-Full / E3-Full formal test FAIL**：E1 11 事件 100% 单月（2020-06）10/11 单桩；E3 test 候选率 CI 下界 ≈0.0052、日候选能量中位 0、A2 消除 77%、机会 79.5% 集中于 2020-11 | R1 E1/E3 gate | `reports/R1_E1_gate.md`、`reports/R1_E3_gate.md` |
| Caltech test 层 E1 response evidence 与 E3 A2 opportunity 在 cycle 层 `S1∩S2=0`；A1 漏斗 10,528 → 155（retention 1.47%，strict-match 选择效应） | R1 扩展审计 A1/A4 | `reports/R1_expansion_audit.md#A1`、`#A4` |
| **A5：近期 actual 波动（recent_var）越高 → E1 响应证据密度越高，train/val/test 方向一致**（Q1→Q4 单调 0.0039→0.0261 / 0.0054→0.0331；test Q3,Q4>pooled） | A5 扩展审计（Batch_3 正式运行，baseline `34f04f6`） | `reports/R1_expansion_audit.md#A5` |
| **Final R1 Gate：D1=B protective-only、D2/D3 fusion=YES、Project=PROTECTIVE GO** | 审查结论52 | `reports/R1_expansion_audit.md#最终判定` |

门判定：**Final R1 Patent Gate = PROTECTIVE GO + D2/D3 融合架构；阶段切换 Patent Definition。**
此前 K1 条件 Go、R1 K1 硬切分复现、扩展审计 A1–A5 均已完成并落账。

### 尚未证明（全部为 D 级假设，禁止对外断言）

- 差值可被其他车辆吸收；
- 短时可执行功率区间可生成且有效；
- 支持域内有界修正（active correction）在主测试域普遍有足够价值；
- 控制权限切换机制能产生闭环/经济收益；
- 可减少储能补偿；
- 可提高光伏消纳；
- 任何闭环收益 / 站级经济效益 / 全车型普遍适用。

以上全部挂账在 `data_registry/claim_evidence_registry.csv`（含 A5 后升级的 C-007 与
Patent Definition 阶段新增 P-001～P-004），汇报时引用 `claim_id` 并遵守
`allowed_wording` / `forbidden_wording`。

## 4. E0-Full 批准范围（冻结）

**包含**：数据注册、完整性/质量校验、硬时间切分（站点内 60/20/20）、标准化数据集构建、
K1 指标复现。

**禁止提前开展**：主动增配模型、可吸收余量估计、复杂时序模型、多车优化调度、闭环收益
仿真、储能/光伏/PCC 效果结论。

## 5. 数据位置与环境配置

- 数据在仓库外，`data_root` 由 `configs/paths.yaml` 配置；仓库不保存原始数据，也不提交
  机器相关绝对路径。本机真实路径只保留在 `configs/paths.yaml`（该文件不入库，模板见
  `configs/paths.example.yaml`）。代码统一经 `io/paths.py` 读取，禁止硬编码。
- 主数据集 `ACN-data/acn_project/` 已构建：静态索引 85,877 / API 索引 51,234 / 映射 96,467
  （matched 40,644 / static_only 45,233 / api_only 10,590）；gold 基准 115 桩；
  原始时序 `ACN-data/ACN-Data-Static/`；API 会话元数据 `acn_full/`。
- 运行时环境：仓库根 `venv/`（Python 3.12.7）。验证命令（在 `patent_preexperiment/`
  下执行）：
  ```text
  ..\venv\Scripts\python.exe -m pytest
  ..\venv\Scripts\ruff.exe check
  ```
- 依赖：`pyproject.toml`（pandas/pyarrow/PyYAML；dev 含 pytest/ruff/mypy）。

## 6. E0-Full 运行入口

```text
S0 阶段启动冻结（本提交：README、e0_full.yaml、证据台账、schema、测试框架）
→ E0F-01 输入与证据注册
→ E0F-02 时间切分冻结（e0_full_split_registry.parquet）
→ E0F-03 会话分钟数据集构建（datasets/session_response_1min，分区）
→ E0F-04 控制池数据集构建（datasets/pool_state_1min|5min）
→ D0 数据工程验收门
→ R1 K1 硬切分复现门
→ 通过后才启动 E1-Full + E2
```

唯一权威执行协议：`docs/工商业园区光储充_专利方向确定详细预实验计划书_V2.0.md`
（实验编号 E0–E8、阈值网格、Go/条件 Go/No-Go 门全部在其中）与
`docs/光储充专利预实验工程总体落地方案_V2.1.md`（工程化细节，不改变实验编号与门标准）。
所有预注册规则以 `configs/e0_full.yaml` 为冻结事实，代码不得散落绝对路径、月份选择或
统计阈值。

## 7. 结果目录与复现方法

```text
data_registry/   K0 基线、E0-Full baseline、split registry、claim 证据台账
datasets/        分区标准化数据集（git 忽略，可从原始数据重建）
results/raw/     实验原始产物（E1L/E3L/K0/P0…）
results/logs/    每次运行日志（含运行时间戳）
reports/         各门报告（K1_gate.md、E0_Full_*_audit.md…）
review/          每轮审查结论归档（审查结论2..7）
```

复现原则：同配置重复运行产物一致（确定性）；测试集只运行一次正式结果；任何新方案必须
新配置版本 + 新测试协议，禁止在测试集上逐图调参。

## 8. 失败时的停止规则

- **D0 失败**：暂停所有模型，修复数据契约/切分/质量，不运行正式 test，不改变问题定义；
- **K1 指标 train 成立、test 不成立**：不改阈值、不换月份、不删不利池、不加复杂模型，
  召开新门评审，可能结论为收缩场景 / 降级为站点或 field mode 方向 / 保护型上界 / No-Go；
- **A2 已消除 >80% 候选**：停止复杂区间模型，只评估简单状态机组合是否仍有专利空间；
- **E1 复现通过但跨站证据弱**：保留 caltech 主场景，JPL 仅作边界，权利要求限制适用条件。

## 9. 当前工程治理状态

- **审查结论52 Final R1 Patent Gate（最新）**：D1=B protective-only、D2/D3 fusion=YES、
  Project Final Verdict = **PROTECTIVE GO + D2/D3 融合架构**；不恢复 broad active
  D1-R/D1-A；不自动进入 E2/E4；R1 预实验方向探索阶段正式关闭，切换 **Patent Definition**。
- 审查结论33/34 准入 R1 扩展审计（§10.2）；结论45/46 A5 protocol v1.2 FINAL FREEZE
  （`9302a7d`）；结论47–51 A5 generator X1→X3.1 code-only 修正与正式运行授权
  （baseline `34f04f6`，Evidence commit `a827df3`）。
- K1.2.2 审查通过（`review/审查结论5.md`），E0-Full 数据构建批准（限定范围）。
- 审查结论7：先完成 E0-Full 阶段启动冻结（证据台账、预注册配置、数据契约、split 规则和
  停止线），冻结审查通过后再进行全量数据构建；全量复现通过后才启动 E1-Full 和 E2。
  该口令已完成其历史使命（E0-Full 已全部完成）。

## 10. 下一阶段：Patent Definition（Review 52）

1. 更新过时的 claim_evidence_registry 与 README 状态（`f6b49e8` 完成）。
2. 主发明技术交底骨架 + 独立/从属权利要求树 + 现有技术检索矩阵
   → `reports/patent_definition/tech_disclosure.md` + `claim_tree.md` + `prior_art_matrix.md`。
3. 现有技术检索仅为技术筛选，非正式新颖性/创造性/FTO 法律意见；最终申请前需专利代理师
   做完整法律检索与权利要求判断。

现有技术边界（Review 52 补检索）：Porsche US12054065B2（故障→fallback 切换，trigger 非
车辆响应证据）、ChargePoint US10464435B2（近期供电历史响应 power-limit）、US10150380B2
（allocated 超能力→释放模块给其他 dispenser）、CN112829627A（多车动态重分配）、
US9290104B2（pilot 改变前后测量响应）。历史边界、差值回收、多车重分配、fallback mode、
pilot 响应测量均不能单独成主权利要求；可主张空间是它们的**新技术关系组合**。
