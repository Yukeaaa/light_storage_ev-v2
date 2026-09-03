# patent-preexperiment：光储充专利预实验工程（CORE NO-GO / MODULE HOLD）

> 本 README 的作用不是介绍代码，而是防止项目被误解为普通充电负荷预测、多车调度优化、
> 用户行为预测或通用光储充仿真平台。读任何代码、改任何配置、汇报任何结论之前，请先读本节。
> **当前权威**：`core_search/CORE_SEARCH_MASTER_PLAN.md` + `reports/core_search/CORE_SEARCH_DECISION_05_ROUND3_CLOSE.md`
> + `core_search/CORE_SEARCH_ROUND4_CANDIDATES.md`。当前结论是 **core-patent status = NO-GO**：
> 暂无成熟 GO 核心专利。Round 4 Decision #06 已完成，R4-C0 STOP 并正式关闭；R4-A0b
> 已用 RWTH Aachen 官方 M5BAT 数据集消除 DATA_PENDING，判定 **DATA_SOURCE_RESOLVED / LEVEL B**。
> R4-A1 A1-0/A1a 已跑，但 A1S/A1S-2 纠错审计已关闭该线：S1 supplementary UTC+1/UTC+2
> 归一产生伪强 tracking 信号；S0 raw-label 只能作为 preferred pairing，未通过论文 power
> RMSE/MAD exact reproduction。`09419f3` 的 A1a STRONG_A1B 判定已 **SUSPENDED**；最终
> **DATA_SEMANTICS_OR_METRIC_UNRESOLVED / R4-A STOP**。Decision #07 已正式关闭 Round 4：
> R4-C CLOSED，R4-B DEFER，R4-D NOT STARTED，A1b/system layer **BLOCKED**，不启动 Round 5。
> E7-FAST/M2 仅保留为 **VALID MODULE / narrow defensive package HOLD**：D2 EV 层 M2 双重上调限制有效，
> 但不足以支撑系统级核心专利 GO；D3/BESS/PCC 系统效果经 corrective audit 后 train+val FAIL、test
> CONDITIONAL，只能作弱从属/背景。
> **E7-FAST v3 历史包**：`reports/patent_definition/01_claim_tree_v3_e7_fast.md`、
> `02_prior_art_element_map_v3_e7_fast.md`、`03_tech_disclosure_e7_fast_v3.md` = HISTORICAL/HOLD，
> 不再作为当前核心专利权威。
> **v2 历史**：`claim_tree.md` / `prior_art_matrix.md` / `tech_disclosure.md` = HISTORICAL
> （D3 recovery 已被 P2.1A FAIL 删除，不再权威）。

## 1. 项目要解决的真实问题

工商业园区光储充系统中，充电桩向车辆下发 **pilot（导引/允许电流）**，但车辆实际执行功率
存在持续的、系统性的响应差异：同一时段内，桩侧可提供功率与车辆实际吸收功率不一致。
**EMS 给车辆安排了多少功率，不代表车辆下一刻真的能按这个功率执行**；若账面上按 7 kW
安排而车辆实际只有 4 kW，计划与实际的 3 kW 差值会迫使储能/电网/下一周期 EMS 补偿。
本项目的发明不是回答"剩下 3 kW 应该给谁"，而是回答更底层的问题：**在当前数据条件下，
有没有资格继续把这辆车当作 7 kW 的可执行负荷？** 若响应证据不足，就不盲信。

E7-FAST/M2 历史候选包的发明中心（**VALID MODULE / HOLD，不是当前核心专利 GO**）：

> EMS/园区控制器提出 EV 群功率上调请求后，对每辆正在充电的 EV，根据当前可获得的桩侧允许
> 信息、实际功率与历史实际响应，计算本周期允许增加量；具备 pilot+actual+history 的 M2 车辆
> 使用 `min(当前桩侧允许值, 历史实际响应支持水平)` 形成双重上限；缺少当前桩侧允许信息或历史
> 不足的车辆采用保护性/锁定处理；EV 群实际接受量再受园区请求限幅。

> **证据边界**：M2 双重约束在真实 EV 数据上降低未经支持的上调高估；不得称“准确识别车辆能力”。
> D3 recovery 已移除；BESS/PCC 系统层效果弱，不作为 Claim 1 必要技术效果。

## 2. 当前专利主轴（CORE-SEARCH：系统级核心专利重筛）

原主轴 V2.1"充电响应状态识别 → 短时可执行功率区间 → 支持域内有界修正 → 支持域外保护回退"中，
**active bounded correction 降为从属/可选实施方式**（P-004 维持 D）；broad active D1-R/D1-A
不恢复。**P1 formal No-Go** 已把 recent_var / variance 状态判定移出核心；**P2.1A formal FAIL**
已删除 D3 recovery；**E7-FAST/M2** 只保留为车辆侧已验证模块和窄防御性候选包 HOLD。
当前核心工作线是 CORE-SEARCH：Round 1-3 已关闭/停止既有统计控制路线；Round 4 双线数据门后
未选出可进入系统层的主线。
术语纪律（AGENTS.md，违规即退回）：

- pilot 与 actual 的差异只能称"导引/允许电流与实际响应差异"，**不得**称"命令失败/拒绝"；
- 只用自然 pilot 正阶跃验证过增量响应的，才谈"可吸收余量"；
- 只用观察值称"预算差值"而非"可回收能力"；
- 未通过 E4.1 验证的响应仿真器不得输出闭环收益结论。

## 3. 已经证明与尚未证明（截至 CORE-SEARCH Round 4）

> **阶段线**：Final R1 Patent Gate（PROTECTIVE GO）→ **P1 formal No-Go**（recent_var
> 状态判定移出核心）→ Patent Gate 2（NARROW CONDITIONAL GO）→ **P2 formal
> SUCCESS / NARROW GO**（设备动作链机制成立）→ **P2.1A D3 falsification FAIL**
> → **E7-FAST D0/D2 GO，D3 train+val FAIL / test CONDITIONAL** → **CORE-SEARCH Round 1-3
> 关闭，core-patent status = NO-GO** → Round 4 data-first physical mechanism search。

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
| **P1 formal No-Go**：recent_var 状态判定作为核心规则 external formal FAIL（215 会话/15,954 cycle，主效应方向反）；variance-defined S1/S2/S3 移出核心 | P1 formal | `results/raw/phase3_p1/P1_patent_gate.md` |
| **Patent Gate 2 = NARROW CONDITIONAL GO**：A/B/C/D 单模块全高拥挤，闭环未公开；主风险 ACN 族 | 检索后冻结 | `results/raw/patent_gate2/patent_gate2_final.md` |
| **P2 formal = SUCCESS / NARROW GO**：D1/D2/D3 设备动作链机制成立（M1=1.0 / M2=1.0 / M4=0.0；M3 natural JPL 1,060 traces / 1,060 sessions；n_diff_prot_normal=72,067） | P2 formal frozen outcome | `results/raw/phase3_p2/P2_patent_gate.md` |
| **P2.1A = formal FAIL**：D3 recovery 作为独立机制删除，不作为权利要求或从属主张 | P2.1A falsification | `results/raw/phase3_p2_1/P2_1A_outcome_report.md` |
| **E7-FAST D2 EV gate = GO**：M2 `min(pilot,Q95)` 相对 rolling-Q95 单独使用，train+val Over improvement 30.08%，test 39.65%，CoverageRatio 77.97%–86.95% | E7-FAST EV validation | `reports/E7_FAST_EV_gate.md`、`reports/E7_FAST_TEST_CONSUMED.md` |
| **E7-FAST D3 system gate = FAIL/CONDITIONAL**：corrective audit 后 train+val 系统效果 0.01%，test 回放 4.46%/6.03%；旧 D3 系统收益数字作废 | E7-FAST corrective audit | `reports/E7_FAST_system_gate.md`、`reports/patent_definition/05_experiment_evidence_summary_v3.md` |
| **CORE-SEARCH Round 3 CLOSED**：R3-A/R3-C STOP，R3-D 仅在有真实 thermal data 时重开；当前无成熟 GO 核心专利 | CORE-SEARCH decision | `reports/core_search/CORE_SEARCH_DECISION_05_ROUND3_CLOSE.md` |
| **CORE-SEARCH Round 4 Decision #06**：R4-C0 STOP；R4-A0 原聚合源 DATA_PENDING；不进入系统层 | R4 data gate | `reports/core_search/CORE_SEARCH_DECISION_06_R4_DATA_GATE.md` |
| **R4-A0b RWTH official audit**：官方源已落地，actual power + optimized schedule + SOC，test_2 原始 timestamp 标签对齐；无 temperature/status/limit/alarm，LEVEL B tracking-only | R4-A official data gate | `reports/core_search/CORE_SEARCH_R4_A0b_RWTH_OFFICIAL_AUDIT.md` |
| **R4-A1 A1-0/A1a**：官方时区归一对齐 PASS；15min active shortfall ratio 0.696 = STRONG_A1B；raw-label diagnostic 0.015 = STOP | R4-A tracking magnitude, suspended | `reports/core_search/CORE_SEARCH_R4_A1_TRACKING_GATE.md` |
| **R4-A1S semantics audit**：论文 Test 2 anchors 支持 S0 raw-label preferred；S1 时区归一产生伪强信号；A1a STRONG suspended，A1b/system layer blocked | R4-A corrective audit | `reports/core_search/CORE_SEARCH_R4_A1S_SEMANTICS_AUDIT.md` |
| **R4-A1S-2 paper metric reproduction**：固定 S0 后，event anchors 通过、energy 单一变体通过，但 power RMSE/MAD 未能按 ±15% 复现；R4-A STOP | R4-A corrective audit close | `reports/core_search/CORE_SEARCH_R4_A1S2_PAPER_METRIC_REPRO.md` |
| **Decision #07 Round 4 close**：R4-A STOP、R4-C CLOSED、R4-B DEFER、R4-D NOT STARTED；不启动 Round 5 | Round 4 close | `reports/core_search/CORE_SEARCH_DECISION_07_ROUND4_CLOSE.md` |

门判定：**当前 core patent = NO-GO / 无成熟 GO 核心专利**。M2 双重上调限制是 VALID MODULE，
可作为 narrow defensive package HOLD；Final R1/P1/P2/E7-FAST v3 均为历史阶段线。

### 尚未证明（全部为 D 级假设，禁止对外断言）

- 差值可被其他车辆吸收；
- 短时可执行功率区间可生成且有效；
- 支持域内有界修正（active correction）在主测试域普遍有足够价值；
- 控制权限切换机制能产生闭环/经济收益；
- 可减少储能补偿；
- 可提高光伏消纳；
- 任何闭环收益 / 站级经济效益 / 全车型普遍适用。
- D3 recovery / Q95 触边恢复具有独立控制价值。

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

- **当前最新（CORE-SEARCH Round 4 / R4-A0b）**：**core-patent status = NO-GO / 当前无成熟 GO 核心专利**。
  当前权威是 `core_search/CORE_SEARCH_MASTER_PLAN.md`、
  `reports/core_search/CORE_SEARCH_DECISION_05_ROUND3_CLOSE.md`、
  `reports/core_search/CORE_SEARCH_DECISION_06_R4_DATA_GATE.md`、
  `reports/core_search/CORE_SEARCH_R4_A0b_RWTH_OFFICIAL_AUDIT.md`、
  `reports/core_search/CORE_SEARCH_R4_A1S2_PAPER_METRIC_REPRO.md`、
  `reports/core_search/CORE_SEARCH_DECISION_07_ROUND4_CLOSE.md`。
  - E7-FAST/M2：D2 EV 层 M2 双重上调限制为 VALID MODULE，可作为 narrow defensive package HOLD。
  - 降级/删除：D3 recovery 已由 P2.1A formal FAIL 删除；D3/BESS/PCC 系统效果经 corrective
    audit 后 train+val FAIL、test CONDITIONAL，只能作弱从属/背景。
  - 禁止引用：旧 D3 系统收益数字（shortfall 降 30%/40%，BESS 临时补偿降 15%/41%）已作废。
- **历史阶段线**：审查结论52 Final R1 Patent Gate（PROTECTIVE GO + D2/D3 融合）→
  P1 formal No-Go（recent_var 移出核心）→ Patent Gate 2（NARROW CONDITIONAL GO）→
  P2 formal（SUCCESS / NARROW GO）→ P2.1A D3 falsification FAIL → E7-FAST v3 收窄。
- 审查结论33/34 准入 R1 扩展审计；结论45/46 A5 protocol v1.2 FINAL FREEZE（`9302a7d`）；
  结论47–51 A5 正式运行（baseline `34f04f6`，Evidence commit `a827df3`）。
- K1.2.2 审查通过（`review/审查结论5.md`），E0-Full 数据构建完成。

## 10. 下一阶段（Decision #07 后）

1. **Round 4 closed**：R4-A STOP，R4-C CLOSED，R4-B DEFER，R4-D NOT STARTED。
2. **不重开 R4-A/R4-C**：不得用 raw-label 1.5%、S1 69.6%、新 timestamp shift、metric variant、ML 或子集救援。
3. **不启动 Round 5**：先做问题级复盘，只有新的真实数据支撑物理机制时才允许设计新数据门。

现有技术边界：单模块 A/B/C/D 全高拥挤；主风险 ACN 族
（US10926659 / US20200254896A1，同数据源最近邻，observation→conservative constraint→
scheduling constraint→feasibility relaxation）。v3 规避锚 = M2 双重上调限制
（当前桩侧允许值 + 历史实际响应支持水平）+ EV 群请求限幅；D3 recovery 不再作为规避锚。
