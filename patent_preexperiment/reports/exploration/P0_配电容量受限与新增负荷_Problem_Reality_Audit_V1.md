# P0「配电容量受限 × 新增电气化负荷」Problem Reality Audit V1

> **定稿日期**：2026-09-17  
> **性质**：探索轨 3-a。目标是判断 3-b 提出的 8 类技术矛盾是否属于行业公共问题、现有系统已解决到什么程度、哪些只能作为约束/压力场景、哪些值得进入第二层探索。  
> **不是**：专利候选注册、完整 prior-art 检索、专利新颖性/创造性结论、R5 启动。  
> **纪律**：先证伪问题，再找机制；强简单基线优先；行业现实与专利边界分别核验；不因有数据而造问题，也不因暂时没有公开数据而杀掉真实公共问题。  
> **前置数据审计**：`数据源准入审计_V1.md`。本报告不改变 `core-patent=NO-GO / Round 5=NOT STARTED / A-M3–M6=UNVALIDATED`。

---

## 0. 本轮结论

8 个问题不应并行深挖。首轮现实审计后，收敛为两个问题族；其余 4 类降为 baseline / constraint / stress。

| # | 原始问题假设 | 行业现实 | 现有技术压力 | 本轮处置 |
|---|---|---|---|---|
| 1 | 规划接入容量与运行实际容量不一致 | **强** | dynamic hosting capacity / flexible connection 已成熟 | **KEEP AS PARENT**，但“动态容量计算”本身不做 |
| 2 | 新增 EV/生产任务的服务保证与容量限制冲突 | **强** | managed charging 已覆盖任务时刻、SOC、建筑负荷、设备容量、departure | **DOWNGRADE**；普通服务保证不独立做 |
| 3 | 储能功率够、能量持续性不够导致接入虚高 | 真实物理约束 | 已知 SOC/容量/Pmax 后可直接形成能量约束 | **KILL-AS-INDEPENDENT**；只作硬约束 |
| 4 | PV/BESS/EV 共存导致静态 hosting capacity 失真 | **强** | dynamic/time-series/probabilistic HC + 主动管理已有直接专利覆盖 | **DOWNGRADE**；generic dynamic HC 不做 |
| 5 | 正常日可承载，极端日/连续低光照/高并发失效 | **强** | robust/stochastic/chance-constrained 属成熟工具链 | **STRESS ONLY** |
| 6 | kW 尚有余量，但 V/Q/谐波/不平衡等先成为瓶颈 | **强，物理性强** | 多维 HC 已有较强基础；但变流器容量竞争仍待审 | **KEEP → Family B** |
| 7 | 为少数最坏小时永久扩容，与允许受控降级之间的矛盾 | **极强** | flexible/non-firm connection 已进入实际运营 | **KEEP → Family A**；“Flex Connect 本身”不做 |
| 8 | 电网外部容量边界与园区内部不可中断/可延迟/储能/EV 的一致分解 | **强** | 普通 EMS/MPC 分解成熟，但 utility/customer 接口仍存在结构空白 | **KEEP → Family A** |

```text
Family A（主线） = 1 + 7 + 8
  非刚性/非保证接入容量下的园区服务保障与受控降级

Family B（副线） = 6
  多维电气约束下的真实站级可承载能力与变流器容量竞争

2 / 3 / 4 / 5
  → baseline / constraint / stress scenario
```

这里的 KEEP / DOWNGRADE / KILL 是**探索资源配置结论**，不是法律上的可专利性结论。

---

## 1. 审计框架

每个问题按六问攻击：

1. 问题是否高频公共，而不是偶发事件？
2. 现有商用/行业系统已经实现了什么？
3. 最强普通方案是什么？——规则、managed charging、MILP/MPC、robust/stochastic 等必须作为强基线，而不是稻草人。
4. 若普通设备状态全部已知，问题是否仍存在？
5. 剩余矛盾是否来自新的结构接口，而不只是换目标函数/权重/算法？
6. 未来是否有可验证的实验路径？

沿用失败史约束：

```text
事件存在 != 运营量级足够
字段存在 != 语义成立 != 事件发生 != 因果可验证
弱 baseline 下的漂亮提升 != 新问题
预测/优化更复杂 != 新技术对象
```

---

## 2. 行业现实锚点：Flexible Service Connection 已经不是概念

### 2.1 中国政策层

国家《新型储能规模化建设专项行动方案（2025—2027年）》明确提出：

- 在**配电网扩建受限**或偏远地区推广电网替代型储能；
- 面向**工业园区、算力设施、商业综合体、光储充放一体化充电站**等场景创新应用；
- 推动智能微电网、源网荷储、虚拟电厂、车网互动等模式。

这只能证明问题具有政策与行业公共性，**不能**证明具体技术机制新颖。

一手来源：
- 国务院政策库附件：`https://www.gov.cn/zhengce/zhengceku/202509/P020250912411822546143.pdf`

### 2.2 PG&E Flex Connect：现实运行接口已经形成

PG&E 2026 Flex Connect 官方材料给出典型案例：客户申请 **2 MW** EV DC 快充负荷，因少数峰值小时的配网容量约束，传统路径全年只能给 **0.5 MW**；Flex Connect 让站点接入完整设备，由 PG&E DERMS 根据电网可用容量下发 scheduled / real-time capacity limits，站内自动调节负荷，多数时间可以使用完整 2 MW。

官方接口可概括为：

```text
Load Limit Letter / planning limit / firm limit
        ↓  保证的静态/规划下限
DERMS hourly dynamic schedule
        ↓  基于受限设备负荷预测的条件容量
Customer site EMS
        ↓  客户自己实现内部控制
PCC aggregated telemetry → PG&E
```

PG&E《Flex Connect Preliminary Load Analysis Report Overview》（2026-01）明确：

- dynamic capacity 是 best estimate，**不是 guaranteed energy**；
- **唯一保证量**是 Service Planning 建立的 load limit；
- Flex Connect 不会把客户削减到该 load limit 以下，它构成 guaranteed floor。

PG&E《Technical Requirements for Telemetry and Control》（2026-01）明确：

- planning/static/firm limit 来源于 Load Limit Letter；
- DERMS 给站点下发小时级 dynamic schedule；
- PCC 遥测是**站级聚合负荷**，包含 flexible 与 non-flexible load；
- schedule 包含 start time / duration / Max Watt Absorb Limit；
- 通信连续丢失 900 s 时退回 planning limit；
- 紧急情况下 DERMS 可取消/修改动态 schedule，客户侧须在 30 s 内退回 planning limit；
- schedule 到站后，站内可以用合适的下游协议向 individual EVSE 分解。

PG&E 在 2025-06-13 向 CPUC 的正式回复进一步明确：

> Load Limit 作用于 customer point of interconnection；**站内采用什么过程去满足该限制，由客户自行决定**。

一手来源：
- `https://www.pge.com/flexconnect`
- `https://www.pge.com/fcloadanlys`
- `https://www.pge.com/fctechreq`
- `https://www.pge.com/fcprogfacts`
- `https://docs.cpuc.ca.gov/PublishedDocs/Efile/G000/M569/K525/569525911.PDF`

**现实结论**：

```text
“外部动态容量边界”已经是现实系统对象；
“站点收到边界以后内部怎么做”不是电网侧替客户解决的问题。
```

因此问题 1/7/8 的行业现实基础成立，但不能把“动态容量”“FSC”“接收限值并跟随”本身当作创新。

---

## 3. 两个直接禁止重复的现有技术边界

### 3.1 禁区 A：generic dynamic hosting capacity

US10873188B2（Opus One Solutions Energy Corp）权利要求 1 已明确覆盖：

- 三相 AC power flow；
- 多个 location；
- 多个 time interval；
- 多种 DER type；
- dynamic hosting capacity；
- hosting capacity → operational value；
- operational value → 主动管理 DER。

从属权进一步覆盖 stochastic/probabilistic engine、quasi-static time series、per-node/per-phase/DER-type、历史/预测/实时数据以及 dispatch schedule。

一手来源：`https://patents.google.com/patent/US10873188B2/en`

因此不得把以下内容当 P0 核心：

```text
按时间/位置/DER类型计算动态承载能力；
把动态承载能力用于调度/主动管理；
用概率/时序/三相潮流提高 hosting capacity 精度。
```

### 3.2 禁区 B：generic “时变供给上限 + 滚动优化 + 不确定性 + 资源预留”

CN120197914B《一种基于汽车充电需求的充电站规划方法和系统》（授权文本，`DC.date` = 2025-05-23，一手核验）已经组合出现：

```text
电网容量约束 + 新能源波动
→ 多时段供给能力评估 / 时变容量上限
→ 需求与供给匹配
→ 动态资源分配
→ 双目标优化
→ 滚动时域求解
→ 随机过程/场景模拟处理不确定性
→ 按风险调整资源预留比例
→ 韧性服务能力预测值
```

一手来源：`https://patents.google.com/patent/CN120197914B/zh`

因此“EV需求预测 + 时变容量上限 + rolling horizon + reserve”也不能作为 Family A 的核心差异。

> **边界说明（须与本节结论一并引用，防止把该文献范围放大）**
>
> 上述五项高压力特征**全部集中于授权文本的权利要求 7**（一手核验：五项关键词在 8 项权利要求中的命中项均为权 7；`随机过程` 另见权 1、`预留` 另见权 5，但完整组合仅权 7）。该权项**引用权 4**，权 4 引用权 3，权 3 引用权 2，权 2 引用权 1 —— 故权 7 的范围**同时带有上游限定**：
>
> ```text
> 权 1  时空充电需求图谱（多源数据融合）
>  → 权 2  站点布局优化（路网 + 多目标 + 粒子群 + 模糊层次分析）
>  → 权 3  电网承载能力评估 + 可再生能源 + 储能协同（多时间尺度调度 + 数字孪生）
>  → 权 4  实时定价 + 资源预分配 + 优先级预约 + 排队
>  → 权 7  时变容量上限 + 动态资源分配 + 滚动时域 + 随机情景 + 风险资源预留 → 韧性服务容量预测值
> ```
>
> 授权文本为 **8 项权利要求**（权 8 为**系统权**，用于实现权 1–7 任一方法），**非**申请公开 A 文本的项数。
>
> **因此本报告只判定：**「时变容量上限 + 动态资源分配 + 滚动时域优化 + 不确定性情景模拟 + 风险资源预留」这一**组合**本身**不是空白**；**不据此**认定其中任一**单独概念**、或在**不同技术对象**下的实现均被该专利覆盖。
>
> **对 Family A 的精确影响**：该专利可排除「需求预测 + 时变供给上限 + 滚动优化 + 随机情景 + 风险预留 → 输出服务容量预测值」的**普通路线**；但核到的权 1–8 **未**触及 `firm capacity ≠ conditional capacity` 的语义区分，也**未见**把「**已承诺服务在容量撤回/下调后的降级 → 履约状态 → 恢复**」作为**被更新技术对象**的披露。该专利是在**预测未来能服务多少并做预分配/预留**；与「语义已发生变化的容量如何回写已承诺服务状态」是两个不同对象，须严格区分。

> 本节只划明显禁止重复区，不是完整 FTO/novelty 检索。

---

## 4. 八类问题逐项 Problem Reality Audit

### 4.1 #1 规划接入容量 vs 运行实际容量

现实性强。PG&E 的 2 MW vs 0.5 MW 案例直接证明少数最坏小时可能决定全年静态接入容量。

但 generic 解法已成熟：dynamic hosting capacity、flexible/non-firm service、day-ahead dynamic schedule 都已经成为正式方案。

**结论：KEEP AS PARENT PROBLEM，不把 dynamic hosting capacity calculation 当 invention。**

### 4.2 #2 新增 EV/生产服务保证 vs 容量限制

DOE FEMP Smart Charge Management 已把以下内容作为常规能力：车辆 schedule/dwell、SOC、departure/vehicle readiness、building load、transformer capacity、utility/grid signal，以及按 available capacity 分配功率、设置 ceiling、按 departure time 排程。

一手来源：
- `https://www.energy.gov/cmei/femp/managed-ev-charging-federal-fleets`
- `https://www.energy.gov/cmei/femp/smart-charge-management-implementation-federal-fleets`

因此以下题目不能作为核心方向：

```text
考虑离场时间和变压器容量的有序充电
考虑 SOC / kWh request 的充电调度
保证车辆离场前充够，同时不超过站点容量
```

残余问题只能发生在 dispatch 之前或之外，例如 conditional capacity 可撤回时站点“能不能承诺服务”。

**结论：DOWNGRADE。**

### 4.3 #3 储能功率够，但能量持续性不够

若已知 `SOC, SOC_min/max, E_usable, Pmax, η`，则：

```text
E_available ≈ ΔSOC · E_usable · η
T ≈ E_available / P
```

这是确定性物理约束；在调度里加入 SOC/energy balance 即可。

**结论：KILL-AS-INDEPENDENT。** 只作为 Family A/B 的硬约束或实验变量。

### 4.4 #4 PV+BESS+EV 共存导致静态 hosting capacity 失真

现实性强，但 US10873188B2 已直接把 location × time interval × DER type × active management 写入权利要求体系。

禁止重新命名为：

```text
光储充多资源动态承载能力
考虑 PV/BESS/EV 时变特性的接入包络
基于预测的动态 hosting capacity
```

**结论：DOWNGRADE。** 外部动态容量只能作为输入边界。

### 4.5 #5 正常日可承载，极端日失效

PG&E Flex Connect load analysis 本身并列 Typical / Extreme loading scenario。

但算法结构通常属于 robust/stochastic/chance constraints/scenario MPC/reserve margin。

**结论：STRESS ONLY。**

### 4.6 #6 kW 有余量，但 V/Q/谐波/不平衡等先成为瓶颈

PG&E 的 CPUC 正式回复确认，容量评估不仅看设备容量，还检查 power flow、normal/emergency rating、protection setting、power quality；模型要避免 thermal、voltage、protection limits 被突破。

所以 `ΔP_nameplate > 0` 不推出 `ΔP_admissible > 0`。

但 generic “把 V/Q/三相潮流考虑进 hosting capacity”也不能做——US10873188B2 已覆盖三相 AC power flow、per-phase V/I/P/Q/power factor。

更窄的待证伪问题：

> 同一 PCS / charger / BESS converter 的有功服务能力与无功、谐波、不平衡治理会竞争同一 `S_rated / I_rated`；这种容量竞争怎样改变站级真实可服务能力？

**结论：KEEP → Family B。**

### 4.7 #7 为少数最坏小时永久扩容 vs 允许受控降级

现实性极强，但“动态限功率从而推迟扩网”已经不是新问题。

现实结构是：

```text
P_firm = planning/static limit，保证 floor
P_cond(t) = dynamic schedule / 条件可用容量，不保证
```

通信失效、紧急取消时必须回到 planning limit。

因此 Family A 不能研究“接收动态限值并跟随”，而应继续追问：

```text
当站点利用 conditional capacity 承担内部服务后，
conditional capacity 被撤回/下调时，
之前作出的服务安排如何受控退化？
```

**结论：KEEP → Family A。**

### 4.8 #8 外部容量边界如何在园区内部一致分解

PG&E/CPUC 一手材料明确：Load Limit 作用于 POI/PCC；电网只要求 PCC 聚合遥测和总容量合规；schedule 在站级下发；站内下游分解由客户实现；客户设施内部采用什么 process，由客户自行决定。

因此确实存在：

```text
utility-side capacity envelope
             ↓
        POI / PCC
             ↓
customer-side mixed services / resources
```

但“给一个站级 P_limit(t)，再用 MILP/MPC 分给设备”仍是普通 EMS。

下一层真正要证伪的是：

```text
容量边界有不同“保证等级”时，
园区内部的服务承诺、准入、降级和恢复
是否需要区别于普通 dispatch 的状态/机制？
```

**结论：KEEP → Family A。**

---

## 5. Family A：非刚性接入容量下的园区服务保障

### 5.1 已被现实系统确认的输入对象

```text
C_ext(t) = {
  C_firm(t),
  C_cond(t),
  validity_window,
  event_status,
  fallback_rule
}
```

Family A 不研究如何算 dynamic hosting capacity，而把它当输入。

### 5.2 普通 EMS 基线

```text
B0 firm-only：永远只用 C_firm
B1 dynamic-follow：直接把 dynamic schedule 当 P_PCC 上限
B2 deterministic MILP/MPC：联合 EV/BESS/PV/负荷优化
B3 robust/stochastic MPC：对 C_cond 下调及负荷/PV/EV 不确定性建模
B4 managed charging：按 deadline / kWh request / SOC / priority 调度
```

若新方案只是权重不同、场景更多、预测更准，则停止。

### 5.3 第二层待证伪的四个残余假设

#### H-A1：Service Admission ≠ Dispatch

先判断“该服务能不能被承诺”，再决定“已承诺服务怎么 dispatch”。

需验证在 `C_firm + C_cond` 两层容量语义下，admission 是否有独立技术必要性。

**反证压力**：CN120197914B 已包含时变供给上限、服务能力预测、资源预留和不确定性处理。若 H-A1 只是换个词叫 admission，应淘汰。

#### H-A2：Committed Service 在 dynamic capacity 撤回后的受控退化

当 `C_cond(t): high → low / canceled`，普通 dispatch 可以重优化，但现实中可能已有生产连续性要求、车辆 departure/kWh 任务、充电服务 SLA、备用 SOC 要求。

待验证问题不是“设优先级”，而是**已接受服务义务如何转换为可审计的降级结果，同时保证 PCC 回到 C_firm**。

#### H-A3：Aggregate Compliance 与内部服务结果之间的状态缺口

可能存在：

```text
PCC 合规
!=
内部每类服务仍满足原承诺
```

如果普通 MPC 的 constraint + objective 足以表达且无新状态对象，则淘汰。

#### H-A4：Fallback → Recovery 的业务连续性

PG&E 规定通信丢失或 schedule 取消时退回 planning limit；恢复后采用最新 schedule。

但客户内部任务的承诺冻结/降级/补偿/恢复顺序并未由电网侧规定。

需验证这是否只是 receding-horizon reoptimization；若是，淘汰。只有发现**跨事务仍必须保留的技术状态**才继续。

### 5.4 当前禁止提前使用的表述

- 新的动态接入容量算法；
- 新的 flexibility envelope；
- 预测站点未来可用容量；
- 基于 MILP/MPC 的多资源分配方法；
- 按优先级削减负荷；
- 考虑 EV 离场时间的充电优化；
- 引入鲁棒/随机优化提升极端情况下可靠性；
- 通过储能补足动态容量不足。

---

## 6. Family B：多维电气约束下的真实站级可承载能力

暂时只保留：

```text
有功服务 P
↔ 无功 Q
↔ 谐波/不平衡补偿
↔ converter apparent-power/current limit
```

普通 hosting capacity 已考虑 V/Q/三相潮流，不能以“多维 hosting capacity”作为创新描述。

第二层重点审：

1. BESS/PCS/EVSE 是否现实承担兼具 P 与 Q/电能质量调节的角色；
2. `S_rated / I_rated` 容量竞争是否已有标准分配机制；
3. 电能质量治理动作是否动态压缩 EV/BESS 有功服务能力；
4. 是否需要新状态/控制闭环，还是简单 `P²+Q²≤S²` / OPF 即可解决。

若只是 `P² + Q² ≤ S_rated²` 或常规 OPF，则停止。

---

## 7. 实验影子

### 7.1 Family A

```text
真实建筑/园区负荷背景（工业数据仍待补）
+ ACN 真实 EV session / power response
+ SOFIE 真实共址 PV+BESS+EV 行为锚点
+ BESS 物理模型
+ PG&E-style C_firm + C_cond(t) 工程场景
```

若没有公开 PG&E 真实 dynamic schedule 历史，则 `C_firm/C_cond` 只能标为 **ENGINEERING / SCENARIO input**。

指标：PCC violation、firm-floor fallback compliance、accepted-service violation、unserved/delayed EV energy、conditional-capacity utilization、BESS throughput、schedule cancellation 后 recovery time 等。

### 7.2 Family B

PowerFactory/PSCAD → controller-in-loop/HIL → 真实站。

基线：只按 kW headroom、常规 P/Q apparent-power constraint、OPF/three-phase OPF、候选新机制。

---

## 8. 下一步门

### 8.1 主线优先：Family A 第二层 Reality/Prior-art Attack

下一轮只回答：

```text
utility 下发 firm + conditional site envelope 后，
客户侧现有 EMS / charging management platforms 已经把
admission → commitment → degradation → recovery
做到什么程度？
```

优先检索：flexible/non-firm connection 客户侧控制产品与试点、EV charging reservation/admission control、service commitment under uncertain grid capacity、microgrid/fleet service degradation & recovery、behind-the-meter EMS 对 dynamic operating envelope 的分解，以及“firm/non-firm capacity 分层 + 已承诺任务”相关专利。

**进入下一阶段的最低门**：至少找到一个无法被 B0–B4 普通基线直接消化、且具备“新技术对象 + 触发条件 + 状态转移/控制后果 + 反馈”的残余机制。

### 8.2 Family B 暂不抢资源

只做轻量 prior-art/产品能力扫描。除非证明存在超出常规 `P/Q/OPF` 的结构缺口，否则不启动数据/仿真工程。

---

## 9. 当前冻结口径

```text
3-b 数据源准入审计第一轮 = CLOSED
3-a Problem Reality Audit V1 = 本文件

P0-Family A = KEEP FOR SECOND-LEVEL ATTACK
P0-Family B = KEEP AS SECONDARY SCOUT

#2 / #3 / #4 / #5 不作为独立主方向
尚无新专利候选编号
尚无 GO 结论
```

本文件只属于公共问题探索轨，与 A/C 第一波专利文本、A-EV/HIL 证据线相互独立。
