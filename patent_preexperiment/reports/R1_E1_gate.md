# R1 E1 门报告：K1 全量硬切分复现——问题强度（E1）停止线判定

实验编号：E0F-06 / R1（E1 部分；E3 部分另行报告）
日期：2026-08-09
协议：`review/审查结论7.md` §10.1（冻结主复现）+ §11（失败止损，情况二）
预注册：`configs/k1_preregister.yaml`（K1_preregister_v1 + k1_1/1_2/1_2_2 corrections）、`configs/e0_full.yaml`（seeds + 停止线）
门判定：**train = PASS、validation = PASS、test = FAIL（2/5 停止线未过）→ 触发情况二（新门评审），R1 E1 不自动放行**

## 1. 结论摘要

- R1 E1 在**主证据宇宙（main_evidence_universe = L1_strict_matched ∧ role==main ∧ split∈{train,validation,test}，13,477 会话）**上按硬切分逐 split 冻结复现 K1。
- **train（9,426 会话，核心母体 4,670）：5/5 停止线全过**。核心事件会话率 11.35%（≥5%），中位功率差 1.272 kW（≈工作功率 36.4%），时间置换差值 95%CI [3.03, 4.90]pp（下界>0），单桩占比 9.6%、单月 16.5%，done 阶段切断后成立。
- **validation（3,896 会话，核心母体 1,813）：5/5 停止线全过**。核心率 14.07%，中位差 1.284 kW（36.8%），CI [3.79, 6.66]pp，单桩 11.5%、单月 30.5%，done 切断成立。
- **test（155 会话，核心母体 40）：2/5 停止线未过**。核心率 7.5%（通过，≥5%）、中位差 1.269 kW（通过，≥0.5kW/10%）、done 切断后结论仍成立（通过）；但**置换 CI 下界 <0（diff CI [−5.00, +12.50]pp）** 与 **单桩主导（单桩占比 90.9%，>50%）** 失败。test 全部 11 个核心事件落在 2020-06，桩 `2-39-79-382` 占 10/11。
- **不构成自动放行**：按协议情况二，"K1 指标在 train 成立、test 不成立" → 不改阈值、不换月份、不删除不利池、不增加复杂模型，**召开新的门评审**；可能结论为收缩场景 / 降级特定站点或 field mode / 收缩为保护型上界 / No-Go。
- **test 失败的性质是"样本不足 + 单一站点集中"，不是机制缺失**：test 核心母体仅 40 会话，置换 CI 宽到 [−5, +12.5]pp（点估计仍为正方向 +2.5pp，率 7.5% 高于置换均值 5.0%）；单一站点集中是 2020-06 极端低量期（test 仅 155 会话）下的随机抽样特征。方向性证据存在但**不足以按冻结规则通过**。
- **E1-Lite 冻结口径逐位复现通过（fidelity check）**：共享 `e1_stats.py` 在冻结 K1 样本上复现 core_denom 2,941、率 11.8667%、中位 1.2794 kW、置换 CI [3.5249, 5.7577]pp，与 `reports/E1_Lite_gate.md` 冻结值一致（6 位小数）。这证明 R1 统计实现与 K1 同源，差异完全来自宇宙与切分，不是实现漂移。

## 2. 范围与方法（冻结，不因 test 结果调整）

| 项 | 冻结值 |
|---|---|
| 宇宙 | main_evidence_universe：sample_layer==L1_strict_matched ∧ role==main ∧ split∈{train,validation,test} = **13,477 会话 / 4,902,115 行**（registry 校验 missing=0 / extra=0） |
| 切分 | E0F-02 硬时间切分（站点时间顺序 60/20/20，按连接时间），test 仅正式评价一次 |
| 阈值 | V2.0 §4.3：P_on=0.5 kW、δ_r=0.25、δ_p=0.5 kW、T_event=5 min、初始排除 5 min、尾段排除 10 min、pilot 工作阈值 1.0 A |
| 事件定义 | 与 K1 一致（K1.2 切断：core/mid/tail 边界强制切断，各段独立重跑持续 ≥T_event；K1.2.1 done 能量拆分；K1.2.2 置换事件分子强制限制 core 母体） |
| 统计 | 会话内时间置换（seeds [7,11,13]）、bootstrap 差值 CI（seed 42、n_boot 2000、母体=core 母体）、事件会话率、中位功率差、单桩/单月占比 |
| 功率口径 | 实测 Power → Voltage×Current（computed）→ 额定电压×Current（estimated）；caltech=240V |
| done 锚点 | `doneChargingTime`（API 优先），缺失时离线推断，再缺失 missing |

test 结果出来后未做任何调整；§10.2 全量扩展审计（其他车库/月份、JPL、office001、异常月份、field mode）未用于挽救 test，作为独立扩展另行报告。

## 3. 逐 split 冻结主复现结果

| 指标 | train | validation | test | 停止线 |
|---|---|---|---|---|
| 合格会话 | 9,426 | 3,896 | 155 | ≥500（train/val ✓；test 非独立门槛） |
| 核心运行窗口会话（母体） | 4,670 | 1,813 | **40** | — |
| 核心事件数 / 事件会话数 | 1,106 / 530 | 564 / 255 | 11 / 3 | — |
| 核心事件会话率 | **11.35%** | **14.07%** | **7.50%** | ≥5% ✓ |
| 中位功率差 | **1.272 kW（36.4%）** | **1.284 kW（36.8%）** | **1.269 kW（35.9%）** | ≥0.5kW 或 ≥10% ✓ |
| 置换差值 95%CI（pp） | [3.03, 4.90] | [3.79, 6.66] | **[−5.00, 12.50]** | 下界 >0：train/val ✓ / **test ✗** |
| 单桩占比 | 9.6% | 11.5% | **90.9%** | ≤50%：train/val ✓ / **test ✗** |
| 单月占比 | 16.5% | 30.5% | **100%**（2020-06） | ≤50%：train/val ✓ / **test ✗** |
| done 切断后成立 | 成立（post_done 能量 0） | 成立 | 成立 | ✓ |
| 出现核心事件的桩数 | 39 | 33 | 2 | — |
| done 锚点 api/inferred/missing | 8,990 / 345 / 91 | 3,859 / 34 / 3 | 132 / 1 / 22 | — |

### 置换负对照细节（test 的详细诊断）

| 指标 | train | validation | test |
|---|---|---|---|
| 真实核心率 | 11.35% | 14.07% | 7.50% |
| 置换均值（3 种子） | 7.39% | 8.83% | 5.00% |
| diff 点估计 | +3.96pp | +5.24pp | +2.50pp |
| bootstrap 95%CI | [3.03, 4.90]pp | [3.79, 6.66]pp | [−5.00, 12.50]pp |
| 母体（bootstrap_n） | 4,670 | 1,813 | 40 |

train/val 的 diff 点估计与 CI 均与 E1-Lite 冻结值（+4.64pp，[3.52, 5.76]pp）同量级。test 的 diff 方向为正（+2.5pp）、真实率高于置换均值，但母体仅 40 → CI 无法收紧到 >0。

### test 单一站点集中诊断

- test 全部 11 个核心事件发生在 **2020-06**（单月占比 100%，cutoff 50%）；
- 桩 `2-39-79-382` 占 10/11（90.9%，cutoff 50%）；
- 3 个事件会话来自 2020-06 低量期（test 共 155 会话，COVID 后恢复期）。
- 与 K1-X（jpl 2020-06/07 COVID 低量期）的"量不足只能作弱证据"性质一致：**低量窗口内事件天然集中，不能据此断言跨月/跨站可推广，也不能据此否定机制存在**。

## 4. Fidelity check（R1 严格复现证明）

共享 `src/patent_preexperiment/response/e1_stats.py` 在冻结 K1 样本（caltech.California_Garage_01、2018-11 + 2019-03/04/05/08/10、5,961 会话）上复现：

| 冻结值 | K1（E1_Lite_gate.md §4/§5） | R1 复现（e1_stats） | 差异 |
|---|---|---|---|
| core_denom | 2,941 | 2,941 | 0 |
| 核心事件会话率 | 11.9%（11.8667%） | 11.8667% | 0 |
| 中位功率差 | 1.28 kW | 1.2794 kW | 0 |
| 置换 CI（pp） | [3.52, 5.76] | [3.5249, 5.7577] | 0 |

→ R1 统计实现与 K1 同源、逐位一致；train/val/test 的差异完全来自宇宙与切分定义，实现无漂移。

## 5. 停止线判定汇总（§10.1 E1 停止线）

| 停止线 | train | validation | test |
|---|---|---|---|
| 核心段事件会话率 ≥5% | 11.35% ✓ | 14.07% ✓ | 7.50% ✓ |
| 中位功率差 ≥0.5kW 或 ≥10% 工作功率 | 1.272 ✓ | 1.284 ✓ | 1.269 ✓ |
| 置换差值 CI 下界 >0 | ✓ | ✓ | **✗（下界 −5.00pp）** |
| 不能由单桩或单月主导 | 9.6%/16.5% ✓ | 11.5%/30.5% ✓ | **✗（90.9%/100%）** |
| done 阶段切断后结论仍成立 | ✓ | ✓ | ✓ |
| **汇总** | **PASS** | **PASS** | **FAIL（2/5）** |

## 6. 判定与下一步（协议情况二）

按 `审查结论7.md` §11 情况二（K1 指标在 train 成立、test 不成立）：

处理约束（已遵守，未做任何调整）：
- 不改阈值；
- 不换月份；
- 不删除不利池（test 不再从 13,477 中抽子集重新判定）；
- 不增加复杂模型。

下一步动作：
1. **召开新的门评审**：以本报告 + `results/raw/E1F/` 全量证据（event_table、fail_cases、month/phase/session summary）为输入；
2. **R1 E1 不自动放行**：E0F-06 验收条件 "R1 PASS 才批准进入 E1-Full + E2" 对 E1 部分当前未满足；
3. **继续完成 R1 剩余部分**（E3 冻结主复现 + §10.2 全量扩展审计 + E3 扩展），为门评审提供完整证据面；
4. 门评审的可能结论（供评审选用，均不隐含本次已选定）：收缩场景 / 降级为特定站点或 field mode 方向 / 收缩为保护型上界 / No-Go。

test 的"不可用/不足"说明（供评审参考，非豁免理由）：
- test 核心母体 40 会话远小于 train(4,670)/val(1,813)，bootstrap CI 半宽 ±8.75pp，无法在 α 下拒绝 H0；
- 单桩主导源于 2020-06 极低量窗口的随机集中，且与 K1-X 已知的低量期限制一致；
- 方向性证据一致：test 率 7.5% ≥5%、中位差 1.269 kW 达线、置换 diff 方向为正、done 切断成立 —— 机制在 test 内**可见但未达标**。

## 7. 工件与复现

- 摘要：`results/raw/E1F/e1_full_summary.json`（含 per_split 全字段、negative_controls、seeds、code_sha）
- 明细：`results/raw/E1F/{train,validation,test}_event_table.parquet`、`{split}_fail_cases.csv`、`{split}_month_summary.csv`、`{split}_phase_summary.csv`、`{split}_session_summary.csv`
- 代码：`src/patent_preexperiment/e1_full/loader.py`、`experiments/e1_full/run.py`、`src/patent_preexperiment/response/e1_stats.py`（共享冻结统计）
- 复现：`..\venv\Scripts\python.exe experiments/e1_full/run.py`（输出 SHA256 `80D863BF14E62013BC570132B2A2D1D9FAC54B3C530B38A00F3ABBF4A9886CF2`，两次运行一致）
- 测试：`tests/test_e1_full_loader.py`（10 tests）全过；全仓 211 tests 过

## 8. 局限与已登记技术债

- test 母体过小（40）是本报告核心局限，属数据窗口现实而非实现缺陷；
- `month_conn` fan-out P1 技术债已登记（`reports/E0F_raw_duplicate_gate_amendment.md:56-59`），**须在 E3 冻结主复现前修复**，并在 R1 E3 报告中同时报 K1-E3 修复前后数值；
- 2021 全年与低覆盖/异常月份（2019-12、2020-02、2020-04、2020-12）只作 stress/敏感性，未进入主切分（已校验 main universe 不含异常月份）。
