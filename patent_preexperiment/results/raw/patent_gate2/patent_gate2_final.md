# Patent Gate 2 — 剩余发明核 prior-art stress test：FINAL 判定 = NARROW CONDITIONAL GO / HOLD P2

> 日期：2026-08-11
> 依据：两轮定向 adversarial 检索（用户亲自首轮 A/B/C/D 初判 + 本轮防线 1/防线 2 纵深攻击）。
> 本判定是**技术筛选结论，非正式新颖性/创造性/FTO 法律意见**；最终申请前必须由专利代理师
> 出具完整法律检索与权利要求意见（见 §7 残余风险）。
> 检索前基线冻结于 `prior_art_matrix.md` §5 与 `claim_tree.md` §5；`P1_patent_gate.md` §5
> 为剩余发明核的原始表述。

## 1. 检索对象回顾（A+B+C+D 闭环，未变动）

```text
A  信息可用性 → 控制/模型模式选择
B  actual/history → EV capability/power boundary
C  信息或历史不足 → protective/conservative fallback
D  后续实际响应 → constraint relaxation / permission recovery
```

**判定标准（冻结，见 `prior_art_matrix.md` §5）**：

- 组合已被充分公开 → **Project No-Go**；
- 组合有类似方案但边界应用模式/约束等级/recovery trigger 有区别 → **Narrow Conditional GO**；
- 组合未被清楚公开 → **Protective GO**。

## 2. 单模块已知度（两轮检索一致确认：A/B/C/D 全部高拥挤）

| 模块 | 代表文献 | 已公开内容 |
|---|---|---|
| A | US20150077054A1（Honda，通信失败→历史数据控制）；US20250196694A1（Hyundai/Kia，通信异常→降电流→通信恢复→恢复） | "信息可用性 → 模式/控制选择"概念充分公开 |
| B | US20140103866A1 / US10953760 / US11718191 / US9656567B2 / WO2013138781A1（ChargePoint，recent history→port power limit）；US20210268929A1（history→max allowed charging power→profile）；US9685798B2（current sensor→feedback→pilot 调整） | "实际/历史 → 能力/功率边界"充分公开；**含直接限桩口功率与直接限设定值** |
| C | US11046205B1（SOC 不可得→历史估算）；US12054065B2（Porsche，故障→fallback 模式切换）；US10926659（ACN，保守约束可由观测推导） | "信息不足→保守/保护性处理"充分公开 |
| D | US20250196694A1（通信恢复→恢复电流）；US10214115B2（停止后恢复）；EP4235909/US7489108B2（电池内部 power limit 恢复） | "后续条件→恢复"概念公开，但恢复对象为**通信、停充、电池内部限值**，非调度器权限 |

**结论（单模块层）**：A/B/C/D 各自为高度拥挤的已知领域，任何只主张单一模块的独立权利要求
都无意义。判定只取决于 A+B+C+D 的组合关系是否已被公开串成闭环。

## 3. 两条"最后防线"的纵深攻击结果（本轮新增）

> 首轮用户初判后，剩余未命中的关键是两条防线。本轮对二者做了各两轮的 adversarial 检索
> （permission / authorization / admissible adjustment range / capability / executable bound /
> constraint on scheduler action / degrade / fallback / re-enable / recovery，含中文交叉检索）。

### 防线 1：boundary → scheduler/EMS 可执行动作范围（权限约束），而非直接充电设定值

- **未命中**：未发现"由信息类别选择边界生成方式 → 把该边界应用为对调度器功率预算
  **修正动作的权限/允许调整范围**（而非直接限制某桩充电设定值）"的完整结构。
- **部分覆盖（必须规避）**：
  - ChargePoint 系列：history → **直接限桩口功率**。这是我们与"直接设限"之间的最近邻，
    撰写时必须明确"限定的是调度器对 EV 功率预算的调整权限"而非"限定充电功率本身"。
  - US12393888B2（Siemens 多目标调度器）：per-EV `P_{n,max}` 作为调度优化器**约束**。
    证明"boundary 作为 optimizer 约束"已知，但该边界来自车辆规格/静态信息，**非**由
    **响应信息类别**驱动选择，也**非**响应驱动的权限恢复。规避点：信息条件驱动的边界
    **模式选择** + 约束等级分级。
  - **US10926659 / US20200254896A1（ACN 自适应充电族，与我们数据同源！）**：per-EV
    max rate 作为在线 LP 约束；保守约束可由观测推导（§"conservative constraints derived
    by observing"）；infrastructure protection 用实时背景负载 cap EV load。**这是风险
    最高的近邻**——同数据集、同"观测→保守约束→调度约束"思路。但其边界来源是
    用户输入/电池模型拟合，**无信息类别分级、无权限等级、无响应驱动恢复**。规避点必须
    落在：信息类别→边界模式选择 + 权限约束等级 + 实际响应驱动恢复，三者**组合**。

### 防线 2：实际响应 → 从保护约束恢复更高 scheduler 权限

- **未命中**：未发现"保护性/保守调度约束下持续观测实际响应 → 由实测响应证据
  **恢复更高调度权限**（而非恢复通信/恢复电流设定值/解除停充）"的完整结构。
- **部分覆盖（必须规避）**：
  - US20250196694A1：通信恢复 → 恢复电流。恢复 trigger 是**通信恢复**，恢复对象是
    **电流设定值**，非响应证据、非调度权限。
  - US10214115B2：停止后恢复；EP4235909/US7489108B2：电池内部限值恢复。恢复对象均
    非调度器权限。
  - US10926659（ACN）：可行域失效时 **relax 约束**——是优化器可行性驱动的约束放松，
    **不是**由实测响应证据驱动的调度权限恢复；且无"保护性降级"与"恢复"的分级制度。

## 4. FINAL 判定

### 判定：NARROW CONDITIONAL GO / HOLD P2

**推理**：

1. A/B/C/D 单模块全部已知（§2），因此**任何单模块主张直接 No-Go**。
2. 完整闭环"信息类别 → 边界模式选择 → 边界作为**调度动作权限约束** → 保护性降级 →
   **实测响应驱动权限恢复**"在两轮纵深攻击中**未发现同构公开**（§3 两条防线均未命中
   精确结构）。
3. 但存在三个必须靠收窄组合才能站住的分叉风险（§3 部分覆盖 + §7）：
   - ACN 族已做"观测→保守调度约束→约束放松"（防线 1+2 各吃一半），
   - ChargePoint 已做"history→直接限功率"（B 的直接动作最近邻），
   - US12393888B2 已做"boundary 作为 optimizer 约束"（B 的调度嵌入最近邻）。
4. 因此**不是 Protective GO**（风险未被证明为零），而是 **Narrow Conditional GO**：
   区别必须**技术化、可落设备动作**，否则退化为 Project No-Go（见 §7 判断基准）。

### 可技术化的区别点（Narrow GO 的锚，写入后续 claim 强制要求）

```text
D1  边界生成方式的"信息类别分级选择"：
    同一条实际响应历史，按可用信息类别（capability 信息 / pilot+actual / current-only /
    历史不足）切换边界生成方式 —— 不是单一方式，不是按用户输入或静态规格。
D2  边界应用为"调度器功率预算修正动作的允许范围（权限等级）"：
    限制的是对 EV 功率预算的调整动作边界（如仅允许收缩预算、禁止按"分配−实际"释放差值），
    而非直接限制充电电流设定值 —— 与 ChargePoint 直接限桩口、US12393888B2 静态规格约束区分。
D3  保护性降级 + 实测响应驱动恢复的"权限分级制度"：
    信息/历史不足 → 进入仅保护性动作的权限等级并持续观测实际响应；后续出现新的正向实际
    响应证据（或实际功率贴近边界）→ 恢复更高调度权限等级 —— 与 ACN 可行性放松、
    Hyundai/Kia 通信恢复、电池内部限值恢复区分。
```

> **P2 开闸条件（Narrow GO 的附加条件）**：P2 必须至少验证 D1/D2/D3 对应的可落设备动作
> 技术成立（如：current-only protective boundary 不输出未支持区间 + 权限等级切换机制在
> 回放中的动作序列可观测、可复现），才能进入专利撰写。若 P2 中"权限等级"始终停留在
> 抽象 wording、无法映射为设备动作序列，判定立即降级为 Project No-Go。

## 5. 状态表（Patent Gate 2 后，冻结）

```text
A/B/C/D 单模块                    全部高拥挤（无单模块可主张）
完整 A+B+C+D 闭环（同构公开）      未发现（两轮纵深检索，非法律结论）
    └ 残余风险                     ACN 族（US10926659/US20200254896A1）局部重叠最高
Patent Gate 2 判定                 NARROW CONDITIONAL GO / HOLD P2
    └ 可技术化锚点                 D1 信息类别分级选择 / D2 权限约束 vs 直接设限 /
                                   D3 响应驱动权限恢复
P2                                CONDITIONAL（开闸条件见 §4）
    └ 若 P2 无法落设备动作          → 降级 Project No-Go
P1 formal rerun                   PERMANENTLY PROHIBITED（sentinel consumed）
Project status                    P2 HOLD → P2 可开（在收窄组合范围内）
```

## 6. 判定证据链（检索记录摘要）

- **用户首轮初判**：NARROW CONDITIONAL GO / HOLD P2；单模块 A/B/C/D 高拥挤；完整闭环
  暂未发现完全命中但风险高。已锁定七篇关键文献：
  US20140103866A1、US20210268929A1、US20150077054A1、US11046205B1、US20250196694A1、
  US9685798B2、US10214115B2。
- **本轮防线 1**（4 轮 websearch 攻击 + 3 轮辅助命中分析）：
  - 确认 ChargePoint 系列 history→port limit 为直接限功率（B 已知）；
  - 确认 US12393888B2 为"boundary as optimizer constraint"（静态规格来源）；
  - 新增风险最高近邻：ACN 族 US10926659 / US20200254896A1（conservative constraint
    derivation + per-EV max rate LP constraint + feasibility-driven relaxation）；
  - 未命中"信息类别驱动的边界模式选择 + 调度动作权限约束"。
- **本轮防线 2**（专项检索 re-enable/recovery/authority）：
  - 确认恢复类文献恢复对象均为通信/电流设定值/停充/电池内部限值；
  - US12267886B2 "Assigning authority for EV re-charging" 为会话授权层级，与功率调整
    权限无关；
  - 未命中"实测响应证据 → 恢复调度权限等级"。
- **排除项复核**：本轮未发现任何文献把 recent_var/variance 作为核心支持状态规则，或
  将"信息不足→保守"与"响应驱动恢复"以**调度权限等级**形式绑定；P1 排除项维持不变。

## 7. 残余风险与正式法律检索前置条件

1. **ACN 族（US10926659 / US20200254896A1）是最大残余风险**：与我们数据同源，且已公开
   "观测→保守约束→在线调度 LP 约束→不可行时放松"。若不把 D1（信息类别分级）与 D3
   （实测响应驱动权限恢复）做足，很容易在审查中拆解为 ACN + ChargePoint 的显而易见组合。
2. **"权限/允许范围"措辞风险**：若 D2 无法体现为设备可执行的动作边界，则区别只剩抽象
   wording，按判定出口应判 Project No-Go。P2 的 D1/D2/D3 落地验证是唯一保险。
3. **正式申请前必须完成**：专利代理师的法律检索（含 EP/CNIPA 库 + ISO 15118 / DIN SPEC
   70121 动态功率限制标准演进 + ACN 相关论文 NPL），并对 US10926659 做 element-mapping
   对照。本判定仅冻结"技术筛选层"结论，不替代法律意见。
