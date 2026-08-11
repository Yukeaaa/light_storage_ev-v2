# P2 Preregistration v1.0 — 信息模式驱动的 EV 功率预算约束与响应恢复状态机回放验证

> 日期：2026-08-11（冻结）
> 依据：Patent Gate 2 FINAL = NARROW CONDITIONAL GO / HOLD P2
> （`results/raw/patent_gate2/patent_gate2_final.md`，commit `aeee71b`）。
> **本文件取代 `minimum_evidence_preregistration.md` §2 的旧 P2 骨架**（"JPL current-only 保护
> 实施例"），后者以性能/收益验证为目标，与 Gate 2 冻结的 D1/D2/D3 机制验证目标不一致。
> 冻结效力：本文件 + `configs/phase3_p2_action_schema.yaml` 同步冻结；任何改动须新版本 +
> 新测试协议。P2 是**机制成立率验证**，不是性能研究，更不是 active redistribution 回炉。
> 本文件不是法律意见。

---

## 0. 目的（一句话）

> 验证 D1/D2/D3 能否从专利文字变成**一条可观察、可复现、可由 EMS/EVSE 实际执行的控制动作
> 序列**。即："权限等级"是否是一个真实控制机制，而不是抽象措辞。

本实验**不回答**：节能、PV 消纳、BESS 收益、active redistribution 收益、任何经济指标。

---

## 1. Patent question（字段 1）

在给定同一实际充电响应轨迹时，系统是否：

```text
D1  按当前可用信息类别（capability / pilot+actual / current-only / 历史不足）
    确定性选择预定义的边界生成模式？
D2  把所选边界编码为对 EMS 功率预算修正动作 ΔP 的机器可执行允许区间
    （allowed_budget_correction_interval），并实际约束候选动作（accept/clip/reject）？
    且不同约束等级对应不同的允许区间？
D3  在保护性模式（PROTECTIVE）下持续观测实际响应，当预注册的物理条件成立时，
    改变允许区间（RECOVERY），且后续 EMS 命令被新区间约束——且该恢复不依赖
    通信恢复 / 停充 / 人为 reset？
```

## 2. Supported CLAIM(s)（字段 2）

- **CLAIM 1 第 3 步**（信息类别 → 边界生成模式选择）= D1；
- **CLAIM 1 第 4 步**（边界 → 功率调整约束等级 / 修正允许范围）= D2；
- **CLAIM 1 第 5/6 步**（保护性降级 + 实际响应驱动恢复）= D3；
- 从属：CLAIM 2（信息层级 → 模式选择规则）、CLAIM 3（current-only history protective
  boundary 实施）、CLAIM 4（历史不足 → conservative fallback）、CLAIM 5（响应证据 → 恢复）。

**明确不支持**：CLAIM 7（有界修正的收益）、CLAIM 8（场站 EMS 对接价值）、以及任何
"释放差值→重分配"主张。P2 只验证**动作集合不同且被约束**，不验证释放后收益。

## 3. Supported claim_id(s)（字段 3）

- **P-001**（信息条件 → 边界模式选择，D1）；
- **P-002**（boundary → 控制约束/权限 = D2，当前 D 级，本实验是它的测试）;
- **P-003**（信息不足 → 保守/保护性处理，D1 的 M4 分支 + D3 的 PROTECTIVE 态）；
- **C-012**（JPL current-only 边界方向弱证据，作为 M3 实施例的自然数据基础）。

**P-004 明确不映射**：P-004 = active bounded correction / CLAIM 8 未来验证；P2 禁止
active redistribution → **P2 不支撑 P-004**（沿袭 v1.0.1 的排除，防止 active correction
从后门回来）。

## 4. Input/data independence requirement（字段 4）

- **主实施例 = JPL current-only**（自然 M3 域：pilot 不可用 → history protective boundary →
  protective action set）。来源 = E0 冻结 1-min 会话表（`matched` 会话），不引入新数据工程。
- **信息面回放 = caltech（pilot-rich）**做 **mode-mechanism replay**：
  - mask pilot → M3（current-only 分支）；
  - truncate history（< min_samples）→ M4（conservative fallback）；
  - inject capability → M1（capability-rich 分支；ACN 数据天然无 capability，故 M1 只作
    **注入回放验证**，**协议必须明示这是 mode-mechanism replay，不是真实站点分布统计**）。
- **切分（先哈希）**：jpl train 拟合阈值、jpl test 单次暴露；office001 **external only**，
  禁止用其结果改任何阈值。
- **不触碰**：封存 test（E1/E3 formal 永不重跑）；P1 sentinel（已 consumed）；低覆盖/异常
  月份仅作敏感性（报告不入门）。
- **Step0 限制**：Step0 / K-gate 只读 jpl train + caltech train（mask replay）；
  **jpl test 的任何响应序列在正式单次暴露前不可读取**。

## 5. Frozen method（字段 5，全部细节冻结于本文件 + schema YAML）

### 5.1 状态机（会话内逐 1-min cycle 推进）

```text
UNASSESSED ──info_mode_lookup──▶ PROTECTIVE   （M3/M4 → SHRINK_ONLY）
    │
    └────────────info_mode_lookup──▶ NORMAL     （M1/M2 → BOUNDED_CORRECTION）

PROTECTIVE ──recovery_trigger（唯一恢复路径）──▶ NORMAL
NORMAL ──degrade_trigger（信息类别退化）──▶ PROTECTIVE
```

**禁止的切换**：PROTECTIVE→NORMAL 不得由通信恢复/停充解除/人为 reset/计时到期触发；
任何切换不得由 recent_var / confidence / classifier 驱动。

### 5.2 D1 — 信息类别 → 边界模式（确定性查表）

| info_mode | 判定条件 | boundary_mode |
|---|---|---|
| M1 capability-rich | capability 可用 | capability_supported_boundary |
| M2 pilot+actual | pilot + actual 可用 | response_history_boundary |
| M3 current-only | 仅 actual/current 历史 | history_protective_boundary |
| M4 history insufficient | 历史样本 < `min_history_samples` | conservative_fallback |

每 cycle 输出 `information_mode` / `boundary_mode` / `boundary_value` / `reason_code`
（见 schema）。选择规则**无拟合、无学习**，纯查表。

### 5.3 D2 — 约束等级 → 允许修正区间（机器可执行动作边界）

| 约束等级 | 状态 | allowed_delta_interval | action |
|---|---|---|---|
| protective | PROTECTIVE | `[-current_budget, 0]` | SHRINK_ONLY |
| supported | NORMAL | `[-current_budget, max(0, boundary_value - current_budget)]` | BOUNDED_CORRECTION |

- **protective 语义**：可收缩、可保持；**禁止**因 `allocated - actual > 0` 生成任何正向
  release（`release_source_forbidden = allocated - actual`）。
- **supported 语义**：上界由**边界支撑容量**决定，**不是** "分配功率 − 实际功率" 差值释放。
- 候选 EMS 预算修正量 ΔP 的约束方式（disposition）：

```text
requested ∈ [L, U]  → accepted       final = requested
requested > U       → clipped_upper  final = U      （PROTECTIVE 下即 blocked release）
requested < L       → clipped_lower  final = L
```

### 5.4 D3 — 恢复触发（物理、最简、预注册冻结）

```text
condition:  actual_power >= 0.95 * protective_bound
sustained:  连续 3 个 1-min cycle，同一 uninterrupted run
excluded triggers: 通信恢复 / 停充 / session reset / 计时到期
禁止（v1 第一版）: confidence score / variance+slope / classifier / 双时间尺度 /
                   learned recovery probability
```

**红线（沿用 Gate 2 纪律）**：如果这个最简物理触发无法产生可用 recovery trace，
**优先 No-Go，不加模型救场**。

### 5.5 完整 recovery trace（D3 设备动作证据，必须逐项可见）

```text
信息/历史不足 → PROTECTIVE → allowed correction = protective set
→ EVSE 持续返回 actual response
→ 预注册 positive-response / boundary-contact 条件成立
→ RECOVERY
→ before: allowed_delta = [...]  / after: allowed_delta = [...]（必须同时记录）
→ 后续至少一个 EMS budget command 使用新的 action bound（clipping/acceptance/rejection
  因新区间而不同，必须可观察）
```

### 5.6 主指标（机制成立率，非性能）

```text
M1  D1 branch realizability  信息类别 → 预定义 boundary_mode 确定性选择比例     目标 1.0
M2  D2 action-bound real.    有效 cycle 生成明确 allowed interval 并实际约束
                             候选动作的比例（requested ≠ final 或 requested 越界）目标 1.0
M3  D3 recovery trace count  完整自然 recovery trace 计数
                             （≥ 20 条 / ≥ 5 会话，AGENTS.md 失败案例抽样下限）
M4  unsupported-release      PROTECTIVE 下 allocated>actual 且 requested>0 时，
     prevention              正向 release（final>0）比例                           目标 0.0
```

> M1/M2/M4 是实现正确性（确定性），**目标即 1.0 / 0.0，不是统计显著性**；M3 是计数，
> 非推断。P2 不做 cluster bootstrap 推断——机制验证不需要，也不该伪装成性能结论。

### 5.7 Step0 kill gates（正式统计前，几十/几百条 replay traces，仅 train + mask replay）

```text
K1  信息面变化是否真的产生不同 boundary mode？   FAIL → D1 不成立 → STOP
K2  "权限等级"能否编码为数值 action set 并改变 accept/clip/reject？
                                                FAIL → PROJECT NO-GO（硬杀线）
K3  是否存在不依赖通信恢复/停充/reset、由实际充电响应触发的 recovery trace？
                                                FAIL → 极可能 PROJECT NO-GO
```

**K2 是硬杀线**，与 Patent Gate 2 冻结规则完全一致（D2 = 生死线）。

## 6. Success / Conditional / No-Go criteria（字段 6）

| 结果 | 判定 | 条件 |
|---|---|---|
| **Success** | 机制成立 | K1/K2/K3 全过；M1=1.0、M2=1.0、M4=0.0；M3 自然 recovery trace ≥ 20 条 / ≥ 5 会话；before/after 动作集变化全部记录；后续命令被新区间约束的实例 ≥ 1 条且可观察 |
| **Conditional** | 部分成立 | M1/M2/M4 正确但 M3 计数低于阈值（但 ≥ 5 条 / ≥ 2 会话，且轨迹结构完整）；或 M3 需要信息面回放（mask/inject）才能凑齐自然轨迹（此时须在报告中明确"依赖 replay"，不得声称全自然） |
| **No-Go** | 机制不成立 | K2 失败；或 M4 出现任何正向 release；或 M1/M2 确定性破坏（选择不唯一）；或 M3=0 且 Step0 判定 LIKELY_NO_GO；或 K1 失败导致 STOP 无法进入正式统计 |

**穷尽映射（不允许未定义分支）**：

```text
K1 FAIL → STOP（D1 不成立）→ 项目状态 = Project No-Go（组合核心缺失）
K2 FAIL → PROJECT NO-GO（权限只是抽象 wording，Gate 2 硬杀线）
K3 FAIL（0 条 recovery trace，含 replay 后）→ PROJECT NO-GO（D3 无设备闭环）
M4 违反（PROTECTIVE 出现 final>0）→ PROJECT NO-GO（技术问题本身不成立）
M3 计数 < 20 但 ≥ 5（且 M1/M2/M4 全过）→ Conditional（需追加自然轨迹或 replay 补强）
其余全过 → Success（NARROW GO 成立，进入 Claim v2 撰写）
```

## 7. Forbidden post-hoc actions（字段 7）

- 禁止把人工 mask/inject 回放当作**真实站点分布统计**；
- 禁止在 P2 内新发明 D3 trigger（confidence/variance+slope/classifier/双时间尺度/learned）；
- 禁止引入性能/收益指标（PV/BESS benefit、release 收益、经济指标）或借此宣称 active
  redistribution 成立；
- 禁止用 recent_var / S1/S2 作为状态判定（P1 排除项，Gate 2 维持）；
- 禁止在 jpl test 上逐图调参 / 重跑；禁止用 office001 改阈值；
- 禁止因 K2/K3 失败而"加模型救场"再重判（先走 No-Go，再按版本化协议变更）。

## 8. Patent consequence if failed（字段 8）

| 失败点 | 专利后果（从 CLAIM 删/改哪一句） | registry 降级 |
|---|---|---|
| K1（D1 不成立） | CLAIM 1 第 3 步"按信息类别选择边界生成方式"删除 → 退化为单一 protective 边界；组合核心缺失 → 极可能 Project No-Go | P-001 → D |
| **K2（D2 不成立）** | CLAIM 1 第 4 步"功率调整约束等级/修正允许范围"无法落设备动作 → **PROJECT NO-GO**（Gate 2 硬杀线） | P-002 → D（且确认 wording 级） |
| K3（D3 不成立） | CLAIM 1 第 6 步 / CLAIM 5"响应驱动恢复"删除 → 恢复仅剩通信/停充恢复（prior art 已覆盖）→ 极可能 Project No-Go | P-003 弱化 |
| M4 违反 | 技术问题本身不成立（保护模式仍释放未支持功率）→ Project No-Go | C-012 维持弱 |

**Success 后果**：P-001/P-002/P-003 升 C；CLAIM 1 v2 写成可执行技术链（见 §9）；
进入 patent_definition 撰写（P3 仍 BLOCKED，除非新授权）。

## 9. 成功后的目标 CLAIM 1 v2（撰写靶子，非本实验输入）

```text
获取当前可用充电信息
↓ 根据其信息类别选择边界生成处理分支（M1/M2/M3/M4 查表）
↓ 生成对应 EV 功率边界
↓ 根据边界形成 EV 功率预算修正允许区间（allowed_budget_correction_interval）
↓ 将 EMS 请求的预算修正量限制在该允许区间内（accept / clip / reject）
↓ 向调度/充电控制模块输出受限后的预算
↓ 持续取得实际充电响应
↓ 满足响应恢复条件（物理触发，预注册）
↓ 改变预算修正允许区间
↓ 后续 EMS 调整采用新的允许区间
```

> 这是与 ACN 最近邻（US10926659 / US20200254896A1）正面对比的**技术动作链**。生存空间
> 必须落在 Gate 2 冻结的三点组合：**信息类别驱动的 boundary-mode selection + budget-
> adjustment action set + actual-response-driven recovery**。

---

## 10. 交付物清单（P2 阶段）

```text
configs/phase3_p2_action_schema.yaml            本实验冻结（已提交）
reports/patent_definition/phase3_p2_preregistration_v1.0.md  本文件（已提交）
src/experiments/phase3_p2/                      【尚未授权】P2 implementation 需本协议评审后再开
results/raw/phase3_p2/                          【尚未授权】Step0 replay + formal 输出 + manifest
reports/patent_definition/phase3_p2_gate.md     【尚未授权】门报告（8 字段 + Step0 结果 + 判定）
```

**P2 implementation 开闸前置**：本协议 + schema 通过 Review 冻结 → 才可写回放代码；
Step0 结果先于 formal test 评审 → 才可单次暴露 jpl test。

## 11. 变更控制

- 本文件 = **P2 preregistration v1.0（冻结）**；schema = 同步冻结。
- 任何改动（含 D3 触发阈值 0.95 / K=3、`min_history_samples`、quantile、窗口）须新版本 +
  新测试协议，走与 evidence freeze 相同的 Review 链；**test 暴露后零改动**。
- 本文件不是法律意见；最终以专利代理师出具的意见为准。
