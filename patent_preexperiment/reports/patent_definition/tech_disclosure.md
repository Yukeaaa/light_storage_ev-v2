# 主发明技术交底骨架（Patent Definition Phase 1）

> 依据：审查结论52 Final R1 Patent Gate（D1=B protective-only、D2/D3 fusion=YES、
> Project Final Verdict = PROTECTIVE GO + D2/D3 融合架构）。
> 本文件是**技术交底骨架**，供后续正式专利交底书与权利要求撰写使用；其中标注的
> "已验证/证据级" 以 `data_registry/claim_evidence_registry.csv` 为准。
> 本文件不是法律意见。
> **Phase 2（Claim Architecture Freeze）已应用**：三态支持状态（§3）、CLAIM 1 第 5/6 步
> 技术化措辞（§4），见 `open_questions_decision_record.md`。

> **⚠ 状态 banner（P1 No-Go / P2 SUCCESS 后更新）**：本骨架撰写于 Final R1 Patent Gate
> 之后、P1 formal 与 P2 formal 之前。下方 §3–§7 中以下表述**已过时，以本 banner 与
> `claim_tree.md` v2（§7 设备动作链）/ `results/raw/phase3_p2/P2_patent_gate.md` 为准**：
> 1. **S1/S2/S3 三态"响应证据支持状态"作为核心**——P1 formal No-Go 已把 recent_var /
>    variance 状态判定移出核心（见 `results/raw/phase3_p1/P1_patent_gate.md`）；P2 验证的是
>    **M1/M2/M3/M4 信息类别（capability / pilot+actual / current-only / 历史不足）→ 边界
>    生成方式**的 precedence 查表，不是 variance 三态。
> 2. **"保护降级与响应恢复"双向闭环**——P2 实现的是 **M3 段内单向恢复**（`m3_recovered`
>    单调，recovery 后只要仍 M3 即保持 NORMAL，不自动退回 PROTECTIVE；见
>    `phase3_p2/state_machine.py`）。下方"既能降级也能恢复"措辞待收缩为"信息/历史不足→
>    保护性观测；实测响应满足边界接触条件→单向恢复"。
> 3. **P-002 = D 级"控制权限切换机制"**——P2 formal 后 P-002 升 **C**（K2/M2 PASS，
>    controller mechanism 已验证）；但仅机制层，**不是效果声明**。
> 4. **M2（pilot+actual）分支**——P2 中 M2 为 **dispatch-only**（无 numerical
>    `boundary_value`，仅 branch/mode dispatch；见 `phase3_p2/pipeline.py`）。CLAIM 1 v2
>    主权利要求优先围绕 **M3/M4 + D2 + D3** 收紧，capability/pilot-rich 作从属/替代实施例。
> 5. **P2 是 mechanism evidence，不是 performance evidence**——站级收益 / 储能补偿减少 /
>    主动重分配 / 真实 EMS request 语义均**未验证**（P-004 维持 D，E4.1 未过）。

## 1. 建议技术题名（备选）

- 主：**一种基于车辆充电响应证据支持状态的功率边界生成及控制权限切换方法**
- 场景版：**一种用于光储充站的基于车辆充电响应证据支持状态的功率边界生成与
  控制模式切换方法**

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

## 3. 核心技术机制（技术链）

```text
EVSE / CSMS 在线观测
        ↓
实际功率/电流历史 + 可得导引/允许电流 + 充电状态 + 数据可用性
        ↓
响应证据支持状态（response-evidence support state）
        ↓
短时功率边界生成模式选择
        ↓
（限制/降级/恢复）EMS 对该 EV / EV 池的控制权限
        ↓
protective / conservative boundary（证据不足时不盲信）
        ↓
新的实际响应反馈
        ↓
重新判断 → 保护降级 / 控制权限恢复
```

**关键技术术语（与 AGENTS.md 术语纪律对齐）**：

- **响应证据支持状态**：由在线实际响应历史（至少含响应变化特征，如近期实际功率波动/
  方差）与当前可得信息类型共同确定的状态，表示"当前功率能力假设有多少响应证据支持"。
  **三态（Phase 2 决策1 冻结）**：
  - **S1 response-supported**：当前证据足以采用响应/历史边界；
  - **S2 protective**：有历史，但证据不足以支持更积极控制 → 采用保护边界；
  - **S3 insufficient**：历史/数据本身不足 → conservative fallback。
  状态转移：S1⇄S2 由响应证据变化驱动，S3 靠数据补齐后离开。
- **短时功率边界生成模式**：根据支持状态选择的不同边界生成方式：
  - pilot-rich / 响应证据充分 → **response/history-derived boundary**；
  - current-only（无 pilot/BMS 能力信息）→ **history protective boundary**；
  - 历史证据不足 → **conservative fallback**（persistence / rolling quantile /
    保守上界）。
- **控制权限切换**：据所选边界限制 EMS 对车辆功率预算的处理权限——**不**无条件按
  "分配功率 − 实际功率"释放差值。概念保留于本交底；**CLAIM 1 正文采用技术化措辞**
  （功率边界的应用模式 / 功率调整约束等级 / 修正允许范围），避免被解读为管理规则
  （Phase 2 决策2 冻结）。
- **保护降级与响应恢复**（⚠ P2 后修正：**单向恢复**，非双向）：信息/历史不足 →
  保护性观测（PROTECTIVE / LOCKED）；当实测响应满足预定边界接触条件（actual 贴近
  boundary，连续若干 cycle）→ **单向恢复**至更高预算修正允许区间（NORMAL）。P2 实现
  中 `m3_recovered` 在 M3 段内单调，recovery 后不自动退回 PROTECTIVE（见
  `phase3_p2/state_machine.py`）。

## 4. 独立权利要求必要步骤（草案，六步骤）

1. 获取充电对象的实际充电电流/功率时序，以及可获得时的导引/允许电流、充电状态和
   数据可用性信息；
2. 根据至少实际响应历史的变化特征，形成当前充电对象的**响应证据支持状态**
   （三态：response-supported / protective / insufficient，Phase 2 决策1 冻结）；
3. 根据响应证据支持状态和当前可用信息类型，选择不同的**短时功率边界生成模式**；
4. 至少包括：响应信息较充分时使用 response/history-derived boundary；导引信息
   不可用时使用 history-derived protective boundary；历史证据不足时使用 conservative
   fallback；
5. 根据所选择的短时功率边界，确定针对所述充电对象的**功率调整约束等级**，以确定所述
   **功率边界的应用模式**并限制基于所述功率边界实施功率预算修正的**允许范围**；
   证据不足时该允许范围仅支持保护性使用，而非无条件根据"分配功率 − 实际功率"释放差值；
6. 当后续实际充电响应满足预定边界接触条件时，**单向恢复**所述功率调整约束等级 /
   预算修正允许区间（保护性降级后由实测响应驱动恢复；P2 实现为 M3 段内 `m3_recovered`
   单调，**非**双向降级↔恢复）。

## 5. 实施例证据（本项目数据）

| 证据 | 数据来源 | 证据级 | claim_id |
|---|---|---|---|
| 近期实际波动（recent_var）越高 → E1 响应证据密度越高，train/val/test 方向一致（0.0039→0.0261 / 0.0054→0.0331；test Q3,Q4>pooled） | A5 扩展审计（baseline `34f04f6`） | C（描述性假设，非已验证规则；P1 No-Go 后移出核心，仅作辅助） | C-007 |
| 三种真实信息条件分支存在：measured_pilot（caltech）/ current-only（jpl 约 90% 文件仅 current）/ 数据不足 | E0-Full 字段覆盖审计 + A5 | A/C | P-001 |
| 信息/历史不足 → 保护性观测（M4 LOCKED / M3 PROTECTIVE 不释放差值）；实测响应贴近边界 → 单向恢复 | P2 formal（jpl_test M4=0.0、M3 natural 1,060 会话） | C（STRONGLY SUPPORTED，natural traces） | P-003 |
| 预算修正动作允许区间 gate（权限等级编码为数值 action set → accept/clip，m2_cov=0.376743 实际生效） | P2 formal（K2/M2 PASS） | C（controller mechanism，**非效果声明**） | P-002 |
| active bounded correction（有界修正） | 审查结论52 降级 | D（opportunity 方向混合、caltech E3 formal FAIL；P2 后维持 D） | P-004 |

**不允许表述为已验证**：储能补偿减少、光伏消纳提高、闭环收益、站级经济效益
（对应 C-005/C-006/C-008~C-010 仍为 D 级）。

## 6. 与现有技术的区分要点（撰写时必须明确）

| 近邻 | 其触发/机制 | 本发明的区别 |
|---|---|---|
| Porsche US12054065B2 | 充电站/负载管理**系统故障** → dynamic/static load-management 切换 | 触发是**车辆实际响应行为/响应证据支持状态**，不是站/系统故障；且联动的是**车辆短时执行边界 + EMS 控制权限** |
| ChargePoint US10464435B2 | 基于**近期供电历史**响应 power-limit message | 本发明额外引入响应证据支持状态 → 边界模式选择 → 控制权限切换的链条；历史边界本身不单独成发明点 |
| ChargePoint US10150380B2 等族 | allocated 超过车辆能力 → 释放功率模块给其他 dispenser | "释放/重分配"是价值应用，非本发明创新点；本发明锚定响应证据支持状态与控制权限 |
| CN112829627A | 按车辆实际需求动态重分配多车功率 | 同上：重分配概念已有，非主权利要求 |
| US9290104B2 | 改变 pilot 前后读取功率、测量车辆响应 | "pilot 阶跃→测量响应"已有公开；本发明不主张"调 pilot 控功率"，而是响应证据状态→边界→权限 |

**可主张空间 = 上述已有要素之间的新技术关系组合**：
响应证据支持状态 → 边界生成方式 → 控制权限 → 保护降级/响应恢复。
该组合是后续专利检索最重点的攻击对象。

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

## 8. 遗留待确认事项（open questions，定稿前）

- 响应证据支持状态的离散化等级（支持/不确定/不足 vs 连续分数）与权利要求的
  概括层级选择；
- "控制权限"在权利要求中的落地措辞（限制处理权限 / 边界钳制 / 模式切换）以
  兼顾可读性与宽保护；
- 场站级汇总接口（EV 边界 → EV 功率预算 → PV/BESS/grid EMS）放在主权利要求
  还是从属/第二独立权利要求；
- 是否将 D2/D3 fusion 拆为第二独立权利要求族（信息条件分级 vs 场站/字段模式适用度）。
