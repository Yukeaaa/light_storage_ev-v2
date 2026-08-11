# 独立/从属权利要求树（Claim Surgery v1 — Patent Gate 2 检索前基线；§6 检索后收窄；§7 Claim Surgery v2）

> 依据：P1 Patent Gate NO-GO（`results/raw/phase3_p1/P1_patent_gate.md`）；P2 formal
> frozen outcome = **SUCCESS / NARROW GO**（`results/raw/phase3_p2/P2_patent_gate.md`）。
>
> **Claim Surgery v2（P2 后定稿）**：CLAIM 1 按 P2 已验证机制改写为**可执行设备动作链**
> （§7），删除所有 P2 未验证的夸大措辞；P-001/P-002/P-003 升 C（`claim_evidence_registry.csv`，
> 已按 P2 formal 更新）。升 C 仅表示"有证据支撑"，**不是**"已验证成效"——站级收益、
> 真实 EMS request、active redistribution 均不在已验证范围。
>
> 撰写纪律沿用 Phase 2：所有"已验证"表述以 `claim_evidence_registry.csv` 为准；
> C-005/C-006/C-008~C-010 与 P-004 仍为 D 级禁止外推。

## 0. 权利要求树总览（v2，P2 后定稿）

```text
CLAIM 1（独立，设备动作链）  获取信息 → 信息类别 → 边界生成方式 → EV 功率边界 → 预算修正
   允许区间 → 限制 EMS 修正量 → 持续实测响应 → 边界接触条件 → 改变允许区间 → 后续按新区间执行
   ├─ CLAIM 2（强从属）      信息可用层级 → 边界生成模式的选择规则（capability/pilot/current-only）
   ├─ CLAIM 3（强从属）      history protective boundary 的具体实施（current-only / no-pilot）
   ├─ CLAIM 4（强从属）      历史不足 → conservative fallback（LOCKED / 不输出未支持区间）
   ├─ CLAIM 5（强从属，恢复） 实测响应贴近边界 → 解除保护、恢复更高预算修正允许区间
   ├─ CLAIM 6（可选从属）     实际功率时序的波动/持续性/变化率作为辅助输入（非核心；recent_var
                               状态判定已被 P1 NO-GO，不得恢复为核心）
   ├─ CLAIM 7（弱从属，D 级） 有界修正 active bounded correction（P-004 未验证，仅从属/可选）
   └─ CLAIM 8（场站级从属）   边界汇总为 EV 功率预算接口，与园区 EMS 对接（不主张站级收益）
```

> v2 相对 v1 的关键变化：CLAIM 1 从"6 步闭环骨架"改写为 **10 步可执行设备动作链**
> （P2 已验证的 M1/M2/M3/M4 机制逐条落到设备动作，见 §7.1）。波动类特征仍只保留为
> CLAIM 6 可选从属。

## 1. 独立权利要求（CLAIM 1 v2 — 可执行设备动作链，P2 后定稿）

一种用于光储充站的电动汽车功率控制方法，包括：

1. 获取当前充电对象可获得的充电信息（含实际充电响应时序，以及可获得时的导引/允许电流、
   充电状态与数据可用性信息）；
2. 根据当前可获得的信息，确定所述充电对象的信息类别（车辆侧能力信息可用 /
   pilot+actual 可用 / 仅 current-actual 历史可用 / 历史不足）；
3. 根据所述信息类别，选择对应的**功率边界生成方式**；
4. 生成所述充电对象的 **EV 功率边界**（history protective boundary 等，不输出超出历史
   观察支持域的区间）；
5. 根据所述边界，形成针对 EV 功率**预算修正动作**的**允许区间**
   （allowed budget-correction interval）；
6. 将 EMS 请求的预算修正量限制在该允许区间内（accepted / clipped_upper / clipped_lower）；
7. 持续获得实际充电响应（因果化，避免未来信息泄漏）；
8. 当实际充电响应满足**预定边界接触条件**（如实际功率贴近所选边界，连续若干周期）时，
   **改变所述预算修正允许区间**（由保护性模式恢复到更高调整权限；功率边界生成方式不变）；
9. 后续 EMS 预算修正按改变后的允许区间执行。

**核心保护点（novel combination，P2 已验证机制）**：

> 边界作用于**"预算修正动作范围"**，而不是直接输出充电功率或直接限制桩口功率设定值
> （D2）；边界生成方式按**信息类别分级选择**（D1）；**实际充电响应**用于恢复这个动作范围
> （D3）——三点组合闭环。与全部近邻的区分边界见 §7.2（ACN element-by-element）。
>
> P2 证明的是机制成立（M1=1.0 / M2=1.0 / M4=0.0；natural recovery 1,060 会话）；
> **未证明**站级收益、真实 EMS request 语义、active redistribution（P-004 维持 D 级）。

## 2. 从属权利要求（CLAIM 2–8，草案）

- **CLAIM 2（强从属）**：所述信息类别按可用层级判断——车辆侧能力信息可用 →
  高置信 capability evidence；pilot + actual 可用 → pilot-response/history derived
  boundary；仅 current/actual 历史可用 → current-only history protective boundary。
  （P2 jpl_test M1=1.0：precedence 穷尽查表唯一性，K1 PASS。）
- **CLAIM 3（强从属）**：在仅存在 current/actual 历史（无 pilot / 无车辆能力信息）时，
  所述 history protective boundary 由历史实际功率的滚动统计（persistence / rolling
  quantile / 保守上界）确定，不输出超出历史观察支持域的执行区间。
  （P2 jpl_test：M3_current_only 888,794 / 899,869 cycle，实测验证。）
- **CLAIM 4（强从属）**：当实际响应历史不足时，采用 conservative fallback，拒绝输出
  未受支持的功率区间（LOCKED）；不依据"分配 − 实际"差值进行功率释放。
  （P2 jpl_test：M4_history_insufficient 11,095 cycle 全部 LOCKED，M4=0.0 无
  unsupported release。）
- **CLAIM 5（强从属，恢复）**：在保护性控制模式下，当检测到实际功率贴近所选边界
  （预定边界接触条件，如 protective_bound>0 且 actual ≥ 0.95×boundary 连续 3 cycle）时，
  改变预算修正允许区间、恢复更高调整权限（保护不是永久 cap；power boundary 生成方式不变）。
  （P2 jpl_test：natural complete recovery traces = 1,060 / 1,060 会话；M4→M3 是
  信息驱动转换，不计入 D3 恢复计数。）
- **CLAIM 6（可选从属，非核心）**：在某些实施方式中，可使用实际功率时间序列的波动、
  持续性、变化率等特征作为**辅助输入**；该特征不作为已独立验证的技术规律主张
  （recent_var 状态判定已被 P1 NO-GO 排除，不得恢复为核心规则）。
- **CLAIM 7（弱从属，D 级，可选实施方式）**：当信息类别与历史充分性满足预设条件、且站级存在
  可调整功率机会时，在所述允许范围内对 EV 功率预算执行**有界修正**。
  （P-004 未验证，仅从属/可选；**不得**升为主权利要求。）
- **CLAIM 8（场站级从属，不升第二发明族）**：将多个充电对象的短时功率边界汇总为 EV
  功率预算约束，并提供给园区 EMS 对接。**不主张站级收益/储能补偿减少**（未验证）。
  （与 Phase 2 决策3 一致；D2/D3 fusion 不拆第二独立发明族。）

## 3. 分层依据（v2，P2 后更新）

| 层次 | 证据/依据 | 说明 |
|---|---|---|
| 主权利要求（1/2/3/4/5） | P-001（C）+ P-002（C，机制层）+ P-003（C） | 组合关系为检索对象；**P2 formal SUCCESS 已验证 D1/D2/D3 可落设备动作** |
| 强从属（2/3/4） | P-001（C）+ P2 M1/M3/M4 | 信息分支与边界生成方式 P2 实测验证 |
| 强从属（5，恢复） | P-003（C，STRONGLY SUPPORTED） | natural recovery 1,060 会话，非 replay 凑数 |
| 可选从属（6） | 原 A5 recent_var（P1 NO-GO） | 降级为辅助输入，**不得写成已验证规律** |
| 弱从属（7） | P-004（D 级，未验证） | active correction 不作主权利要求必选 |
| 场站级（8） | 架构设计 | 价值应用层；不主张站级收益 |

## 4. 术语纪律与撰写约束（沿袭，v1 新增条款）

- pilot 与 actual 差异只能称"导引/允许电流与实际响应差异"，不得称"命令失败/拒绝"。
- "可吸收余量/可回收能力/可回收电量"未经 E1-Full 自然正阶跃验证 + 新独立数据验证前不得
  出现（C-004 仍 D 级）。
- 不得把 `recent_var`/variance 写成已验证的响应支持状态判定规律（P1 formal No-Go）；
  波动类特征仅作辅助输入。
- "控制权限"概念保留于技术交底；CLAIM 1 正文用技术化措辞（边界应用模式 / 功率调整约束
  等级 / 修正允许范围）。
- 闭环收益（储能补偿减少/光伏消纳提高）在 E4.1 响应仿真器验证通过前不得写入实施例效果。
- **真实 EMS request 语义未验证**：P2 的 requested_delta 是冻结的外生 conformance probe
  （v1.0.2 §7 禁止按 [L,U] 反向生成 probe），不得写成"已验证真实 EMS 预算修正请求"。
- **站级收益 / 储能补偿减少 / 主动重分配**不得写成已验证效果（P-004 仍 D 级，E4.1 未过）。
- P2 的 replay 结果（train-side 机制证据）**不得**冒充 natural 计数或真实站点分布统计。

## 5. Patent Gate 2 前冻结的检索对象与排除项

**检索对象（A+B+C+D 组合闭环）**：

```text
A  信息可用性 → 控制/模型模式选择
B  actual/history → EV capability/power boundary
C  信息或历史不足 → protective/conservative fallback
D  后续实际响应 → constraint relaxation / permission recovery
```

重点查：**A+B+C+D 是否已被公开串成闭环**（单模块已知不致命，组合关系是否显而易见/已
明确公开才是判定点）。

**排除项（检索与撰写不得重新引入）**：

- recent_var 高低作为核心状态规则；variance-defined S1/S2 作为 CLAIM 1 核心；
- broad active redistribution 任何宽泛表述；
- PV/BESS benefit；
- 为绕 prior art 临时增加的复杂度（risk score、双模型、classifier 等）。

## 6. Patent Gate 2 后收窄（FINAL：NARROW CONDITIONAL GO / HOLD P2）

> 检索后结论见 `results/raw/patent_gate2/patent_gate2_final.md`。本版从"检索前基线"升级为
> **检索后收窄版**。A/B/C/D 单模块全部高拥挤，完整闭环两轮纵深检索未发现同构公开，但存在
> 三个分叉风险（ACN 族、ChargePoint 直接限功率、US12393888B2 静态规格边界约束），因此
> 判定为 **Narrow Conditional GO**：必须收窄组合并技术化，否则退化为 Project No-Go。

### 6.1 强制收窄锚点（D1/D2/D3，写入后续撰写要求）

```text
D1  信息类别分级选择边界生成方式：同一实际响应历史下，按可用信息类别（capability /
    pilot+actual / current-only / 历史不足）切换边界生成方式 —— 非单一方式、非用户输入、
    非静态规格。区分 ACN 族（边界来自用户输入/电池模型拟合）与 US12393888B2（静态规格）。
D2  边界应用为"调度器功率预算修正动作的允许范围（权限等级）"：限制对 EV 功率预算的调整
    动作边界（如仅允许收缩、禁止按"分配−实际"释放差值），而非直接限制充电电流设定值。
    区分 ChargePoint 直接限桩口功率。
D3  保护性降级 + 实测响应驱动恢复的权限分级制度：信息/历史不足 → 仅保护性动作权限等级并
    持续观测实际响应；新正向实际响应证据（或实际功率贴近边界）→ 恢复更高调度权限等级。
    区分 ACN 可行性放松、Hyundai/Kia 通信恢复、电池内部限值恢复。
```

> **D2 是最大 wording 风险**：若无法体现为设备可执行的动作边界，只剩抽象"权限"措辞，
> 按判定出口即 Project No-Go。P2 必须验证 D1/D2/D3 对应的可落设备动作序列。

### 6.2 CLAIM 1 收窄方向（v2 待 P2 验证后定稿）

保留 v1 的 6 步闭环骨架，但对第 4 步的"功率调整约束等级/应用模式"补充强制措辞：

- 第 4 步明确：所述边界用于约束对**功率预算的修正动作**（允许收缩、禁止无条件释放差值），
  而非直接设定充电电流或限制桩口功率；
- 第 3 步明确：边界生成方式由**当前可用信息类别**决定（分级选择），非单一估计方式；
- 第 6 步明确：恢复触发为**实测实际响应证据**（新的正向响应 / 实际功率贴近边界），
  排除通信恢复、停充解除、电池内部条件作为替代触发。

### 6.3 状态更新

```text
Patent Gate 2    NARROW CONDITIONAL GO / HOLD P2 →（P2 后）P2 = SUCCESS / NARROW GO
P2 formal        SUCCESS（M1=1.0 / M2=1.0 / M4=0.0 / M3 natural 1,060 会话；§6 判门）
D1/D2/D3         已落设备动作并验证（信息类别分级选择 / 预算修正动作允许区间 / 实测响应驱动恢复）
P3               HOLD（不自动开；新增实验需新授权 + 新协议版本）
排除项           维持（§5）不变，新增：不得主张单一模块（A/B/C/D 全已知）；不得主张站级收益
```

### 6.4 P2 后定稿（Claim Surgery v2 生效）

- CLAIM 1 已按 §7.1 改写为 10 步设备动作链（本文件 §1）；
- P-001/P-002/P-003 在 `claim_evidence_registry.csv` 升 C（P-002 由 D 升 C，
  controller mechanism 已验证）；P-004 维持 D；
- 所有"已验证"升级仅到 C（证据支撑），不升 B/A（成效/普遍性）；
- 下一步：§7.2 ACN element-by-element 对照 + 专利代理师法律检索意见。

## 7. Claim Surgery v2 — 设备动作链与 ACN 最近邻对照（P2 后冻结）

### 7.1 设备动作链（CLAIM 1 v2 靶子，P2 已验证机制；与 preregistration §9 靶子一致）

```text
获取当前充电信息（含实际充电响应时序，及可获得时的导引/允许电流、状态、数据可用性）
↓
确定信息类别（capability / pilot+actual / current-only / 历史不足）
↓
选择对应功率边界生成方式（D1：M1/M2/M3/M4 precedence 穷尽查表，jpl_test M1=1.0）
↓
生成 EV 功率边界（D1：history protective boundary，不输出超出历史观察支持域区间）
↓
根据该边界形成预算修正允许区间（D2：allowed budget-correction interval）
↓
将 EMS 请求的预算修正量限制在该区间（D2：accepted / clipped_upper / clipped_lower；
  jpl_test m2_cov=0.376743 实际生效、n_diff_prot_normal=72,067）
↓
持续获得实际充电响应（因果化 shift(1)，禁止未来信息）
↓
实际响应满足预定边界接触条件（protective_bound>0 且 actual ≥ 0.95×boundary，连续 3 cycle）
↓
改变预算修正允许区间（D3：application_state → NORMAL，boundary_mode 不变；
  jpl_test natural complete traces=1,060 / 1,060 会话）
↓
后续预算修正按新区间执行（after_diff 逐条可观察）
```

> 保护焦点：**边界作用于"预算修正动作范围"，而不是直接输出充电功率或直接限制桩口功率
> 设定值**；实际充电响应用于**恢复这个动作范围**（不是通信恢复/停充恢复/电池内部限值恢复）。

### 7.2 ACN 最近邻 element-by-element 对照（US10926659 / US20200254896A1，同数据源）

> 来源：`prior_art_matrix.md` §6 已将 ACN 族列为主风险（观测→保守约束→在线调度约束→
> 可行性放松）。本表逐要素对照，供专利代理师复核；差异点落在 §7.1 加粗的 D1/D2/D3 三点。

| CLAIM 1 v2 要素 | ACN 族（US10926659 / US20200254896A1） | 差异判定 |
|---|---|---|
| 1 获取充电信息（含实际响应） | 观测 charging session（同一数据源） | 相同（背景，非区分点） |
| 2 确定信息类别 | 无信息类别分级概念 | **D1 差异** |
| 3 按信息类别选择边界生成方式 | 单一 estimation/optimization（电池模型拟合 / 用户输入），非分级切换 | **D1 差异** |
| 4 生成 EV 功率边界 | per-EV max rate 边界（模型/可行性驱动） | 边界生成动机不同（历史观测保护 vs 模型/可行性） |
| 5 边界 → 预算修正允许区间 | 边界直接作在线 LP 调度约束（capacity 分配） | **D2 差异**：本方案约束"预算修正动作的允许范围（权限等级）"，非直接调度分配 |
| 6 限制 EMS 修正量（accepted/clipped） | 无"修正动作权限"概念（LP 解即最终分配） | **D2 差异** |
| 7 持续实测响应 | 有实际响应观测（用于可行性检查/定价） | 部分相同（观测本身非新颖） |
| 8 实测响应 → 恢复触发 | 恢复为可行性驱动约束放松（feasibility-based relaxation），非响应证据驱动权限恢复 | **D3 差异** |
| 9 后续按新区间执行 | — | 由 D2/D3 继承 |

**结论（供代理师复核）**：

```text
单要素：A/B/C/D 全部高拥挤（§6 已确认），不可单要素主张；
组合差异：D1（信息类别分级选择）+ D2（边界作用于预算修正动作权限，而非直接分配/设定值）
         + D3（实测响应驱动恢复权限）三点组合在 ACN 族中未发现同构公开。
ACN 族是"可行性驱动的约束放松"，本方案是"响应证据驱动的权限恢复"——恢复对象为调度器
        权限等级而非物理限值，这是与 ACN 族最核心的语义分界线。
```

> 注意：本对照基于 P2 冻结机制语义，不是法律检索/无效分析意见；以专利代理师正式意见为准。
