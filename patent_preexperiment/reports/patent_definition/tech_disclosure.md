# 主发明技术交底骨架（Patent Definition；P2 formal 后版本）

> **当前状态**：P1 formal No-Go（recent_var/variance 三态移出核心）→ Patent Gate 2
> NARROW CONDITIONAL GO → **P2 formal SUCCESS / NARROW GO**（D1/D2/D3 设备动作链机制成立，
> mechanism realizability only）。P3 HOLD；下一步仅批准 P2.1 攻击性 falsification。
> 权威 claim 以 `claim_tree.md` v2（§7 设备动作链）+ `results/raw/phase3_p2/P2_patent_gate.md`
> 为准；本交底骨架正文已对齐 P2 实际验证。
> "已验证/证据级" 以 `data_registry/claim_evidence_registry.csv` 为准。本文件不是法律意见；
> 最终申请前需专利代理师做完整法律检索与权利要求判断。
> **P2 是 mechanism evidence，不是 performance evidence**：站级收益 / 储能补偿 / 主动重分配 /
> 真实 EMS request 语义均未验证（P-004 维持 D）。

## 1. 建议技术题名（备选）

- 主：**一种基于充电信息类别的电动汽车功率边界生成与预算修正允许区间控制方法**
- 场景版：**一种用于光储充站的基于充电响应信息的功率边界生成、预算修正允许区间
  限制与实测响应驱动恢复方法**
- 动作链版（最贴合 P2 验证范围）：**一种电动汽车充电功率预算修正动作的约束方法，
  依据可获得的充电信息类别生成功率边界、形成预算修正允许区间，并据实测响应恢复所述允许区间**

## 2. 要解决的技术问题（发明起点）

传统 EMS 给充电车辆分配功率后，**默认该车辆能按分配值执行**：

```text
EMS 给车 A 安排 7 kW
→ 未来就按 7 kW 参与站级平衡
```

但车辆实际执行可能长期只有 4 kW、正在波动、或刚进入新的充电状态。于是：

```text
EMS 账面认为 EV 能吸收 7 kW
实际 EV 只吸收 4 kW
→ 计划与实际的差值（3 kW）由储能/电网/下一周期 EMS 被迫补偿
```

**技术问题**：在无法直接可靠获知车辆真实执行能力（无 BMS/SOC/真实剩余需求，
或无 pilot/导引信息）且车辆执行行为随时间变化时，EMS 无法判断"该车当前是否仍
配得上被当作 X kW 的可执行负荷"。盲目信任导致站级调度建立在未经响应证据支持的
假设之上；盲目设保守上限则浪费可用功率。

**本发明不解决**：差值"该给谁"（主动重分配，已有大量近邻且当前证据不足）。

**本发明解决**：在当前数据条件下，"有没有资格继续把这辆车当作 X kW 的可执行负荷"，
以及据此应赋予 EMS 多大的控制权限。

## 3. 核心技术机制（D1/D2/D3 设备动作链，P2 已验证机制）

```text
获取当前充电信息（实际响应时序 + 可得时的导引/允许电流、状态、数据可用性）
        ↓  D1
确定信息类别（capability / pilot+actual / current-only / 历史不足）
        ↓  D1
选择对应功率边界生成方式（M1/M2/M3/M4 precedence 穷尽查表）
        ↓  D1
生成 EV 功率边界（M3：history protective boundary；M4：conservative fallback / LOCKED；
                   M2：dispatch-only，无 numerical boundary_value；M1：注入 replay）
        ↓  D2
根据边界形成"预算修正动作允许区间"（allowed budget-correction interval）
        ↓  D2
将 EMS 请求的预算修正量限制在该区间（accepted / clipped_upper / clipped_lower）
        ↓
持续获得实际充电响应（因果化，禁止未来信息）
        ↓  D3
判断预定边界接触条件（actual 贴近 boundary，连续若干 cycle）
        ↓  D3
满足条件时单向改变预算修正允许区间（PROTECTIVE → NORMAL，boundary_mode 不变）
        ↓
后续预算修正按新区间执行（after_diff 可观察）
```

**保护焦点**：边界作用于**"预算修正动作范围"**，而不是直接输出充电功率或直接限制桩口
功率设定值；实际充电响应用于**恢复这个动作范围**（不是通信恢复 / 停充恢复 / 电池内部
限值恢复）。

**关键技术术语（与 AGENTS.md 术语纪律对齐）**：

- **信息类别（D1）**：按当前可获得信息将充电对象分为 M1 capability-rich（注入 replay）、
  M2 pilot+actual（**dispatch-only**，P2 未生成 numerical boundary）、M3 current-only
  （history protective boundary）、M4 历史不足（conservative fallback / LOCKED）。P2 验证
  M1/M2/M3/M4 precedence 穷尽查表唯一性（jpl_test M1=1.0）。**CLAIM 1 v2 主权利要求优先
  围绕 M3/M4 + D2 + D3 收紧**；capability/pilot-rich 作从属/替代实施例。
- **预算修正允许区间（D2）**：边界用于约束对 EV 功率**预算修正动作**的允许区间（权限等级
  编码为数值 action set：accepted / clipped_upper / clipped_lower），**不**无条件按
  "分配功率 − 实际功率"释放差值，也非直接设定充电电流/桩口功率。P2 验证 K2/M2 PASS
  （m2_cov=0.376743 实际生效；n_diff_prot_normal=72,067）。**controller mechanism，非效果声明**。
- **实测响应驱动恢复（D3）**：信息/历史不足 → 保护性观测（M4 LOCKED / M3 PROTECTIVE 不
  释放差值）；实测响应满足预定边界接触条件 → **单向恢复**至更高预算修正允许区间
  （NORMAL）。P2 实现中 `m3_recovered` 在 M3 段内单调，recovery 后不自动退回 PROTECTIVE
  （**非双向降级↔恢复**，见 `phase3_p2/state_machine.py`）。jpl_test M4=0.0（无 unsupported
  release）、M3 natural complete traces=1,060 / 1,060 会话。
  > **证据层级注意**：P2 证明恢复机制及动作变化已观测；"边界接触是否构成恢复更高权限的
  > **有效能力证据**"尚待 P2.1A falsification（rolling-Q95 自相关伪证据风险未排除）。

## 4. 独立权利要求必要步骤（草案，10 步设备动作链；对齐 `claim_tree.md` v2 §7.1）

1. 获取当前充电对象可获得的充电信息（含实际充电响应时序，以及可获得时的导引/允许
   电流、充电状态与数据可用性信息）；
2. 根据当前可获得的信息，确定所述充电对象的**信息类别**（capability / pilot+actual /
   current-only / 历史不足）；
3. 根据所述信息类别，选择对应的**功率边界生成方式**（M1/M2/M3/M4 precedence 穷尽查表）；
4. 生成所述充电对象的 **EV 功率边界**（M3 history protective boundary，不输出超出历史
   观察支持域的区间；M4 历史不足时为 conservative fallback / LOCKED）；
5. 根据所述边界，形成针对 EV 功率**预算修正动作**的**允许区间**（allowed budget-
   correction interval）；
6. 将 EMS 请求的预算修正量限制在该允许区间内（accepted / clipped_upper / clipped_lower）；
7. 持续获得实际充电响应（因果化，避免未来信息泄漏）；
8. 判断所述实际充电响应是否满足**预定边界接触条件**（如实际功率贴近所选边界，连续
   若干周期）；
9. 满足所述边界接触条件时，**单向改变所述预算修正允许区间**（由保护性模式恢复到更高
   调整权限；功率边界生成方式不变；P2 实现为 M3 段内 `m3_recovered` 单调，非双向降级↔恢复）；
10. 后续 EMS 预算修正按改变后的允许区间执行。

**核心保护点（novel combination，P2 已验证机制）**：第 3 步（信息类别分级选择边界生成
方式，D1）→ 第 5/6 步（边界 → 预算修正动作允许区间，D2）→ 第 8/9 步（实测响应驱动单向
恢复，D3）的三点组合闭环。与全部近邻的区分边界见 §6 与 `claim_tree.md` §7.2（ACN
element-by-element）。

## 5. 实施例证据（本项目数据）

| 证据 | 数据来源 | 证据级 | claim_id |
|---|---|---|---|
| 近期实际波动（recent_var）越高 → E1 响应证据密度越高，train/val/test 方向一致（0.0039→0.0261 / 0.0054→0.0331；test Q3,Q4>pooled） | A5 扩展审计（baseline `34f04f6`） | C（描述性假设，非已验证规则；P1 No-Go 后移出核心，仅作辅助） | C-007 |
| 三种真实信息条件分支存在：measured_pilot（caltech）/ current-only（jpl 约 90% 文件仅 current）/ 数据不足 | E0-Full 字段覆盖审计 + A5 | A/C | P-001 |
| 信息/历史不足 → 保护性观测（M4 LOCKED / M3 PROTECTIVE 不释放差值）；实测响应贴近边界 → 单向恢复 | P2 formal（jpl_test M4=0.0、M3 natural 1,060 会话） | C（机制已观测；"边界接触是否构成恢复更高权限的有效能力证据"待 P2.1A falsification） | P-003 |
| 预算修正动作允许区间 gate（权限等级编码为数值 action set → accept/clip，m2_cov=0.376743 实际生效） | P2 formal（K2/M2 PASS） | C（controller mechanism，**非效果声明**） | P-002 |
| active bounded correction（有界修正） | 审查结论52 降级 | D（opportunity 方向混合、caltech E3 formal FAIL；P2 后维持 D） | P-004 |

**不允许表述为已验证**：储能补偿减少、光伏消纳提高、闭环收益、站级经济效益
（对应 C-005/C-006/C-008~C-010 仍为 D 级）。

## 6. 与现有技术的区分要点（撰写时必须明确；Patent Gate 2 FINAL 后）

> Patent Gate 2 已确认 A/B/C/D **单模块全部高拥挤**；唯一可主张空间是 **D1/D2/D3 三点
> 组合**（技术化、可落设备动作）。主风险近邻 = ACN 族（US10926659 / US20200254896A1，
> 同数据源，observation→conservative constraint→scheduling constraint→feasibility
> relaxation）。逐要素对照见 `claim_tree.md` §7.2。

| 近邻 | 其触发/机制 | 本发明的区别（落点） |
|---|---|---|
| ACN 族 US10926659 / US20200254896A1 | 观测→保守约束→在线 LP 调度约束→**可行性驱动放松** | **D2**：本发明约束"预算修正动作的允许区间（权限等级）"，非直接调度分配/LP 约束；**D3**：响应证据驱动权限恢复，非可行性驱动放松 |
| Porsche US12054065B2 | 充电站/负载管理**系统故障** → dynamic/static load-management 切换 | 触发是**车辆实际响应/信息类别**，不是站/系统故障 |
| ChargePoint US10464435B2 等 | 基于**近期供电历史**响应 power-limit message / 直接限桩口功率 | **D2**：本发明约束的是 EMS 预算修正动作范围，而非直接限制充电电流/桩口功率设定值 |
| US12393888B2 | 静态规格 boundary 作 optimizer 约束 | **D1**：本发明边界由**信息类别分级动态选择**生成，非静态规格 |
| US9290104B2 | 改变 pilot 前后读取功率、测量响应 | "pilot 阶跃→测量响应"已有公开；本发明不主张"调 pilot 控功率"，而是信息类别→边界→预算修正动作权限→实测响应恢复 |
| 通信恢复 / 停充恢复 / 电池内部限值恢复类 | 后续条件→恢复（恢复对象为通信/电流/停充/电池内部） | **D3**：本发明恢复对象为**调度器预算修正权限等级**，非物理限值/通信状态 |

**可主张空间 = D1 + D2 + D3 的设备动作组合**（非任一单模块）：
信息类别分级选择边界生成方式 → 边界作用于预算修正动作允许区间 → 实测响应驱动恢复该
允许区间。该组合是后续专利检索最重点的攻击对象，亦是 P2.1 falsification 要杀的发明核。

## 7. 尚需补的最小实验（P2 后；P3 HOLD，仅批准 P2.1 攻击性验证）

> P2 formal = SUCCESS / NARROW GO（mechanism realizability only）。P3 不自动开；
> 下一步只批准**攻击性 falsification**，不优化、不扩复杂度。任一失败 → Project No-Go。

1. **P2.1A — D3 Falsification gate**：D3 recovery 是否只是 rolling-Q95 自相关伪证据？
   做 negative control（恒功率/persistence baseline、recovery 时点随机匹配、lag-shuffle、
   rolling median/max baseline）。核心指标不是"recovery 数量"，而是"D3 条件对后续可支持
   上界是否有超过简单功率持续性的预测增益"。无增量辨识力 → **D3 No-Go**。
2. **P2.1B — D2 Technical-Effect gate（最小闭环/HIL）**：EMS request 来自独立 controller
   （非内部枚举 probe）、EV response 独立于 gate；比较 unrestricted correction vs D1+D2
   vs D1+D2+D3。指标：infeasible command rate / boundary violation / unsupported
   positive correction rate / tracking residual / unnecessary protective duration。
   无真实技术效果 → **D2 No-Go**。完全不做经济收益。
3. **专利代理师检索**：ACN 族（US10926659 / US20200254896A1）element-by-element 对照
   （见 `claim_tree.md` §7.2）+ EP/CNIPA 库 + ISO 15118 动态功率限制标准演进。

**已停用（P1 No-Go / P2 后不再作为定稿前置）**：
- ~~新独立数据验证 support rule（C-007 升为已验证规则）~~——recent_var 已移出核心；
- ~~E4.1 响应仿真器验证 P-002 闭环站级效果~~——P2 已验证 P-002 机制层；闭环效果改由
  P2.1B 最小闭环 gate 攻击，不追求站级经济收益。

## 8. 遗留待确认事项（open questions，定稿前；P2 后）

- **D3 trigger 语义有效性**（P2.1A 攻击点）：boundary-contact 是否包含超过"简单功率
  持续性"的增量信息？若 P2.1A 证伪，D3 区别锚消失，需重判 Patent Gate；
- **D2 技术效果**（P2.1B 攻击点）：在独立 EMS request + 独立 EV response 的最小闭环中，
  D1+D2+D3 是否产生明确物理控制效果（infeasible/boundary-violation/tracking residual）？
- **CLAIM 1 主权利要求覆盖范围**：是否将 M2（dispatch-only）/ M1（注入 replay）纳入主
  权利要求，还是仅 M3/M4 + D2 + D3（审查建议后者，避免"证据范围 > 实现范围"）；
- "预算修正允许区间 / 权限等级"在权利要求中的落地措辞（限制处理权限 / 边界钳制 /
  action set），兼顾可读性与宽保护；
- 场站级汇总接口（EV 边界 → EV 功率预算 → PV/BESS/grid EMS）放从属权利要求（不主张
  站级收益，P-004 维持 D）；
- 专利代理师 ACN element-mapping + EP/CNIPA 库 + ISO 15118 动态功率限制标准演进。
