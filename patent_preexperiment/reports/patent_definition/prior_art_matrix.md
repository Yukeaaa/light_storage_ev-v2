# 现有技术检索矩阵（Patent Definition Phase 1 + Patent Gate 2，含检索后 FINAL 判定）

> **⚠ HISTORICAL（v2）— 不再作为当前权威。**
> **CURRENT CORE-PATENT AUTHORITY = CORE-SEARCH 决策链**；`02_prior_art_element_map_v3_e7_fast.md`
> 仅为 E7-FAST/M2 历史候选包要素对照（VALID MODULE / HOLD）。
> 本文件攻击的是"信息分类+history boundary+recovery"，recovery 已删除，靶子已变。
> 代理师请以 v3 element map 为准。

> 依据：审查结论52 §八/§九 补检索 + P0 杀伤性初筛（`results/raw/P0/P0_patent_kill_screen.md`）
> + P1 Patent Gate NO-GO（`results/raw/phase3_p1/P1_patent_gate.md`）。
> 本矩阵是**技术筛选**，非正式新颖性/创造性/FTO 法律意见；最终申请前需专利代理师做
> 完整法律检索与权利要求判断。
> **Phase 1 的检索靶子（recent_var 状态判定器）已被 P1 formal 否掉**；§5 冻结
> Patent Gate 2 的新检索对象与排除项，见 `claim_tree.md` §5。

## 1. 检索目标（最重点攻击的组合）

> **响应证据支持状态 → 短时功率边界生成模式选择 → EMS 控制权限切换 → 保护降级/响应恢复**

即审查结论52 认定的唯一可主张空间：这些**已有要素之间的新技术关系组合**。

## 2. 检索矩阵

| 专利/文献 | 申请人 | 核心触发 | 覆盖本发明的哪一步 | 与本发明的技术关系差异 | 风险等级（对主权利要求） | 区分对策 |
|---|---|---|---|---|---|---|
| US12054065B2 | Porsche | 充电站/负载管理**系统故障** → dynamic/static load-management 模式切换 | 模式切换（fallback）概念 | 触发是系统/站故障状态，**不是车辆实际响应行为/响应证据支持状态**；不联动车辆短时执行边界 + EMS 对车辆预算的控制权限 | 中（仅概念层） | 明确 trigger = 车辆实际充电响应及其历史证据状态/信息可用状态 |
| US10464435B2 | ChargePoint | 基于**近期供电历史**响应 power-limit message | 历史功率 → 下周期上限（第 4 步局部） | 无"响应证据支持状态 → 边界模式选择 → 控制权限"链条；仅是单桩对 power-limit 的响应策略 | 中 | 锚定支持状态→权限切换的耦合，不单独主张"历史功率设限" |
| US10150380B2（及族 US11813959B2/US12157387B2/US12221010B2） | ChargePoint | allocated power 超过车辆请求/支持能力时释放多余 power modules 给其他 dispenser | 差值回收/重分配（非主权利要求） | "释放未用功率给他车"已被充分覆盖；是价值/应用主张，非创新点 | 高（仅限重分配主张） | 重分配降为场站级从属/价值主张；主权利要求不依赖回收动作 |
| CN112829627A | — | 按车辆实际需求动态重分配多车功率 | 多车动态分配 | 同样只覆盖重分配，无响应证据支持状态/控制权限 | 高（仅限重分配主张） | 同上 |
| US9290104B2 | — | 改变 pilot duty-cycle 前后读取功率、测量车辆响应 | "pilot 阶跃→测量响应" | 仅测量手段公开，无"由测量结果形成支持状态→切换边界→切换权限" | 低-中 | 不主张"调 pilot 控功率"；pilot 仅作为输入之一 |
| US20240343147（GM，充电限流/taper 检测） | GM | 充电限流检测 | — | 针对 taper/限流现象识别，不涉及边界模式选择与控制权限 | 低 | — |
| US20250145043A1（多端口自适应功率管理） | — | 通用动态负载管理 | — | 调度/分配层，无桩侧响应证据状态 | 低 | — |
| US20130346025A1 / WO2025/078176（EVSE pilot–响应差异） | — | 协议合规/占用检测 | — | 用途不同（合规/占用），未见"pilot 阶跃 vs 实际电流持续偏差 → 可执行边界"布局 | 低 | — |
| US12165224B2 | — | 模型适用域/回退（侧重调度/预约） | fallback 概念 | 侧重预约/调度可信度，桩侧观测比对空 | 中（概念层） | 场景锚定 EVSE/CSMS 桩侧在线观测 |
| WO2026/003612（目标充电电流方法） | — | 目标充电电流 | — | 电流目标设定，非响应证据状态 | 低 | — |

## 3. 判定结论

1. **不能单独成主权利要求的要素**（近邻已充分覆盖）：历史功率→下周期上限、
   actual<pilot→回收差值、车辆需求小→给别人、改变 pilot→测量响应、fallback mode。
2. **相对可主张的组合**：响应证据支持状态（由在线实际响应历史形成）→ 边界生成模式
   （随信息可用性分支）→ EMS 控制权限切换 → 保护降级/响应恢复。该组合在检索到的
   近邻中**未见完整同构组合**，与 P0 杀伤性初筛结论一致（"完整步骤组合……未见完整同构"）。
3. **最大侵权/无效风险来源**：Porsche（fallback 概念）+ ChargePoint（历史功率驱动设限）
   的**组合拆解**——检索与撰写阶段必须证明二者未公开/未暗示"由车辆实际响应证据状态
   驱动的边界选择与控制权限联动"。

## 4. 正式检索策略（E8 / 法律检索前）

- 关键词族：charging response / pilot / allowed current / actual power / variance /
  execution capability / power budget control authority / fallback protective mode /
  EVSE observable；中/欧专利库（CNIPA / EPO）并行。
- 对比重点：Porsche US12054065B2、ChargePoint US10464435B2/US10150380B2 的分级引证
  （citation network）与在后改进（continuation）文献。
- NPL：EVSE 功率分配、ISO 15118 / DIN SPEC 70121 动态功率限制相关标准演进、
  ACN 相关论文（响应差异观察）作为背景文献建档。
- 产出：每篇近邻的 claim 要素对照表（element-mapping），作为权利要求撰写与
  答复审查意见的基础。
- 结论前不做 FTO 判断；最终以专利代理师出具的法律意见为准。

## 5. Patent Gate 2 — 剩余发明核 prior-art stress test（检索前基线）

> 检索对象、分层判断与排除项在 `claim_tree.md` §5 冻结（本矩阵 §1-3 的旧靶子——响应
> 证据支持状态→边界→权限——已因 P1 No-Go 失效，仅作背景保留）。

**检索对象（四类组合，逐类查单模块已知度，再查 A+B+C+D 闭环是否已被公开）**：

```text
A  信息可用性 → 控制/模型模式选择
B  actual/history → EV capability/power boundary
C  信息或历史不足 → protective/conservative fallback
D  后续实际响应 → constraint relaxation / permission recovery
```

**两层判断**：

1. 单模块（A/B/C/D）是否已知；
2. **组合关系是否显而易见 / 已明确公开**——尤其 A+B+C+D 是否已被串成闭环
   （"按信息质量选能力模型 → 历史不足保守模式 → 后续响应恢复"）。

**判定出口**：

- 组合未被清楚公开 → **Protective GO**（P2：验证 current-only history protective
  boundary 实施例技术成立）；
- 组合有类似方案但边界应用模式/约束等级/recovery trigger 有区别 → **Narrow
  Conditional GO**（收窄范围后决定 P2）；
- 组合已被充分公开（车辆信息不足→history estimate→保守约束→新观测→放宽约束）→
  **Project No-Go**，禁止用 risk score / 双模型 / classifier 等制造复杂度硬撑。

**重点追踪对象**：保护性降级 + 权限恢复是否已被类似关系公开；`historical limit` /
`fallback control` / `mode switching` / `confidence-based control` /
`dynamic charging constraint` 族。

## 6. Patent Gate 2 — FINAL 判定：NARROW CONDITIONAL GO / HOLD P2（检索后）

> 完整判定与证据链见 `results/raw/patent_gate2/patent_gate2_final.md`（FINAL 记录）。
> 本节为矩阵更新，冻结检索后结论，替代 §5 的开放基线。

**单模块已知度（两轮检索确认，A/B/C/D 全部高拥挤）**：

| 模块 | 代表文献 | 已公开内容 |
|---|---|---|
| A | US20150077054A1；US20250196694A1 | 信息可用性→模式/控制选择 |
| B | ChargePoint 族（US20140103866A1/US10953760/US11718191/US9656567B2/WO2013138781A1）；US20210268929A1；US9685798B2；**ACN 族（US10926659/US20200254896A1）** | actual/history→能力/功率边界（含直接限桩口、限设定值、在线 LP 约束） |
| C | US11046205B1；US12054065B2；ACN 族（保守约束由观测推导） | 信息不足→保守/保护性处理 |
| D | US20250196694A1（通信恢复）；US10214115B2（停充恢复）；EP4235909/US7489108B2（电池内部限值恢复） | 后续条件→恢复（恢复对象均为通信/电流/停充/电池内部，**非调度器权限**） |

**两条防线纵深攻击（本轮）**：

- 防线 1（boundary→调度动作权限约束，非直接设定值）：未命中。部分覆盖为 ChargePoint
  直接限桩口功率、US12393888B2 静态规格 boundary 作 optimizer 约束、ACN 族 per-EV max
  rate 作在线 LP 约束（同数据集，**风险最高近邻**）。
- 防线 2（实测响应→恢复调度权限）：未命中。恢复类文献恢复对象均为通信/电流设定值/停充/
  电池内部限值；ACN 族是可行性驱动的约束放松，非响应证据驱动的权限恢复。

**FINAL 判定**：

```text
判定       NARROW CONDITIONAL GO / HOLD P2 →（P2 后）P2 = SUCCESS / NARROW GO
条件       P2 必须落地 D1/D2/D3（信息类别分级选择边界方式 / 边界应用为调度动作允许范围而非
           直接设限 / 保护性降级 + 实测响应驱动恢复权限），否则降级 Project No-Go
主风险     ACN 族（US10926659/US20200254896A1）—— 观测→保守约束→在线调度约束→可行性放松
规避锚     D1 信息类别分级、D2 权限约束 vs 直接设限、D3 响应驱动权限恢复（技术化、可落设备动作）
P2 验证    D1/D2/D3 均已落设备动作并通过（M1=1.0/M2=1.0/M4=0.0/M3 natural 1,060 会话）；
           CLAIM 1 v2 设备动作链 + ACN element-by-element 对照见 claim_tree.md §7
法律前置   ACN 族 element-mapping + EP/CNIPA 库 + ISO 15118 动态功率限制标准演进（专利代理师）
```
