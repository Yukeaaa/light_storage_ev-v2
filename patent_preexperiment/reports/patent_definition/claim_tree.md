# 独立/从属权利要求树（Claim Surgery v1 — Patent Gate 2 检索前基线）

> 依据：P1 Patent Gate NO-GO（`results/raw/phase3_p1/P1_patent_gate.md`）。本版为
> **Claim Surgery v1**：把 prior-art 检索对象冻结为剩余保护架构，排除 recent_var 状态
> 判定器作为核心。这是检索前的基线，**不是**定稿；Patent Gate 2 结果决定后续是否收窄
> （Narrow Conditional GO）或止损（Project No-Go）。
>
> 撰写纪律沿用 Phase 2：所有"已验证"表述以 `claim_evidence_registry.csv` 为准；
> C-005/C-006/C-008~C-010 仍为 D 级禁止外推；P-002 仍 D 级（"控制约束/权限"是机制
> 而非已验证效果）。

## 0. 权利要求树总览（v1 修订）

```text
CLAIM 1（独立，核心闭环）   信息条件/历史充分性 → 边界生成模式 → 约束等级 → 保护降级/响应恢复
   ├─ CLAIM 2（强从属）      信息可用层级 → 边界生成模式的选择规则（capability/pilot/current-only）
   ├─ CLAIM 3（强从属）      history protective boundary 的具体实施（current-only / no-pilot）
   ├─ CLAIM 4（强从属）      历史不足 → conservative fallback（不输出未支持区间）
   ├─ CLAIM 5（强从属，恢复） 后续实际响应证据 → 解除保护、恢复更高控制权限
   ├─ CLAIM 6（可选从属）     实际功率时序的波动/持续性/变化率作为辅助输入（非核心、非经验证规律）
   ├─ CLAIM 7（弱从属）      有界修正（evidence 充分且 opportunity 满足时，限域内修正）
   └─ CLAIM 8（场站级从属）  边界汇总为 EV 功率预算接口，与园区 EMS 对接
```

> 注：v1 把原 CLAIM 2/3（variance 定义状态、滑动窗方差/标准差/极差 → S1/S2/S3）
> **移出核心地位**。波动类特征只保留为 CLAIM 6 可选从属，且不得写成"已验证规律"。

## 1. 独立权利要求（CLAIM 1，v1 核心）

一种用于光储充站的电动汽车功率控制方法，包括：

1. 获取充电对象在当前环境下可获得的信息，包括实际充电电流/功率时序，以及可获得时的
   导引/允许电流、充电状态与数据可用性信息；
2. 判断当前可使用的**信息类别**与**实际响应历史的充分程度**（不依赖 variance 定义的
   支持状态）；
3. 根据所述信息类别与历史充分性，选择一种**短时功率边界生成方式**，所述方式至少包括：
   较高质量 capability evidence（如车辆侧/桩侧能力信息）对应高置信边界；pilot+actual
   可用时对应响应/历史派生边界；仅 current/actual 历史可用时对应 history protective
   boundary；历史本身不足时对应 conservative fallback；
4. 根据所选择的短时功率边界，确定针对所述充电对象的**功率调整约束等级**与所述功率
   边界的**应用模式**，限制基于该边界实施功率预算修正的**允许范围**；在信息或历史
   不足时，该允许范围仅支持保护性控制，而非无条件根据"分配功率 − 实际功率"释放差值；
5. 当信息或历史不足时进入**保护性控制模式**：所述保护性模式不是永久限功率，而是持续
   观察后续实际充电响应；
6. 当后续实际充电响应提供新的支持证据（或实际功率贴近所选边界）时，允许从保护性模式
   **恢复至更高功率调整约束等级/更高控制权限**。

**核心保护点（novel combination）**：第 3 步（信息条件 → 边界生成模式选择）→ 第 4 步
（边界 → 功率调整约束等级/允许范围）→ 第 5/6 步（保护性降级 + 实际响应驱动恢复）之间的
**闭环组合关系**。这是与全部近邻的区分边界，也是 Patent Gate 2 的检索靶子
（见 `prior_art_matrix.md` §5）。

## 2. 从属权利要求（CLAIM 2–8，草案）

- **CLAIM 2（强从属）**：所述信息类别按可用层级判断——车辆侧能力信息可用 →
  高置信 capability evidence；pilot + actual 可用 → pilot-response/history derived
  boundary；仅 current/actual 历史可用 → current-only history protective boundary。
- **CLAIM 3（强从属）**：在仅存在 current/actual 历史（无 pilot / 无车辆能力信息）时，
  所述 history protective boundary 由历史实际功率的滚动统计（persistence / rolling
  quantile / 保守上界）确定，不输出超出历史观察支持域的执行区间。
- **CLAIM 4（强从属）**：当实际响应历史不足时，采用 conservative fallback，拒绝输出
  未受支持的功率区间；不依据"分配 − 实际"差值进行功率释放。
- **CLAIM 5（强从属，恢复）**：在保护性控制模式下，当检测到新的正向实际响应或实际功率
  贴近所选边界时，解除保护性约束并恢复更高功率调整约束等级/控制权限（保护不是永久 cap）。
- **CLAIM 6（可选从属，非核心）**：在某些实施方式中，可使用实际功率时间序列的波动、
  持续性、变化率等特征作为**辅助输入**；该特征不作为已独立验证的技术规律主张。
- **CLAIM 7（弱从属，可选实施方式）**：当信息类别与历史充分性满足预设条件、且站级存在
  可调整功率机会时，在所述允许范围内对 EV 功率预算执行**有界修正**。
- **CLAIM 8（场站级从属，不升第二发明族）**：将多个充电对象的短时功率边界汇总为 EV
  功率预算约束，并提供给园区 EMS 对接。（与 Phase 2 决策3 一致；D2/D3 fusion 不拆第二
  独立发明族。）

## 3. 分层依据（v1）

| 层次 | 证据/依据 | 说明 |
|---|---|---|
| 主权利要求（1/2/3/4/5） | 保护性架构 candidate（P-001 改写）+ 三个真实信息分支（P-001）+ 工程安全设计 | 组合关系是检索对象；P1 未否定，但未验证 |
| 强从属（3/4/5） | P-002（D 级，机制）+ P-001 | 具体实施方式为 P2 预留验证点 |
| 可选从属（6） | 原 A5 recent_var（Caltech exploratory only） | 降级为辅助输入，**不得写成已验证规律** |
| 弱从属（7） | P-004（D 级） | active correction 不作主权利要求必选 |
| 场站级（8） | 架构设计 | 价值应用层，非创新核心 |

## 4. 术语纪律与撰写约束（沿袭，v1 新增条款）

- pilot 与 actual 差异只能称"导引/允许电流与实际响应差异"，不得称"命令失败/拒绝"。
- "可吸收余量/可回收能力/可回收电量"未经 E1-Full 自然正阶跃验证 + 新独立数据验证前不得
  出现（C-004 仍 D 级）。
- 不得把 `recent_var`/variance 写成已验证的响应支持状态判定规律（P1 formal No-Go）；
  波动类特征仅作辅助输入。
- "控制权限"概念保留于技术交底；CLAIM 1 正文用技术化措辞（边界应用模式 / 功率调整约束
  等级 / 修正允许范围）。
- 闭环收益（储能补偿减少/光伏消纳提高）在 E4.1 响应仿真器验证通过前不得写入实施例效果。

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

## 6. 定稿前待补（Gate 2 之后）

- 依 Patent Gate 2 结果决定：Protective GO（直接 P2）/ Narrow Conditional GO（收窄组合、
  重点保护边界应用模式 + 约束等级 + recovery trigger）/ Project No-Go（止损）。
- 正式新颖性/创造性/FTO 法律检索（含中/欧专利库 + NPL）后，再做 claim 步骤裁剪合并。
