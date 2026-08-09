# R1 E1 门报告：K1 全量硬切分复现——问题强度（E1）停止线判定

实验编号：E0F-06 / R1（E1 部分；E3 部分另行报告）
日期：2026-08-09（审查结论26 复核修订）
协议：`review/审查结论7.md` §10.1（冻结主复现）+ §11（失败止损，情况二）
预注册：`configs/k1_preregister.yaml`（K1_preregister_v1 + k1_1/1_2/1_2_2 corrections）、`configs/e0_full.yaml`（seeds + 停止线）
门判定：**train = PASS、validation = PASS、test = FORMAL FAIL（2/5 停止线未过）→ 情况二触发 → 新门评审 = Conditional Continue within R1 only**

## 1. 结论摘要（审查结论26 定版）

- R1 E1 在**主证据宇宙（main_evidence_universe = L1_strict_matched ∧ role==main ∧ split∈{train,validation,test}，13,477 会话）**上按硬切分逐 split 冻结复现 K1。
- **train（9,426 会话，核心母体 4,670）：5/5 停止线全过**。核心事件会话率 11.35%（≥5%），中位功率差 1.272 kW（≈工作功率 36.4%），时间置换差值 95%CI [3.03, 4.90]pp（下界>0），单桩占比 9.6%、单月 16.5%，done 阶段切断后成立。
- **validation（3,896 会话，核心母体 1,813）：5/5 停止线全过**。核心率 14.07%，中位差 1.284 kW（36.8%），CI [3.79, 6.66]pp，单桩 11.5%、单月 30.5%，done 切断成立。
- **test（155 会话，核心母体 40）：FORMAL FAIL（2/5 停止线未过）**。核心率 7.5%（通过）、中位差 1.269 kW（通过）、done 切断后结论仍成立（通过）；但**置换 CI 下界 <0（diff CI [−5.00, +12.50]pp）** 与 **单桩主导（90.9%，>50%）** 失败。test 全部 11 个核心事件落在 2020-06，桩 `2-39-79-382` 占 10/11。
- **正式结论必须记为 FAIL，不是"基本通过只是 test 太小"**。test 中机制方向仍可见，但冻结停止线未通过；低样本量和 L1 证据覆盖坍缩是重要解释候选，但**目前无法区分它与真实时间漂移、站点特异性或机制泛化不足**。不得把 155 会话 test 标记为事后"不可评估"。
- **情况二已被触发**（train/val 成立、test 不成立）→ 不改阈值、不换月份、不删除不利池、不增加复杂模型，**召开新门评审**。本轮评审决议：**不判 E1 mechanism No-Go**（train/val 稳定 + 多站多月 + 负对照成立）；**也绝不豁免 test FAIL**（test 证据面过小且集中，不能宣称机制跨时间/跨站成立）。
- **继续 R1-E3 获批准**，但只作为 R1 内部证据补全；**仍不批准 E1-Full、E2、E4**，不能用 E3 的好结果"救"E1 test FAIL。最终仍需门评审决议：收缩场景 / 限定 support domain / 转 D1-P / No-Go。
- **专利方向含义**：不支持宽泛主张"任意站点、任意时期都能稳定识别车辆响应能力"，该方向降权；与 D1-R 最有价值部分一致的是 **support-domain gating + protective fallback**（识别响应状态 → 判断是否在数据支持域 → 充分则输出 executable interval / bounded correction，不足则 fallback / protective bound）。
- **E1-Lite 冻结口径逐位复现通过（fidelity machine check）**：`experiments/e1_full/fidelity_check.py` 在冻结 K1 样本上复现 core_denom 2,941、率 11.8667%、中位 1.2794 kW、置换 CI [3.5249, 5.7577]pp 全一致，输出 `results/raw/E1F/R1_E1_fidelity.json` 并通过测试锁定。

## 1.1 关键背景：不是"随机抽样"，而是 L1 证据覆盖坍缩

- E0F-02 对 Caltech 主集的严格时间切分原为 **train=31,585 / validation=10,528 / test=10,528**。
- 再筛 `L1_strict_matched ∧ role==main` 后变成 **9,426 / 3,896 / 155**：test 仅保留 **≈1.5%**（10,528 → 155）。
- 因此 test 的小样本**不是普通随机波动，而是后期 L1 matched evidence availability collapse**：test 月份（2020-05/06/07/08/11）处于疫情恢复期，matched+pilot 会话大幅减少。切分本身按 `[connection_time, session_id]` 确定性时间排序，**无随机性**，不能以"随机抽样特征"解释集中度。
- test 的 40 个 core-denom 会话逐月分布：**2020-05=6 / 2020-06=13 / 2020-07=7 / 2020-08=2 / 2020-11=12**；11 个核心事件全部落在 2020-06（单桩 2-39-79-382 占 10/11）。

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
- **解释必须保留不确定性**：test 中机制方向仍可见（率 7.5% ≥5%、中位差 1.269 kW 达线、置换 diff 方向为正、done 切断成立），但冻结停止线未通过；低样本量和 L1 证据覆盖坍缩（test 10,528 → 155，≈1.5%）是重要解释候选，**但目前无法区分它与真实时间漂移、站点特异性或机制泛化不足**。不能据此断言"只是 COVID，机制其实肯定跨时间/跨站成立"。

## 4. Fidelity machine check（R1 严格复现证明，审查结论26 P1）

`experiments/e1_full/fidelity_check.py` 在冻结 K1 样本（caltech.California_Garage_01、2018-11 + 2019-03/04/05/08/10、5,961 会话）上复现，输出 `results/raw/E1F/R1_E1_fidelity.json` 并被 `tests/test_e1_full_fidelity.py` 锁定：

| 冻结值 | K1（E1_Lite_gate.md §4/§5 / e1_lite_summary.json） | R1 复现（e1_stats） | 差异 |
|---|---|---|---|
| core_denom | 2,941 | 2,941 | 0 |
| 核心事件会话率 | 11.8667% | 0.11866712002720163 | 0 |
| 中位功率差 | 1.2794 kW | 1.2794 kW | 0 |
| 置换 CI（pp） | [3.5249, 5.7577] | [0.03524878, 0.05757679] | 0 |

→ R1 统计实现与 K1 同源、逐位一致；train/val/test 的差异完全来自宇宙与切分定义，实现无漂移。机器门确保任何人修改 `e1_stats.py` 立即炸测试（对 K1 冻结数值逐位比对，ATOL=1e-6，且锁定冻结样本合格会话数=5,961）。

## 5. 停止线判定汇总（§10.1 E1 停止线）

| 停止线 | train | validation | test |
|---|---|---|---|
| 核心段事件会话率 ≥5% | 11.35% ✓ | 14.07% ✓ | 7.50% ✓ |
| 中位功率差 ≥0.5kW 或 ≥10% 工作功率 | 1.272 ✓ | 1.284 ✓ | 1.269 ✓ |
| 置换差值 CI 下界 >0 | ✓ | ✓ | **✗（下界 −5.00pp）** |
| 不能由单桩或单月主导 | 9.6%/16.5% ✓ | 11.5%/30.5% ✓ | **✗（90.9%/100%）** |
| done 阶段切断后结论仍成立 | ✓ | ✓ | ✓ |
| **汇总** | **PASS** | **PASS** | **FAIL（2/5）** |

## 6. 判定与下一步（协议情况二；审查结论26 定版）

按 `审查结论7.md` §11 情况二（K1 指标在 train 成立、test 不成立）：

处理约束（已遵守，未做任何调整）：
- 不改阈值；
- 不换月份；
- 不删除不利池（test 不再从 13,477 中抽子集重新判定）；
- 不增加复杂模型。

本轮门评审决议（审查结论26，2026-08-09）：
- **不判 E1 mechanism No-Go**：train/validation 稳定（率 11–14%、中位差 ~1.27–1.28 kW、置换 CI 明确 >0、多站多月、done-cutting 后核心现象仍在），没有依据说"pilot–actual 响应差机制不存在"。
- **也绝不豁免 test FAIL**：test 只有 40 core sessions / 3 event sessions / 11 events，10/11 同一站、11/11 同一月、置换 CI 跨 0，没有依据说"机制其实肯定跨时间/跨站成立"。这是必须保留的不确定性。
- **批准继续 R1-E3**（仍属同一 R1，非新模型）：只作 R1 内部证据补全，**不能挽救已冻结的 E1 test FAIL**；即使 E3 全 PASS，也不能直接写 "R1 = PASS"，最终仍需明确门评审决议。
- **仍不批准 E1-Full、E2、E4**。

正式状态：
```text
E0F-01..05            PASS
E0F-06 / R1
    E1 train          PASS
    E1 validation     PASS
    E1 test           FORMAL FAIL
                      ↓ 情况二
                  新门评审 = Conditional Continue within R1
                      ↓
                  完成 E3 + 扩展审计 → 最终 R1 决议
E1-Full / E2 / E4     NOT APPROVED
```

下一步动作：
1. **修复 `month_conn` fan-out P1 债务**（`reports/E0F_raw_duplicate_gate_amendment.md:56-59`），R1 E3 报告中同时报 K1-E3 修复前后数值；
2. **实现 E3 R1 runner**，按治理顺序：code-only commit → 冻结 SHA → clean worktree → train/validation → 确认无阈值改动 → test 一次 → evidence-only commit；
3. 完成后继续 §10.2 全量扩展审计（其他车库/月份、JPL、office001、异常月份、field mode），为最终 R1 决议提供完整证据面。

test 的"证据面不足"说明（供评审参考，**非豁免理由**，不作为事后"不可评估"标记）：
- test 核心母体 40 会话远小于 train(4,670)/val(1,813)，bootstrap CI 半宽 ±8.75pp，无法在 α 下拒绝 H0；
- 单桩主导源于 2020-06 极低量窗口的集中，且与 K1-X 已知的低量期限制一致；
- 方向性证据一致：test 率 7.5% ≥5%、中位差 1.269 kW 达线、置换 diff 方向为正、done 切断成立 —— 机制在 test 内**可见但未达标**；
- 这些不构成 FAIL 的豁免，只是后续门评审解释集中度时的候选原因（时间漂移/站点特异性/泛化不足均不可排除）。

## 7. 工件、溯源与复现

- 摘要：`results/raw/E1F/e1_full_summary.json`（per_split 全字段、negative_controls、seeds、stop_lines、r1_verdict_on_test、provenance）
- **溯源（审查结论26 P1）**：`results/raw/E1F/e1_full_provenance.json` —— `evidence_commit=44fa88c`、`formal_test_exposure=44fa88c`、`runtime_code_clean=not independently provable from Git history`（44fa88c 代码与 evidence 同次提交，Git 历史无法独立证明 test 暴露前实现已冻结；阈值/人口/seeds/K1 fidelity 均已冻结且 test 为负面结果，故不因此作废）。**未倒填**为 "formal run code_sha=44fa88c clean"。`e1_full_summary.json` 中 provenance 字段记录的是治理修复后的运行时状态，非 44fa88c 原始运行。
- **fidelity machine check（审查结论26 P1）**：`experiments/e1_full/fidelity_check.py` + `tests/test_e1_full_fidelity.py` 锁定 `results/raw/E1F/R1_E1_fidelity.json`（core_denom=2,941、rate=0.118667、median=1.2794、置换 CI=[3.5249, 5.7577]pp，全部逐位一致；另锁定冻结样本合格会话=5,961）。任何 `e1_stats.py` 改动跑测试即炸。
- 明细：`results/raw/E1F/{train,validation,test}_event_table.parquet`、`{split}_fail_cases.csv`、`{split}_month_summary.csv`、`{split}_phase_summary.csv`、`{split}_session_summary.csv`
- 代码：`src/patent_preexperiment/e1_full/loader.py`、`src/patent_preexperiment/e1_full/gate.py`（正式门退出码 + 溯源）、`experiments/e1_full/run.py`、`src/patent_preexperiment/response/e1_stats.py`（共享冻结统计）
- **正式门退出码（审查结论26 P0）**：`formal_exit_code(summary)` 读 `r1_verdict_on_test.verdict`，PASS → 0、FAIL → 1；合成 summary 单测覆盖 PASS/FAIL/缺字段。**不再**用 `bool(summary)` 恒真导致的 "FAIL 也返回 0"。`e1_full_summary.json`（44fa88c 冻结版）不含此字段，不重跑正式 test。
- 复现（**不重跑正式 test**）：`..\venv\Scripts\python.exe experiments/e1_full/run.py` 会重写 `e1_full_summary.json` 并输出 provenance；44fa88c 的正式 evidence 保持冻结，只在未来按治理顺序的 evidence-only commit 时更新。原 44fa88c 运行 SHA256 `80D863BF14E62013BC570132B2A2D1D9FAC54B3C530B38A00F3ABBF4A9886CF2`。
- 测试：`tests/test_e1_full_loader.py`（10）、`tests/test_e1_full_runner_gate.py`（6）、`tests/test_e1_full_fidelity.py`（2，锁 K1 冻结值）；全仓 211+18 = 229 passed（本地记录，非 GitHub Actions 独立证明）。

## 8. 局限、已登记技术债与治理记录

- test 母体过小（40）本报告已如实列为 FAIL 证据面，非实现缺陷；L1 覆盖坍缩（test 10,528→155，≈1.5%）已单列于 §1.1，不作为"随机抽样"解释。
- `month_conn` fan-out P1 技术债已登记（`reports/E0F_raw_duplicate_gate_amendment.md:56-59`），**须在 E3 冻结主复现前修复**，并在 R1 E3 报告中同时报 K1-E3 修复前后数值（n_cycles 36,736 / unique 36,683 / duplicate 53 / A2 rate 39.261215% / daily energy share 3.892868% 为历史冻结值）。
- 2021 全年与低覆盖/异常月份（2019-12、2020-02、2020-04、2020-12）只作 stress/敏感性，未进入主切分（已校验 main universe 不含异常月份）。
- **治理记录**：本报告已按审查结论26 修订——删除"随机抽样特征""不是机制缺失"过强措辞；结论定版为 Formal FAIL / 情况二 / Conditional Continue within R1；E1-Full/E2/E4 保持 NOT APPROVED；E3 只能补全信息面不能救 E1。
