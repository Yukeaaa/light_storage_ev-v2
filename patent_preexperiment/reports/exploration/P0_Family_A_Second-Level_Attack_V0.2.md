# P0 Family A 第二轮反打（Second-Level Attack）V0.2

> **定稿日期**：2026-09-17
> **性质**：探索轨 3-a 第二轮。把 V1 §5.3 的四条残余假设（H-A1–H-A4）与 V1 之后的 H-A5 候选，
> 用**现有技术作为坐标系**再打一次；目标不是"找到别人做过就排除"，而是判断
> **我们到底还能不能形成新的技术结构**。
> **不是**：专利候选注册、完整 prior-art 检索、新颖性/创造性结论、FTO 结论、R5 启动。
> **前置**：`P0_配电容量受限与新增负荷_Problem_Reality_Audit_V1.md`（3-a V1）、
> `数据源准入审计_V1.md`（3-b）。
> **证据件**：`_raw_audit_familyA_2026-09-17/`（4 件权项级留痕 + 统一结构矩阵）、
> `_raw_audit_2026-09-17/`（V1 的两件专利留痕）。
> **代码/结果**：`patent_preexperiment/experiments/ha5_knockout/run.py` →
> `patent_preexperiment/results/raw/ha5_knockout/knockout_result.{json,md}`。
> **不改变**：`core-patent = NO-GO` / `Round 5 = NOT STARTED` / `A-M3–M6 = UNVALIDATED`；
> 不改动 A/C 第一波文本、A-EV/HIL 代码、既有治理文件。

---

## 0. 本轮结论（先说结果）

**Family A 的第二层反打结果是否定的。** 四条残余假设已全部降级或杀掉，
新提的 H-A5 在 cheap-knockout 中被**普通基线逐点复现**，判定：

```text
H-A1  Service Admission ≠ Dispatch            → STOP THIS MECHANISM（generic）
H-A2  capacity withdrawal 后服务受控退化       → HIGH PRESSURE
H-A3  PCC 合规 ≠ 内部服务履约                  → NO RESIDUAL TECHNICAL GAP
H-A4  fallback → recovery                     → STOP THIS MECHANISM（generic）
H-A5  容量保障来源 ↔ 服务承诺依赖关系           → NO RESIDUAL TECHNICAL GAP
────────────────────────────────────────────────────────────────
Family A（1+7+8）  → DOWNGRADE / NO CURRENT RESIDUAL TECHNICAL GAP
                      ⚠️ 这不是"这个方向不能做"，而是：
                      「当前建模假设下，没有剩余技术机制值得继续投入」
```

**为什么是"更强的简单基线"而不是 prior art 杀掉了 H-A5**：
真正致命的一击来自本项目自己的 strongest-baseline knockout ——
`identity_order` 是个**无状态规则**，却与 H-A5 轨迹逐点相同。
这说明**不是"别人申请过"，而是"新增状态在我们自己的模型里没有体现出独立技术必要性"**。

$$
\boxed{
\text{Family A} = \text{DOWNGRADED} \;/\; \text{NO CURRENT RESIDUAL TECHNICAL GAP}
}
$$


**关键否证事实（一句话）**：
H-A5 主张"承诺对保障容量的**来源归属**必须作为持久状态存在"，
但 knockout 显示 —— **一个完全无状态的逐周期规则（按服务顺序优先）就能逐点复现 H-A5 的全部控制轨迹**
（S1：最大偏差 0 kW；S2：最大偏差 0 kW，错误作废电量 0 kWh）。
既然无状态即可复现，"必须持久化 provenance"这一技术必要性不成立。

---

## 1. V1 四条残留假设的二轮状态

| 假设 | V1 提法 | 本轮核到什么 | 状态词表 |
|---|---|---|---|
| **H-A1** | 先判"服务能否被承诺"，再决定"已承诺服务怎么 dispatch" | **承诺前做容量准入**已在 2024-04 优先权的 US20250326322A1 **独立权 1** 中：预约时间窗 + 超过最低阈值（RMPP / RE / 最小续航）+ 依最低阈值判站点单桩可用性；权 8 进一步用 `SPMax + SCNPMax + 已预约充电过程` 判可用性；权 10/22/36/49 还写了"容量下降时通知其他用户"。更早的 US10723230B2（二级证据）按电网容量阈值判是否可提供服务后生成预约。 | **STOP THIS MECHANISM**（generic 版） |
| **H-A2** | 已承诺服务在 `C_cond` 撤回后的受控退化 | WO2024105191A1 **权 1** 已把"受 **energy-reserve profile** 约束、在**滚动窗**内求解、并按解控制 setpoint"写成独立权；**权 8/24/31** 更把 `update the energy-reserve profile **in response to one or more completed events**` 写入从属权 —— 即"提前留余量保 readiness + 按已完成事件更新"。US12165224B2 **权 9** 把"未满足到达参数的成本"作为决策判据、**权 1/3** 允许已预约时段被**部分让渡**。 | **HIGH PRESSURE**（未全杀：见 §3 对象差异） |
| **H-A3** | PCC 合规 ≠ 内部每类服务仍满足原承诺 | 命题为真（V1 已立），但**不是技术方案**：给每个服务加 `E^required / deadline / slack` 再 `min Σ w_i s_i`，普通 MILP 即可表达"谁没完成"。 | **NO RESIDUAL TECHNICAL GAP** |
| **H-A4** | fallback → recovery 是否需要跨事务状态 | CN111098724B **独立权 1**（2018 年申请）已把完整链路写入：`中断请求 → 发中断指令（停止执行预约充电模式）→ 在预定时间段内检测充电执行信号（枪是否插入）→ 不存在则发恢复指令 / 存在则拒绝恢复`，并含"不同外置模块分配处理优先级"。 | **STOP THIS MECHANISM**（generic 版） |

### 1.1 需要与结论一并引用的边界

> **CN111098724B 只否定"把 generic 中断→降级→恢复动作链当作新机制"**，
> **不能**推论"站点容量撤回后的服务降级/恢复对象本身无空间"。
> 其"恢复"恢复的是**整车预约充电模式**，恢复条件是**本地执行状态（枪是否插入）**，
> 不是**外部容量回升**，且无跨服务核销。

> **US20250326322A1 为 A1 公开文本（非授权）**，权利范围可能变动；
> 其权 10/22/36/49 的 `reduction in charging capacity` **在权项中未指向外部可撤回容量**，
> 该成因须看说明书 —— 本轮**未做说明书逐段核验**，故标注 **说明书级待核**。
> 即使该句确指电网侧撤回，也只强化 H-A2 的压力，**不改变** §0 对 H-A5 的判定。

---

## 2. 4 件核心文献的 claim-level 结构矩阵

完整矩阵见 `_raw_audit_familyA_2026-09-17/structure_matrix.md`；权项原文见同目录 4 个 `*_claims.txt`。
本节只保留矩阵的**结论段**。

### 2.1 六维速览

| 维度 | US20250326322A1 | WO2024105191A1 | US12165224B2 | CN111098724B |
|---|---|---|---|---|
| **技术对象** | 预约 + 站点单桩可用性判定 | 滚动优化中的每资产 energy-reserve profile | 跨实体预约时段再分配 + 补偿 | 整车预约充电模式启停 |
| **状态** | 静态配置量 `SPMax/SCNPMax` + 预约占用记录 | **energy-reserve profile（持久，可滑动/锚定/更新）** | 时段所有权；AI 模型参数 | 预约充电模式标志 + 模块优先级 |
| **触发** | 用户预约；容量下降 | 滚动时步；scheduled event；**completed events** | **需求侧**：他人找不到未预约时段 | 外置模块中断请求 |
| **状态迁移** | 占用 → 重算可用性；容量降 → 仅通知 | profile 滑动 / 锚定 / 组合 / 按已完成事件更新 | 时段所有权或使用权转移 | 模式停止 → 检测 → 恢复 or 拒绝恢复 |
| **控制后果** | 分配 coupler；余量开放给其他桩 | 控制物理部件 **setpoint**；给 EV 关联时段/功率 | 电子授权使用时段；给让渡方替代时段 | 向整车控制器发中断/恢复指令 |
| **反馈** | **无** | ✅ **有**（completed events → 更新 profile） | ⚠️ 仅**模型训练**层（接受/拒绝作标注） | ✅ **有**（枪是否插入 → 是否恢复） |

### 2.2 最重要的一张对照：四个"状态"是不是同一类东西

| 文献 | 持久化了什么 | 被什么修改 | 是否等价于 H-A5 的 $\Gamma_j$ |
|---|---|---|---|
| US20250326322A1 | 预约占用（时间窗 × 单桩） | 预约 / 取消 | ❌ 无来源分解 |
| WO2024105191A1 | energy-reserve profile（能量裕度曲线） | **completed events** | ❌ 是**不确定性预留裕度**，不是**来源归属** |
| US12165224B2 | 时段所有权 + 模型参数 | 接受 / 拒绝（训练） | ❌ 是**所有权**，不是**来源** |
| CN111098724B | 预约充电模式标志 + 优先级 | 中断 / 恢复指令 | ❌ 无容量概念 |

**读法**：四件都持久化了"某物的可用性 / 所有权 / 裕度"，
**没有一件持久化"某承诺由哪一等容量支撑"**。所以 H-A5 的**语义入口确实未被直接占据** ——
但这是**必要非充分**条件。真正的关卡见 §4：*为什么该信息需要作为状态存在*。

### 2.3 由本轮矩阵直接读出的一条反证（重要）

WO2024105191A1 **权 8 / 24 / 31** 的存在，直接打掉了 H-A5 论证中最常被默认的一步：

> 「存在**跨滚动周期持续、且被执行反馈修改**的优化状态 ⇒ 这是一个新机制」

该命题**不成立**：Hitachi 已在 2022 年优先权中把这条写进从属权（且是"约束优化可行域 + 控制 setpoint"的完整闭环）。
因此仅凭"状态持续存在 + 被反馈修改"**不足以**构成残余。

---

## 3. H-A5 的残余定义（本轮工作定义）

> 定义来源：V1 之后的二轮攻击；本轮把它精确化为可检验形式，以便 cheap-knockout。

### 3.1 状态对象

$$
\Gamma_j=\Bigl(E_j^{\text{remain}},\ t_j^{\text{deadline}},\ q_j^{\text{firm}},\ q_j^{\text{cond}},\ s_j\Bigr)
,\qquad
q_j^{\text{firm}}+q_j^{\text{cond}}=E_j^{\text{remain}}
$$

`q^firm / q^cond` = **服务 j 当前尚未履行的承诺中，由 firm capacity / conditional capacity 支撑的份额**。

### 3.2 四个动作

$$
\text{commit}\ \rightarrow\ \text{consume}\ \rightarrow\ \text{invalidate/reallocate}\ \rightarrow\ \text{recover}
$$

**硬要求**（V1→V0.2 的收紧）：这些动作必须改变**实际控制允许域**，
而不只是改账面上的标签。判据（用户生死门）：

$$
\Bigl|P_i(t)^{H\text{-}A5}-P_i(t)^{\text{baseline}}\Bigr|>0
\quad\text{or}\quad
\Bigl|E_i(t)^{H\text{-}A5}-E_i(t)^{\text{baseline}}\Bigr|>0
\quad\text{or}\quad
\Bigl|P_{PCC}(t)^{H\text{-}A5}-P_{PCC}(t)^{\text{baseline}}\Bigr|>0
$$

若三者全为 0 → 主要是**账务/业务语义**，不得继续包装成技术机制。

### 3.3 与"优先级 / 预约 / 优化"的界

H-A5 **只能**主张 **provenance / dependency / consumption of guaranteed vs conditional capacity**；
**不得**主张 priority / reservation / optimization 本身。另存两个**已存禁区**：

- **US8521337B1**（负荷可选 firm / non-firm / 二者，按可靠等级排供）：**二级证据，本轮未核**
  → 不得申请"给服务分 firm/non-firm 等级"**本身**。（该禁区不依赖本轮判定，见 §6.2）
- **CN120197914B 权 7**（时变容量上限 + 动态资源分配 + 滚动时域 + 随机情景 + 风险资源预留，
  逐级从属 7→4→3→2→1）：不得以"EV 需求预测 + 时变容量上限 + rolling horizon + reserve"为核心差异。

---

## 4. 最强常规基线（含本轮新增的两条）

| 基线 | 内容 | 来源 |
|---|---|---|
| B0 firm-only | 永远只用 `C_firm` | V1 §5.2 |
| B1 dynamic-follow | 直接把 dynamic schedule 当 `P_PCC` 上限 | V1 §5.2 |
| B2 deterministic MILP/MPC | 联合 EV/BESS/PV/负荷优化 | V1 §5.2 |
| B3 robust/stochastic MPC | 对 `C_cond` 下调与负荷/PV/EV 不确定性建模 | V1 §5.2 |
| B4 managed charging | 按 deadline / kWh request / SOC / priority 调度 | V1 §5.2 |
| **B5-recompute** | **纯逐周期重解，无 provenance**。并列最优时用两种规范 tie-break：<br>`proportional`（等权对称解·水填充）/ `identity_order`（按服务顺序优先） | **本轮新增** |
| **B6-parametrized** | **逐周期 MILP + 上周期类别分解作为参数携带**；余量按"先 firm 后 cond"回填 | **本轮新增（最关键）** |

> **为什么必须补 B6**：若只拿 B5-recompute 当基线，任何"provenance 影响轨迹"的结果都会被误读为
> "必须持久状态"。B6 证明：**把上一周期的分解作为参数传进去**，
> 普通滚动 MILP 就能复现同一轨迹 —— 而"携带上一周期分解"本身就是一个平凡状态。
> 因此真正的判据不是"有没有差异"，而是"**无状态方案能否复现**"。

---

## 5. Cheap-knockout：退化场景设计与结果

**设计原则**：故意制造**多个目标值完全相同的最优解**，使来源分解**不被目标函数确定**。

### 5.1 两个场景

| 场景 | `C_firm` | `C_cond(t)` | 服务（demand / firm 支撑 / cond 支撑） | 承诺时刻并列最优分解数 |
|---|---|---|---|---|
| **S1** 单次撤回·对称 | 100 kW | `[100, 0, 100]` | A critical 80 / 80f / 0c；B deferrable 80 / 0f / 80c | **2 901** |
| **S2** 混合支撑·两周期 episode | 100 kW | `[100, 0, 0, 100]` | A 50 / 50f / 0c；B 80 / **50f / 30c**；C 20 / 0f / 20c | **51 541** |

S2 的 B 是**同一服务被两个保障等级混合支撑** —— 这正是 H-A5 唯一可能有别于"优先级"的情形。

### 5.2 结果（`results/raw/ha5_knockout/`，可复跑）

**S1 —— 轨迹（各周期各服务实际功率，kW）**

| 策略 | P1 | P2 (`C_cond=0`) | P3 |
|---|---|---|---|
| B5-proportional | [80, 80] | **[50, 50]** | [80, 80] |
| B5-identity_order | [80, 80] | [80, 20] | [80, 80] |
| B6-parametrized | [80, 80] | [80, 20] | [80, 80] |
| **H-A5-state** | [80, 80] | [80, 20] | [80, 80] |

**S2 —— 轨迹**

| 策略 | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| B5-proportional | [50, 80, 20] | **[33, 53, 13]** | **[33, 53, 13]** | [50, 80, 20] |
| B5-identity_order | [50, 80, 20] | [50, 50, 0] | [50, 50, 0] | [50, 80, 20] |
| B6-parametrized | [50, 80, 20] | [50, 50, 0] | [50, 50, 0] | [50, 80, 20] |
| **H-A5-state** | [50, 80, 20] | [50, 50, 0] | [50, 50, 0] | [50, 80, 20] |

**指标**

| 指标 | S1 | S2 |
|---|---|---|
| `N_provenance_flip` | 2 | 0 |
| `E_wrong_invalidation`（削减到低于 firm 支撑份额的电量，kWh） | B5-prop **30**；其余 **0** | B5-prop **34**；其余 **0** |
| `N_commitment_reversal` | B5-prop 2；其余 1 | 全 0 |
| `T_recovery_inconsistency` | 全 0 | 全 0 |
| 轨迹最大偏差 vs H-A5（kW） | B5-prop **30**；identity_order / B6 **0** | B5-prop **17**；identity_order / B6 **0** |
| **与 H-A5 轨迹逐点相同者** | `identity_order`, `B6-parametrized` | `identity_order`, `B6-parametrized` |

### 5.3 怎么读这张表（本节是 V0.2 的核心）

1. **"provenance 影响轨迹"是成立的** —— 相对 B5-proportional，
   H-A5 的轨迹最大差 30 kW（S1）/ 17 kW（S2），且 B5-proportional 把不可中断的 A
   **削减到低于其 firm 支撑份额**（S1 30 kWh、S2 34 kWh 错误作废）。
   所以这**不是**"完全一样的 P_i(t)、只是记账不同"的情形。

2. **但 H-A5 在任何场景都没有跑赢普通基线** ——
   一个**完全无状态**的逐周期规则 `B5-identity_order`（按服务顺序优先）
   与 H-A5 **逐点相同**，且 `E_wrong_invalidation = 0`。
   B6-parametrized（携带上周期分解）同样逐点相同。

3. **根因（这是本轮最值钱的结论）**：
   在"多个服务各自独立"的结构下，
   **"按容量来源作废" 与 "按服务优先级作废" 是同一个策略的两种叫法**。
   要使命题不等价，必须满足"同一服务被两个等级混合支撑、且混合比例随周期的变化方向
   不可由任何固定优先级序表达"—— 而一旦需要固定优先级序**随历史变化**，
   该优先级序本身就成了状态；于是又绕回"状态"，不构成新对象。

4. **因此**：`H-A5 → NO RESIDUAL TECHNICAL GAP`。按用户生死门口径，
   **不应**继续把它包装成技术机制。

### 5.4 Family A 的 reopen 条件（**登记保留，本轮不投入资源**）

本判定基于 S1/S2 两个退化场景。Family A **不是"死掉"**，而是
「当前建模假设下没有剩余技术机制值得继续投入」。只有在出现**下列任一类新证据**时才重开：

```text
① 服务之间存在真实的物理耦合 / 非可替代资源路径，
   使「按服务优先级」无法等价代替 provenance；
② firm / conditional 容量并非同一 PCC 上可任意互换的标量，
   而与设备拓扑、馈线、相别、变流器或时间连续性绑定；
③ provenance 的持续状态会导致 stateless baseline 无法复现的实际控制轨迹差异；
④ 执行反馈改变后续物理可行域，而不只是改变合同 / 账本状态。
```

> 本轮的三个更机械的证伪句柄（可作为上述条件 ①③ 的检验入口，**不投资源**）：
> **R1** 存在"同一服务混合支撑、且混合比例随周期改变的方向不可由固定优先级序表达"的更一般场景；
> **R2** 被释放的 cond 容量重新分配给**另一**服务后产生义务**血缘（lineage）**，
> 使义务无法归属到任一服务自身的累计计数器（即 §3.1 的 $\Gamma_j$ 不完备）；
> **R3** 所需控制动作依赖**事件序列**（order-dependent），而不只是当前总量。
>
> **本轮明确决定：R1/R2/R3 不投检索、不做仿真。** 初判：即使成立，也只是把状态从"分解"升级为
> "血缘台账"，仍需过 §6 的 Q1（物理资源/控制许可 vs 合同字段），通过概率不高。

---

## 6. 技术性四问（去掉状态后普通 MPC 是否出现可复现错误动作）

形式检查：

$$
\text{technical object}\;\rightarrow\;\text{state}\;\rightarrow\;\text{trigger}\;\rightarrow\;\text{transition}\;\rightarrow\;\text{control consequence}\;\rightarrow\;\text{feedback}
$$

| # | 问题 | 本轮判定 | 依据 |
|---|---|---|---|
| **Q1** | 状态是否对应**物理资源 / 控制许可**，而不只是合同字段？ | **NO**（偏记账） | `q^firm / q^cond` 记的是"承诺的资金来源"，是**分配记账**；真正的物理约束是 `Σx ≤ C_firm + C_cond(t)` |
| **Q2** | 状态变化是否**直接改变控制器可执行动作集合**？ | **NO / 已被优先序覆盖** | 削减**总量**由物理容量决定；削减**对象**的选择在 B5-identity_order 里由静态优先序决定，不构成新的许可集合 |
| **Q3** | **执行反馈**是否会修改该状态并影响后续控制？ | **NO**（且已被现有技术占据） | knockout 中 `recover` 由 `C_cond` 回升触发，**不是执行偏差触发**；而"被执行反馈修改的持久状态"已被 WO2024105191A1 **权 8/24/31** 占据 |
| **Q4** | 去掉该状态后，普通 MPC 是否出现**可复现的错误动作**，而不只是解释性变差？ | **NO** | B5-identity_order 去掉状态后轨迹**逐点相同**，`E_wrong_invalidation = 0` |

**四问全为不利。** 六段链中 `state` 与 `feedback` 两段无法成立 → **不注册候选。**

---

## 7. 状态词表（本轮统一口径）

| 词条 | 含义 |
|---|---|
`RELATED PRIOR ART` | 同一场景/同一物理量的现有技术，但不触及本假设对象
`HIGH PRESSURE` | 触及本假设的大部分要素，需在答审中构造区别
`STRUCTURALLY DIFFERENT` | 技术对象/触发源/状态迁移机制存在可陈述差别
`RESIDUAL GAP EXISTS` | 存在**无法被普通基线复现**的残余机制（本轮无一假设达到）
`NO RESIDUAL TECHNICAL GAP` | 命题真实，但可被普通 MILP/MPC/优先序完全表达 → 不成机制
`STOP THIS MECHANISM` | 该机制版（含 generic 版）应停止推进

**本轮判定分布**：`STOP THIS MECHANISM` ×2（H-A1、H-A4 generic）、
`HIGH PRESSURE` ×1（H-A2）、`NO RESIDUAL TECHNICAL GAP` ×2（H-A3、H-A5）、
`RESIDUAL GAP EXISTS` ×0。

---

## 8. "未答即停"门槛（Family A 若再启动，须先满足）

```text
G1  必须给出一个无法被 B0–B6 任一基线逐点复现的轨迹差异
G2  该差异必须源于「状态/来源」，而不是优先级、权重或目标函数
G3  该状态必须对应物理资源或控制许可，其变化必须改变控制器可执行动作集合
G4  执行反馈必须修改该状态并影响后续控制，且须区别于 WO2024105191A1 权 8/24/31
G5  去掉该状态后，普通 MPC 必须出现「可复现的错误动作」，而非仅解释性变差
────────────────────────────────────────────────────────────
任一不成立 → STOP。不进入权利要求草案。
```

---

## 9. 当前证据等级

| 材料 | 等级 | 说明 |
|---|---|---|
| US20250326322A1 / WO2024105191A1 / US12165224B2 / CN111098724B | **权项级（claim-level）** | 4 件权项全文留痕于 `_raw_audit_familyA_2026-09-17/` |
| US20250326322A1 权 10/22/36/49 的容量下降成因 | **说明书级待核** | 本轮未做说明书逐段核验 |
| WO2024105191A1 的"电网削减 power demand limit" | **说明书级（非权项级）** | 只在扰动列表，**未入权项**；引用时不得与权项级结论混列 |
| US10723230B2（容量阈值判可否服务后生成预约） | **二级（未核）** | 仅支撑 H-A1 的 generic KILL；该 KILL 现由 US20250326322A1 权项级**独立**支撑，结论不依赖它 |
| US10214115B2（EVSE power sharing 容量降/恢复） | **二级（未核）** | 仅支撑 H-A4 的 generic KILL；该 KILL 现由 CN111098724B 权 1 权项级**独立**支撑 |
| US8521337B1（firm/non-firm/二者可选） | **二级（未核）** | 作为"不得申请分等级本身"的禁区登记；**未核不影响本轮判定** |
| PG&E Flex Connect 接口（firm floor vs dynamic schedule / 通信丢失 900 s 退回 / 30 s 退回） | **一手（V1 已核）** | 官方 PDF + CPUC 正式回复 |
| 本轮 cheap-knockout | **合成退化 LP，机制可行性限定** | **不是**收益量化、**不是**部署证据；不得用于 A 轨 R5 7/7 |

---

## 10. 下一步（2026-09-17 已定）

```text
Family A（1+7+8）  → DOWNGRADED / NO CURRENT RESIDUAL TECHNICAL GAP
                     保留为 Problem-Reality 记录，不再投入检索/仿真资源
                     reopen 仅凭 §5.4 的四类新结构/物理证据
                     ❗ R1/R2/R3 暂不做（已决定）

Family B（6）      → SCOUT（轻量）。只回答一个问题：
                     同一 PCS/BESS/EVSE 的 S_rated / I_rated
                     在有功服务与无功/谐波/不平衡治理之间的容量竞争，
                     是否存在超出常规 P²+Q² ≤ S²、三相 OPF/MPC 的**结构性技术矛盾**
                     先不写算法、不找数据、不做仿真；仍按同一方法攻击
                     结果见 P0_Family_B_Scout_V0.1.md

数据线（3-b）      → 不扩张。只有某个机制先通过 G1–G5，才去问"哪个公开数据能验证它"
专利候选           → 仍无编号。本轮不注册任何候选
入口               → 待 Family B scout 第一轮结果出来后**一次性建立**（见 §11）
```

> **方法论收获（本轮最值得保留的一条）**：真正杀掉 H-A5 的**不是 prior art，而是更强的简单基线**。
> 这与 R3-A / R3-C 的失败是同一种高质量证伪方式。以后继续坚持：
> $$\boxed{\text{先找能否被更简单机制等价复现，再谈专利差异}}$$

---

## 11. 治理声明

- 本轮**未**改动 A/C 第一波申请文本、A-EV/HIL 代码与结论、既有治理文件。
- 本轮**未**启动任何真实数据实验，**未**扩 prior-art 检索面（只核 V1/二审已点名的 4 件）。
- 4 件文献结论**只用于探索轨**，**不得**作为 A/C 申请文本的支持或证据。
- 本轮 knock-out 为**合成退化 LP**，仅用于机制可行性判定，**不得**引用其数值作为收益/效果证据。
- `core-patent = NO-GO`、`Round 5 = NOT STARTED`、`A-M3–M6 = UNVALIDATED` **不变**。
- V1（`P0_…_Problem_Reality_Audit_V1.md`）作为**历史 Problem Reality Audit 不删除**；
  其 §5.3 的"四条残余假设"与 §8.1 的"进入下一阶段最低门"由本文件**supersede 其"当前判断"部分**。
- V0.2 自身的 §0 / §5.4 / §10 于 2026-09-17 按用户裁定**定稿**为
  `Family A = DOWNGRADED / NO CURRENT RESIDUAL TECHNICAL GAP`，
  并确认 AGENTS.md 入口**延后**至 Family B scout 首轮结果之后统一建立。
