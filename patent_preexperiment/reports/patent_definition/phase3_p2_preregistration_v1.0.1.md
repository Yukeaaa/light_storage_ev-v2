# P2 Preregistration v1.0.1 — 信息模式驱动的 EV 功率预算约束与响应恢复状态机回放验证

> 日期：2026-08-11（v1.0.1 冻结，Review 66 修复后）
> 依据：Patent Gate 2 FINAL = NARROW CONDITIONAL GO / HOLD P2
> （`results/raw/patent_gate2/patent_gate2_final.md`，commit `aeee71b`）；
> **Review 66 = CONDITIONAL FAIL**（Executable freeze 存在 P0 blockers）。
> 本文件取代 v1.0（`minimum_evidence_preregistration.md` v1.1 changelog 已登记重定义），
> v1.0.1 逐项封死 Review 66 的 P0/P1 接口闭环。
> 冻结效力：本文件 + `configs/phase3_p2_action_schema.yaml`（v1.0.1）同步冻结；任何改动须
> 新版本 + 新测试协议。P2 是**机制成立率验证**，不是性能研究，更不是 active redistribution
> 回炉。本文件不是法律意见。

---

## 0. v1.0.1 changelog（Review 66 修复清单，全部冻结）

```text
P0-1  D2 动作输入来源封死：controller-conformance replay + 外生 budget/probe 规则
      （禁止按 [L,U] 反向生成 probe）；M2 语义 = final==clip(requested,L,U) 且 disposition
      唯一，不再要求"每 cycle 都 requested!=final"（约束是否生效改列为描述性 M2_cov）。
P0-2  三层解耦：information_mode → boundary_mode 固定映射；application_state 独立变化。
      M3 recovery 后仍用 history_protective_boundary，仅提升权限等级（PROTECTIVE→NORMAL）。
      M4 = LOCKED/[0,0] 唯一化；M4 无 protective_bound，不得直接触发 D3。
P0-3  D1 查表改为穷尽 precedence：capability 优先；history-insufficient 只作用于
      pilot/actual 派生分支；任何未覆盖组合 fail-closed → M4。
P0-4  D3 因果化：protective_bound(t) 只用 <t 数据（shift(1)），绑定 E0 actual_power_kw /
      severe_gap_before；protective_bound<=0 禁止恢复；0.95 与连续 3 cycle 数值不变。
P0-5  M1/M2 本轮只验证 branch dispatch，不参与 D2/D3 数值门；D2/D3 自然 embodiment 只在
      M3/M4 上验证（capability 注入值与 response_history 算法不冻结为数值规则）。
P1-1  Step0 用全部冻结 JPL train + 固定 Caltech replay（不挑样本）；Success ≥20 traces /
      ≥5 sessions 必须是 natural JPL；replay 单列辅助，不计入自然轨迹；JPL current-only
      test 域曾被 E3 分析 → P2 只声称 outcome single exposure，不得声称"未分析过的独立 test"。
P1-2  继承 P1 fail-closed 治理：code SHA + protocol/schema SHA + clean worktree + sentinel；
      sentinel 一旦存在，任何 status 均消费 P2 exposure。
fix   accept/clip/reject 统一为 accepted / clipped_upper / clipped_lower，删除 reject。
fix   K3 出口唯一化为 PROJECT_NO_GO（Step0 与穷尽映射一致，删除 LIKELY_PROJECT_NO_GO）。
```

> v1.0.1 **未改动**以下冻结数值：`0.95 × protective_bound`、连续 3 cycle、15 min / Q95 /
> `min_history_samples=5`；recent_var/classifier 等救场继续禁止；性能、PV/BESS、active
> redistribution 继续排除。本轮只把"已冻结的机制"写成唯一可执行语义，不重新设计科学模型。

---

## 0. 目的（一句话，沿袭 v1.0）

> 验证 D1/D2/D3 能否从专利文字变成**一条可观察、可复现、可由 EMS/EVSE 实际执行的控制动作
> 序列**。即："权限等级"是否是一个真实控制机制，而不是抽象措辞。

本实验**不回答**：节能、PV 消纳、BESS 收益、active redistribution 收益、任何经济指标。

---

## 1. Patent question（字段 1，沿袭 v1.0）

在给定同一实际充电响应轨迹时，系统是否：

```text
D1  按当前可用信息类别（capability / pilot+actual / current-only / 历史不足）确定性选择
    预定义的边界生成模式（穷尽 precedence 查表，fail-closed → M4）？
D2  把所选边界编码为对 EMS 功率预算修正动作 ΔP 的机器可执行允许区间
    （allowed_budget_correction_interval），并实际约束候选动作（accepted / clipped_upper /
    clipped_lower）？且不同约束等级对应不同的允许区间？
D3  在保护性模式（PROTECTIVE）下持续观测实际响应，当预注册的物理条件成立时，改变允许
    区间（RECOVERY → NORMAL），且后续 EMS 命令被新区间约束——该恢复不依赖通信恢复 /
    停充 / 人为 reset，且 protective_bound 只用当前 cycle 之前的数据（因果化）？
```

## 2. Supported CLAIM(s)（字段 2，沿袭 v1.0）

- **CLAIM 1 第 3 步**（信息类别 → 边界生成模式选择）= D1；
- **CLAIM 1 第 4 步**（边界 → 功率调整约束等级 / 修正允许范围）= D2；
- **CLAIM 1 第 5/6 步**（保护性降级 + 实际响应驱动恢复）= D3；
- 从属：CLAIM 2（信息层级 → 模式选择规则）、CLAIM 3（current-only history protective
  boundary 实施）、CLAIM 4（历史不足 → conservative fallback）、CLAIM 5（响应证据 → 恢复）。

**明确不支持**：CLAIM 7（有界修正的收益）、CLAIM 8（场站 EMS 对接价值）、以及任何
"释放差值→重分配"主张。P2 只验证**动作集合不同且被约束**，不验证释放后收益。

## 3. Supported claim_id(s)（字段 3，沿袭 v1.0）

- **P-001**（信息条件 → 边界模式选择，D1）；
- **P-002**（boundary → 控制约束/权限 = D2，当前 D 级，本实验是它的测试）；
- **P-003**（信息不足 → 保守/保护性处理，D1 的 M4 分支 + D3 的 PROTECTIVE 态）；
- **C-012**（JPL current-only 边界方向弱证据，作为 M3 实施例的自然数据基础）。

**P-004 明确不映射**：P-004 = active bounded correction / CLAIM 8 未来验证；P2 禁止
active redistribution → **P2 不支撑 P-004**（沿袭 v1.0.1 的排除，防止 active correction
从后门回来）。

## 4. Input/data independence requirement（字段 4，v1.0.1 修订 P1-1）

- **主实施例 = JPL current-only**（自然 M3 域）。来源 = E0 冻结 1-min 会话表
  （`matched` 会话，`actual_power_kw` = measured→computed→estimated），不引入新数据工程。
- **信息面回放 = caltech（pilot-rich）**做 **mode-mechanism replay**（单列辅助）：
  - mask pilot → M3（current-only 分支）；
  - truncate history（< min_history_samples）→ M4（conservative fallback）；
  - inject capability（`injection_value_kw=7.2` 固定标量）→ M1（capability-rich 分支）。
  **协议明示：这是 mode-mechanism replay，不是真实站点分布统计；replay 结果不计入
  natural recovery trace（M3 指标）。**
- **切分（先哈希）**：jpl train 拟合、jpl test 单次暴露；office001 **external only**，
  禁止用其结果改任何阈值。
- **test 域状态声明（P1-1）**：JPL current-only test 域此前已用于 E3 分析。P2 **只声称
  "P2 outcome 单次暴露（single exposure）"**，**不得**声称"从未分析过的独立 test"。
- **不触碰**：封存 test（E1/E3 formal 永不重跑）；P1 sentinel（已 consumed）；低覆盖/异常
  月份仅作敏感性（报告不入门）。
- **Step0 限制（P1-1）**：Step0 / K-gate 使用**全部冻结 JPL train + 固定 Caltech replay**
  （precedence/阈值/指标下明确定义，**不挑样本**）；jpl test 任何响应序列在正式单次暴露前
  不可读取。

## 5. Frozen method（字段 5，v1.0.1 核心修订）

### 5.1 三层解耦（P0-2）

```text
Layer 1  information_mode  ∈ {M1, M2, M3, M4}          —— 每 cycle 由可用信息决定（确定性）
Layer 2  boundary_mode     —— information_mode 的固定映射（不随状态变化）
Layer 3  application_state ∈ {LOCKED, PROTECTIVE, NORMAL} —— 独立变化
```

| information_mode | boundary_mode | 默认 application_state | 说明 |
|---|---|---|---|
| M1 capability-rich | capability_supported_boundary | NORMAL | dispatch-only（无真实 capability 数据） |
| M2 pilot+actual | response_history_boundary | NORMAL | dispatch-only（v1.0.1 不冻结数值算法） |
| M3 current-only | history_protective_boundary | PROTECTIVE | D2/D3 自然 embodiment |
| M4 history insufficient | conservative_fallback | LOCKED | 无 protective_bound；[0,0] |

**状态转换（唯一路径）**：

```text
LOCKED ──info_mode_change（M4→M3，历史达 min_samples）──▶ PROTECTIVE
PROTECTIVE ──recovery_trigger（D3，仅 M3+PROTECTIVE）──▶ NORMAL      [boundary_mode 不变]
NORMAL ──degrade_trigger（信息退化，如 M2→M3 / M1→M3）──▶ PROTECTIVE
NORMAL ──info_mode_change（退化到 M4）──▶ LOCKED
```

- **M3 recovery 语义（P0-2 关键）**：recovery 只提升 application_state（PROTECTIVE→NORMAL），
  **boundary_mode 仍是 history_protective_boundary**；NORMAL 的允许区间用**同一个
  history_protective_boundary 值**计算 `max(0, boundary - budget)`，绝不"神奇变成 M1/M2"。
- **M4 不得直接触发 D3**：M4 无 protective_bound（`boundary_value=null`）；M4 必须先经
  `info_mode_change`（历史达 min_history_samples）→ M3+PROTECTIVE，才具备 D3 触发资格。
- **禁止的切换**：PROTECTIVE→NORMAL 不得由通信恢复/停充解除/人为 reset/计时到期触发；
  任何切换不得由 recent_var / confidence / classifier 驱动。

### 5.2 D1 — 穷尽 precedence 查表（P0-3）

从第一条命中的规则起判（互斥、穷尽；任何未覆盖组合 fail-closed → M4）：

```text
1. capability_available == true                                → M1
2. pilot_available AND actual_available AND history_sufficient → M2
3. pilot_available AND actual_available                        → M4   （历史不足）
4. actual_available AND history_sufficient                     → M3
5. actual_available                                            → M4   （历史不足）
6. else                                                        → M4   （fail-closed）
```

- **capability 优先**：capability=true 即 M1，独立于 history 充分性（capability 是独立证据，
  不依赖历史）。capability=true 但 pilot=false → 规则 1 命中 → M1。
- **history 充分性**：当前 cycle 之前、同一 run 内、非 severe_gap 的 `actual_power_kw`
  非空样本数 `>= min_history_samples(=5)`。history-insufficient **只**作用于 pilot/actual
  派生分支（M2/M3）。
- 每 cycle 输出 `information_mode` / `boundary_mode` / `reason_code`（命中规则号），
  纯查表、无拟合、无学习。

### 5.3 D2 — 动作输入来源（P0-1，controller-conformance replay）

ACN 无真实 EMS budget/request 字段 → 诚实定义为 **controller-conformance replay**：

```text
current_budget_source   B(t) = 3.0 + 1.5 * (md5hex(session_id)首字节 mod 4)   # {3.0,4.5,6.0,7.5} kW
requested_delta_source  probe(t) = grid[(cycle_index + md5hex(session_id)首字节 mod 5) mod 5]
                        grid = [-3.0, -1.5, 0.0, +1.5, +3.0] kW
allocated              allocated == current_budget（同一变量，不独立存在）
独立审计                probe/budget 生成不得读取 boundary_value / allowed interval /
                        actual_power_kw / application_state / outcome；实现记录 probe_seed/budget_seed
```

**红线（P0-1）**：禁止按 `[L,U]` 反向生成 probe 来"做出 1.0"；probe 与 boundary/state/
outcome 完全外生。

### 5.4 D2 — 约束等级 → 允许修正区间（按 application_state 唯一化）

| application_state | allowed_delta_interval | action |
|---|---|---|
| LOCKED（M4） | `[0.0, 0.0]` | NO_CORRECTION |
| PROTECTIVE（M3 默认） | `[-current_budget, 0.0]` | SHRINK_ONLY |
| NORMAL（M1/M2 默认；M3 recovery 后） | `[-current_budget, max(0.0, boundary_value - current_budget)]` | BOUNDED_CORRECTION |

- **LOCKED 与 PROTECTIVE 唯一化（P0-2）**：M4=`[0,0]`（禁止任何修正），不再与 PROTECTIVE
  的 `[-budget,0]` 混写。
- **PROTECTIVE 语义**：可收缩、可保持；**禁止**因 `allocated - actual > 0` 生成任何正向
  release（`release_source_forbidden = allocated - actual`）。
- **NORMAL 语义**：上界由**边界支撑容量**决定，**不是** "分配功率 − 实际功率" 差值释放。
- 候选动作唯一 disposition（fix：无 reject）：

```text
L <= requested <= U  → accepted        final = requested
requested > U        → clipped_upper   final = U     （PROTECTIVE 下即 blocked release）
requested < L        → clipped_lower   final = L
```

### 5.5 D3 — 恢复触发（物理、最简、因果化；P0-4）

```text
condition:  protective_bound > 0  AND  actual_power_kw >= 0.95 * protective_bound
sustained:  连续 3 个 1-min cycle，同一 run（数值不变）
causality:  protective_bound(t) 只用 <t 数据（shift(1)，窗口 15min/Q95/min_samples=5）；
            actual_power_kw(t) 为当前 cycle 实测
zero_guard: protective_bound <= 0 不得触发（排除 0 >= 0.95*0 自动恢复）
绑定字段:   actual_power_kw（E0 冻结，measured→computed→estimated）、
            severe_gap_before / gap_before_min（run 与 reset 语义）、
            pilot_available / pilot_power_kw（E0 冻结）
excluded:   通信恢复 / 停充 / session reset / 计时到期
禁止(v1):   confidence score / variance+slope / classifier / 双时间尺度 / learned probability
红线:        若最简物理触发无法产生可用 recovery trace → 优先 No-Go，不加模型救场
```

### 5.6 完整 recovery trace（D3 设备动作证据，必须逐项可见）

```text
信息/历史不足(M4) → info_mode_change → M3+PROTECTIVE → allowed correction = protective set
→ EVSE 持续返回 actual response
→ 预注册 positive-response / boundary-contact 条件成立（protective_bound>0 且因果化成立）
→ RECOVERY（application_state → NORMAL，boundary_mode 仍 history_protective_boundary）
→ before: allowed_delta = [...]  / after: allowed_delta = [...]（必须同时记录）
→ 后续至少一个 EMS budget command 使用新的 action bound（accepted/clip 因新区间而不同）
```

> M4→M3 是**信息驱动**转换（历史积累），**不是** D3 recovery，不得计入 M3 计数。

### 5.7 主指标（机制成立率；P0-1 修正 M2 语义）

```text
M1     D1 branch realizability  按 precedence 查表，全部 cycle 得到唯一 info_mode/boundary_mode
                                （含 M1/M2 dispatch + M3/M4 数值）             目标 1.0
M2     D2 action-bound real.    M3/M4 数值 cycle 上 final_delta == clip(requested,L,U)
                                且 disposition 与唯一规则一致                    目标 1.0
M2_cov 描述性                   clip 实际生效（requested != final）的 cycle 占比   报告不入门
M3     D3 recovery trace count  完整 natural recovery trace 计数（natural JPL test）
                                ≥ 20 traces / ≥ 5 sessions                       门
M4     unsupported-release      PROTECTIVE cycle 中 final_delta > 0 的比例
     prevention                （clip_upper 到 0 不算 release）                   目标 0.0
```

> M1/M2/M4 是实现正确性（确定性/符合性），目标即 1.0 / 0.0，非统计显著性；M3 是计数，
> 非推断。P2 不做 cluster bootstrap 推断——机制验证不需要，也不伪装成性能结论。

### 5.8 Step0 kill gates（P1-1：全部冻结 JPL train + 固定 Caltech replay，不挑样本）

```text
K1  信息面变化是否真的产生不同 boundary mode？（precedence 穷尽查表确定性）
                                    FAIL → D1 不成立 → STOP
K2  "权限等级"能否编码为数值 action set 并改变 accept/clip？（外生 probe replay）
                                    FAIL → PROJECT NO-GO（硬杀线）
K3  是否存在不依赖通信恢复/停充/reset、由实际充电响应触发的 natural recovery trace（JPL train）？
                                    FAIL → PROJECT NO-GO（出口唯一化）
```

**K2 是硬杀线**，与 Patent Gate 2 冻结规则完全一致（D2 = 生死线）。

## 6. Success / Conditional / No-Go criteria（字段 6）

| 结果 | 判定 | 条件 |
|---|---|---|
| **Success** | 机制成立 | K1/K2/K3 全过；M1=1.0、M2=1.0、M4=0.0；M3 **natural JPL** recovery trace ≥ 20 条 / ≥ 5 sessions；before/after 动作集变化全部记录；后续命令被新区间约束的实例 ≥ 1 且可观察 |
| **Conditional** | 部分成立 | M1/M2/M4 正确但 M3 natural JPL 计数低于阈值（5–19 条，且轨迹结构完整）；replay 辅助证据可补强但**不得冒充 natural 计数** |
| **No-Go** | 机制不成立 | K2 失败；或 M4 出现任何正向 release；或 M1/M2 确定性破坏（查表不唯一）；或 M3 natural=0；或 K1 失败导致 STOP 无法进入正式统计 |

**穷尽映射（不允许未定义分支）**：

```text
K1 FAIL → STOP（D1 不成立）→ Project No-Go（组合核心缺失）
K2 FAIL → PROJECT NO-GO（权限只是抽象 wording，Gate 2 硬杀线）
K3 FAIL（JPL train 0 natural trace，含 replay 后）→ PROJECT NO-GO（D3 无设备闭环）
M4 违反（PROTECTIVE 出现 final_delta>0）→ PROJECT NO-GO（技术问题本身不成立）
M3 natural < 20 但 ≥ 5（且 M1/M2/M4 全过）→ Conditional（追加 natural 或 replay 补强，
   但 replay 单列、不计入 natural 阈值）
其余全过 → Success（NARROW GO 成立，进入 Claim v2 撰写）
```

## 7. Forbidden post-hoc actions（字段 7，v1.0.1 增加）

- 禁止把人工 mask/inject 回放当作**真实站点分布统计**；禁止用 replay 结果"凑"natural 计数；
- 禁止在 P2 内新发明 D3 trigger（confidence/variance+slope/classifier/双时间尺度/learned）；
- 禁止按 `[L,U]` 反向生成 probe 来"做出" K2/M2；
- 禁止引入性能/收益指标（PV/BESS benefit、release 收益、经济指标）或借此宣称 active
  redistribution 成立；
- 禁止用 recent_var / S1/S2 作为状态判定（P1 排除项，Gate 2 维持）；
- 禁止在 jpl test 上逐图调参 / 重跑；禁止用 office001 改阈值；
- 禁止因 K2/K3 失败而"加模型救场"再重判（先走 No-Go，再按版本化协议变更）。

## 8. Patent consequence if failed（字段 8，沿袭 v1.0）

| 失败点 | 专利后果（从 CLAIM 删/改哪一句） | registry 降级 |
|---|---|---|
| K1（D1 不成立） | CLAIM 1 第 3 步"按信息类别选择边界生成方式"删除 → 退化为单一 protective 边界；组合核心缺失 → 极可能 Project No-Go | P-001 → D |
| **K2（D2 不成立）** | CLAIM 1 第 4 步"功率调整约束等级/修正允许范围"无法落设备动作 → **PROJECT NO-GO**（Gate 2 硬杀线） | P-002 → D（且确认 wording 级） |
| K3（D3 不成立） | CLAIM 1 第 6 步 / CLAIM 5"响应驱动恢复"删除 → 恢复仅剩通信/停充恢复（prior art 已覆盖）→ 极可能 Project No-Go | P-003 弱化 |
| M4 违反 | 技术问题本身不成立（保护模式仍释放未支持功率）→ Project No-Go | C-012 维持弱 |

**Success 后果**：P-001/P-002/P-003 升 C；CLAIM 1 v2 写成可执行技术链（见 §9）；
进入 patent_definition 撰写（P3 仍 BLOCKED，除非新授权）。

## 9. 成功后的目标 CLAIM 1 v2（撰写靶子，非本实验输入；沿袭 v1.0）

```text
获取当前可用充电信息
↓ 根据其信息类别选择边界生成处理分支（M1/M2/M3/M4 穷尽 precedence 查表）
↓ 生成对应 EV 功率边界（M3/M4 为自然 embodiment：history_protective_boundary）
↓ 根据边界形成 EV 功率预算修正允许区间（allowed_budget_correction_interval）
↓ 将 EMS 请求的预算修正量限制在该允许区间内（accepted / clipped_upper / clipped_lower）
↓ 向调度/充电控制模块输出受限后的预算
↓ 持续取得实际充电响应（actual_power_kw，因果化 shift(1)）
↓ 满足响应恢复条件（物理触发：protective_bound>0 且 actual >= 0.95×boundary，连续 3 cycle）
↓ 改变预算修正允许区间（application_state → NORMAL，boundary_mode 不变）
↓ 后续 EMS 调整采用新的允许区间
```

> 这是与 ACN 最近邻（US10926659 / US20200254896A1）正面对比的**技术动作链**。生存空间
> 必须落在 Gate 2 冻结的三点组合：**信息类别驱动的 boundary-mode selection + budget-
> adjustment action set + actual-response-driven recovery**。

---

## 10. 交付物清单（P2 阶段）

```text
configs/phase3_p2_action_schema.yaml            本实验冻结（v1.0.1，已提交）
reports/patent_definition/phase3_p2_preregistration_v1.0.1.md  本文件（v1.0.1，已提交）
src/experiments/phase3_p2/                      【尚未授权】P2 implementation 需 Review 67 通过
results/raw/phase3_p2/                          【尚未授权】Step0 replay + formal 输出 + manifest
reports/patent_definition/phase3_p2_gate.md     【尚未授权】门报告（8 字段 + Step0 结果 + 判定）
```

**P2 implementation 开闸前置**：本协议（v1.0.1）+ schema 通过 **Review 67**（只核接口闭环）
→ 才可写回放代码；Step0 结果先评审 → 才可单次暴露 jpl test。

## 11. 变更控制

- 本文件 = **P2 preregistration v1.0.1（冻结）**；schema = 同步冻结。v1.0 由 git 历史保留。
- 任何改动（含 D3 触发阈值 0.95 / K=3、min_history_samples、quantile、窗口、probe 网格）须
  新版本 + 新测试协议，走与 evidence freeze 相同的 Review 链；**test 暴露后零改动**。
- 本文件不是法律意见；最终以专利代理师出具的意见为准。
