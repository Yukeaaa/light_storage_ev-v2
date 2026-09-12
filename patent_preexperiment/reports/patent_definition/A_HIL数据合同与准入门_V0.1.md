# A HIL 数据合同与准入门 V0.1（pre-HIL 预注册）

- 日期：2026-09-12
- 状态：**准入门工具与合同已落地（可机器执行）**；synthetic 算法阶段**封板**——下一步为 BESS-PCS HIL adapter，不再改 synthetic 算法。
- 评审输入：2026-09-12 第二轮复审（架构 PASS / 真实设备接入 CONDITIONAL PASS；"下一步已经不应该继续改 synthetic 算法"）。
- 代码：`src/patent_preexperiment/a_ev/hil_contract.py` + `configs/a_ev_hil_contract.yaml` + `tests/test_hil_contract.py`（9 项）。
- **口径声明（不变）**：A-M3–M6 = UNVALIDATED、Round 5 = NOT STARTED、core-patent = NO-GO 不变。

---

## 1. 为什么需要准入门

当前唯一真正的大关：**把现有架构接到真实 PCS/BMS/PCC 上**，证明数据拿得到、指令发得下去、本地裁剪读得回来、反馈闭环真实工作。评审明确纪律：

> HIL 第一阶段的数据少任何一层，都必须在 admission gate 明确标成"某类机制不可验证"，而不是事后猜。

因此把字段清单与判定规则**预注册为可机器执行的合同**：`admit()` 输入现场字段可得性，输出**逐机制**的 VERIFIABLE / DERIVED / NOT_VERIFIABLE 判定与整体结论（ADMITTED / CONDITIONAL / REJECTED）。判定与字段清单随 HIL 场景集冻结，不依结果变动。

## 2. 字段合同（HIL 第一阶段强制记录）

| 字段 | 责任域 | 支撑机制 | 缺层后果 |
|---|---|---|---|
| command_id | EMS | 审计留痕、M6 写回关联 | 写回不可关联到指令 |
| requested_setpoint | EMS | M1 执行偏差、M2 能力学习、M3 站级缺口 | **核心——缺则 REJECTED** |
| translated_setpoint | 网关 | M1 上报限值区分、Reported 包络 | 限值区分降级（可推导） |
| accepted_setpoint | 设备 | M1 上报限值区分、M6 写回、Reported 包络、响应窗标定 | 缺失时必须声明推导口径 |
| write_ack | 适配器 | M6 写回、控制权仲裁 | 写回确认降级 |
| control_owner | EMS | 错误归因防线（控制权仲裁） | **多主则 REJECTED** |
| override_source / override_reason | 设备 | M1 外部约束/保护/模式判据 | 该判据只能靠注入模拟，真实分类不可验证 |
| applied_timestamp | 设备 | M1 响应观察窗、响应窗标定 | commissioning 标定不可跑 |
| p_meas | 设备 | M1/M2/M6 全链、噪声标定 | **核心——缺则 REJECTED** |
| pcc | PCC 独立表计 | 模块 6 残差通道、PCC 主指标 | 站级补偿通道不可验证 |
| soc / temp_c | BMS | M3/M5 可行域（SOC/温度约束） | 约束判据降级 |
| local_limits | BMS/PCS | Reported 包络、可行域 | Reported 层降级 |
| p_min_p_max | 组合 | M3/M5 动态可行域 | 承接规模不可验证 |

**判定规则**（预注册）：

```text
REJECTED     requested/p_meas 缺失（无执行偏差可言）
             ｜时钟不统一或偏差超预算（秒级偏差即混淆暂态/clamp/能力受限）
             ｜控制权非单一（隐形上游 = 错误归因不可控）
CONDITIONAL  核心闭环可得，但 (a) 存在 NOT_VERIFIABLE 机制（缺层显式列名）
             ｜ (b) 存在推导口径字段（DERIVED，须在 commissioning 实测验证推导链后升级 ADMITTED）
ADMITTED     全字段可得 + 时钟统一 + 单一控制权
```

**当前登记口径 = CONDITIONAL**：`accepted_setpoint` 多数 PCS 不直接外露，按推导口径登记（BMS 充放限值 + PCS 限功率寄存器 + 控制日志合成）——依赖它的机制（上报限值区分 / Reported 包络 / M6 写回 / 响应窗标定）可验证但**必须标注推导口径**，commissioning 期间实测验证推导链。

## 3. 四个现场接口真实性风险（评审点名，准入检查对应）

1. **PCS 能否同时提供 requested / accepted / actual？** 只能读实际功率时，accepted 须由 BMS 充放限值 + PCS 限功率寄存器 + 控制日志推导（合同已按推导口径登记；若连推导材料都没有 → M1 上报限值区分、Reported 包络 NOT_VERIFIABLE）。
2. **统一时钟**：PCC 表、EMS、PCS 日志错 2–3 秒即把暂态、clamp、能力受限搞混 → 合同时钟节（unified + max_skew_s，实测超预算 = REJECTED，时序判据与标定全部标记不可验证）。
3. **写 ACK ≠ 生效**："寄存器写成功"不等于"控制权已获得并实际生效" → write_ack 只作留痕，生效判定依赖 applied_timestamp + accepted + P_meas 的闭环；四层缺一即在门上标出。
4. **隐形上游控制权**：本地 EMS / 消防策略 / 削峰策略 / BMS / 厂家云同时写同一控制量是最易造成错误归因的现场问题 → control_authority 节强制登记 owners，非单一 = REJECTED。

## 4. REPORTED_LIMIT 边界（评审确认保持，冻结为设计决定）

`REPORTED_LIMIT` **不进入 ExecutionLearned**：BMS 报 30 kW 限值只封 Reported 包络（可行域取交），不写执行学习边界。两层独立保留：

```text
设备自己说能做到多少（Reported） ≠ 执行证据实际证明它能做到多少（ExecutionLearned）
```

代码现状已满足（`REPORTED_LIMIT` allows_update=False；`feasible_headroom` 只做局部取交，从不写 `state.up/down_bound`）——四层包络 `Physical ∩ Reported ∩ ExecutionLearned ∩ Service` 的成熟表达以此为准。

## 5. 首套台架与五个硬问题（进入 HIL 的验收口径）

```text
PCS/BESS A ＋ PCS/BESS B ＋ PCC 独立表计 ＋ EMS/A 控制器     （先不接 PV、桩、V2G）
```

1. 指令能否真实下发？
2. accepted/effective 值能否取得（或按推导口径合成）？
3. 实际响应时间是什么？
4. 人为 Pmax/Pmin 限值能否准确制造 ground truth？
5. A 的能力状态更新、承接、写回是否真的影响下一次控制？

五个跑通 → A 的工程可行性从"架构判断"升级为"设备级事实"。随后：HIL commissioning（每设备响应窗/噪声/判据带）→ V1.0 lock → formal A-EV → shadow → 受控真实站。

## 6. 状态定级（评审 2026-09-12 第二轮）

| 维度 | 状态 |
|---|---|
| 专利核心机制 | **PASS / 已冻结** |
| 算法逻辑 | **PASS** |
| 合成机制验证 | **PASS（阶段封板）** |
| 异构资源工程模型（[Pmin,Pmax]） | **PASS** |
| 命令链建模 | **PASS** |
| PCC 监督闭环 | **PASS** |
| 设备适配规范 | **PASS** |
| **HIL 数据合同与准入门** | **PASS（本轮新增，可机器执行）** |
| 真实 PCS 通讯/控制 | **未验证** |
| HIL 闭环 | **未开始正式验证** |
| 真实站效果 | **UNVALIDATED** |

## 7. Open items

1. 按合同逐项完成现场字段可得性核对，把 `a_ev_hil_contract.yaml` 从"预登记口径"替换为实测口径（accepted 推导链是否成立在 commissioning 验证）；
2. BESS-PCS adapter 实现（按 V0.3 §5 规范 + 本合同字段清单）；
3. 首套台架五问逐条留档；
4. 通过 commissioning 验证 accepted 推导链后，将准入门升级 ADMITTED 并进入 V1.0 lock。
