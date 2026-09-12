# A 工程架构与设备适配层 V0.3（按"真实站可运行"标准的工程修订）

- 日期：2026-09-12
- 状态：**四个 HIL 前工程阻断项全部在软件侧关闭**；生产工程架构 = **CONDITIONAL PASS → （软件侧）PASS**；真实站闭环有效性**仍未验证**。
- 前序：`A_算法原型与可控真值场景台_V0.2.md`（V0.2 PRE-FREEZE CLOSED）。
- 评审输入：2026-09-12 工程落地性复审（"如果明天装到工商业光储充站里能不能跑"）。
- **口径声明（不变）**：全部产出为合成场景机制验证，非效果结论；**A-M3–M6 = UNVALIDATED、Round 5 = NOT STARTED、core-patent = NO-GO 不变**；专利文本保持冻结——本版全部为工程内部表示与工程层能力升级，不动权项语言（评审确认：`[Pmin,Pmax]` 与通道解耦均不需要推翻权项）。

---

## 1. 评审结论与四阻断项对照

评审判定：专利机制可实施性 PASS、软件机制原型 PASS、生产工程架构 CONDITIONAL PASS；正式 HIL 前需关闭四项。本版处置：

| # | 阻断项 | 处置 | 位置 |
|---|---|---|---|
| 1 | 资源能力模型：`bidirectional` 布尔 → 动态 `[Pmin, Pmax]` + 运行点 headroom | ✅ 已实现 | `types.ResourceSpec`、`gap_carrier.feasible_headroom`、配置 site |
| 2 | 控制链数据：requested / accepted / applied / measured 四层留痕 | ✅ 已实现（合成层） | `Obs.p_cmd_requested/p_cmd_accepted/reported_limit_active`、场景 S10 |
| 3 | 站级闭环：能力证据通道与 PCC 站级残差通道解耦 | ✅ 已实现 | PCC 独立表计观测行、模块 6 `pcc_fallback`、场景 S11、`A_sup` |
| 4 | Device Adapter：按资源类别定义可读/可写字段、周期、超时、clamp、ack、fallback | ✅ 规范已成文（本文 §5）；代码在 HIL adapter 阶段落地 | 本文 §5 / §6 |

## 2. 四层目标生产架构（评审 §1）与现模块映射

```text
离散证据门          —— 哪些证据可信、当前是什么工况     → 模块 1 attribution（if/else 只住在这里）
能力观察器          —— 持续能力边界 + 可信度 + 迟滞      → 模块 2 capability + 模块 5 写回/恢复
连续可行域 / 承接    —— 每个资源还能上/下调多少、怎么分   → 模块 3/4（V0.3 起基于 [Pmin,Pmax] 区间）
执行与反馈          —— 下发 → 实际响应 → 修正能力知识    → 模块 5 写回 + 模块 6 监督层
```

承接算法的工程演进位：主实验保持**确定性排序**（最大可承接贡献 + tie-break，专利的"简单实施方式"锚点）；生产可在同一可行域接口上替换为小型 LP/QP（目标：缺口加权的偏差最小 + 调节量惩罚 + 低置信度惩罚，约束：区间 + 爬坡 + SOC + 温度 + 模式）。**专利价值不押在排序算法上，押在能力状态如何产生、维护、进入下一次承接、反馈如何写回。**

## 3. 阻断项 1：动态可行功率区间（已实现）

**模型**：资源调节能力统一为 `P ∈ [p_min, p_max]`（站级符号），在**当前运行点**上算 headroom：

```text
p_max_eff = min(p_max,  up_bound_learned)    （物理 ∩ 执行学习）
p_min_eff = max(p_min, -down_bound_learned)
H_up = p_max_eff − P_meas                    （向上 / 减吸收）
H_down = P_meas − p_min_eff                  （向下 / 减注入）
```

| 资源 | p_min | p_max | 上向贡献来源 |
|---|---|---|---|
| BESS | −充电上限 | +放电上限 | 增出力 / 减充电 |
| PV | 0（或最小出力） | 当前可用光伏功率 | 解除限发（仅当主动限发且资源存在） |
| 普通充电桩 | −最大充电功率 | 0 | **减少吸收**（−25 → −5 即上向 +20） |
| V2G | −最大充电功率 | +最大放电功率 | 双向（第一轮工程验证不依赖） |

- SOC 工作区约束只施加于 `kind == "bess"`（充电负荷 / PV 不适用站级 SOC 占位语义）。
- **新证据（S9，跨事务复用）**：T2 缺口下，完整 A 经 R2 减吸收承接（bad_cmd=0）；A_no_state 按额定能力先派 R0（bad_cmd=0.19）。区间模型使"缺口交给其他资源"覆盖到单向负荷。
- `bidirectional` 降级为兼容别名（区间是否横跨 0），不再是承接资格判据。

## 4. 阻断项 2 + 3：命令链四层留痕 与 双通道解耦（已实现）

### 4.1 命令链四层

```text
P_plan → P_cmd_requested（EMS 欲下发）→ P_cmd_accepted（网关/本地控制器翻译接受）→ P_meas（实测）
```

`Obs` 新增 `p_cmd_requested` / `p_cmd_accepted` / `reported_limit_active`。**关键语义**：本地 BMS/PCS 裁剪（accepted < requested）时，设备执行的是 accepted——不构成执行偏差证据（新归因判据 4b'：`REPORTED_LIMIT`，既不更新能力、也不入缺口来源；上报限值同时进入可行域的 **Reported 包络层**，见 §5.3）。HIL 数据合同必须含：`command_id`、`requested_setpoint`、`translated_setpoint`、`accepted/effective_setpoint`、`applied_at`、`override_source`、`override_reason`。

**证据（S10 上报型限值）**：窗口内 accepted=30 < requested=50 且实测=30——A 不收缩（无执行失败证据），B0 误当执行证据收缩（错误归因对照）。

### 4.2 能力证据通道 ⊥ 站级控制残差通道

```text
资源级 P_req/P_meas → 严格证据链 → capability_state     （有疑问宁可不更新）
站级目标 − PCC 独立实测 → control residual → 资源承接    （PCC 表计独立于资源通信）
```

实现：Simulator 输出 **PCC 独立表计观测行**（rid="PCC"，计划−实测，独立噪声，与资源通信状态无关）；模块 6 `pcc_fallback`（默认关闭，`A_sup` 开启）：残差超带持续确认 → 在**可行且通信有效且非显性失败**的资源中做 level-holding 承接；站级真实超发 → 释放。能力学习仍只走模块 1–2 严格通道，**监督层不更新能力状态**（共享基础设施定位，不进权项链路）。

**证据（S11 通信冻结 + 真实未执行并存）**：

| 策略 | EMUR | PCC 稳态残差 | 说明 |
|---|---|---|---|
| A（严格） | 0.00 | 7.58 | 不更新能力 ✓，站级缺口如实保留 |
| **A_sup** | **0.00** | **1.21** | 同样不更新能力 ✓，PCC 通道补上站级缺口 |
| B0 | 1.00 | 0.43 | 靠错误能力更新才补上（负对照） |

评审指出的洞（"设备失联 + 真没执行 + PCC 少了 50 kW，不能因此就不补"）已闭合：**能力认知归能力认知，站级补偿归站级补偿，二者在正常情况下互相验证。**

### 4.3 实现过程中逼出的三条工程纪律（已落入代码与测试）

1. **上报包络进可行域**：已上报限值的资源 headroom 按 accepted 封顶，防止"虚假 headroom"把修正量派给已被本地裁剪的资源；
2. **防抖**：后备需求变化未超判据带 → 维持现有承接，不逐步重选（防来回换手）；
3. **显性失败排除 + 写回同权**：后备派发同样登记 `_issued_at/_pending_wb`（每步重注册，对抗事务清理），已过响应观察窗仍超带欠交付的资源不再派发——监督层与归因通道共用权 7 的确认条件。

## 5. 阻断项 4：设备适配层与控制权边界（规范）

### 5.1 控制链定位（必须写进 HIL/工程方案）

```text
A 算法（监督控制层）→ 站级资源目标 / 修正量（request / target / limit）
  → Device Adapter（协议翻译）→ 本地 PCS / 逆变器 / 桩控制器（最终安全裁剪）→ 设备
```

A **不替代** BMS、PCS 内环、光伏保护、EVSE 安全控制、继电保护；**本地设备永远保留最终否决权**。这与权 11 把"功率控制要求"写为"目标值**或约束值**"天然兼容。硬边界（缺一不可）：

```text
不得关闭保护；不得越过本地 Pmin/Pmax；不得越过 SOC/温度/电流/电压限制；
不得超过爬坡率；必须有 command timeout；必须有 comm-loss fallback；必须有控制权仲裁；
必须保留原始指令与最终应用指令的完整日志（= 阻断项 2 的数据链）。
```

### 5.2 适配器字段合同（按资源类别）

| 条目 | BESS / PCS | PV / 逆变器 | EVSE（智能充电桩） |
|---|---|---|---|
| 必读 | P_meas、SOC、温度、充/放电限值、Pmin/Pmax、模式/故障/保护、心跳 | P_meas、当前可用功率（逆变器+辐照/估计）、限发状态、模式/保护 | P_meas、车辆需求/状态、桩/车协议允许功率、会话状态 |
| 必写 | 有功目标**或**功率上限（二选一按协议）、爬坡 | 限发上限 / 有功百分比 | 充电计划 / 电流或功率上限 |
| 控制周期 | 1–4 s（快速通道） | 5–30 s | 5–30 s 至分钟级（慢通道，OCPP Smart Charging 粒度；2.0.1 中为可选 profile，**不得默认可用**） |
| clamp 语义 | 本地 BMS/PCS 可裁剪 → 必须回读 accepted | 本地 MPPT/保护可裁剪 | 桩/车协商可裁剪 |
| ack / 超时 | 写点 ack + command timeout + comm-loss fallback（保持/安全位） | 同左 | SetChargingProfile ack + 会话级超时 |
| 响应窗 | 每设备 own T_resp（多速率） | 每设备 own T_resp | 每设备 own T_resp（慢一级） |

V2G：OCPP 2.1 / ISO 15118-20 协议层可行，但车+桩+EMS+并网保护全链支持不能作为默认前提——**专利可覆盖，第一轮工程验证不依赖**。

### 5.3 能力包络的四层装配（生产形态）

```text
P_eff = Physical（额定/温度/电流/电压/SOC/爬坡）
      ∩ Reported（BMS/PCS 上报的当前充放限值，= 阻断项 2 的 accepted 链）
      ∩ ExecutionLearned（A 的执行证据确认边界 —— 专利核心层）
      ∩ Service（服务约束：如充电用户离场时限、需求响应合同）
```

A 的技术位置：**不是替代 BMS 上报的 Pmax，而是额外维护一层 execution-confirmed capability**，并与 Reported 层取交。V0.3 原型已实现 Learned 层与 Reported 层的取交（上报包络进可行域）；Physical/Service 层在 HIL adapter 中落地。

### 5.4 多速率响应窗（评审 §8）

实验阶段 worst-case p95 + 统一窗仅用于机制隔离；生产按 `T_resp,i` 每设备 commissioning（阈值产生规则已支持 per-resource band，响应窗的 per-resource 化在 HIL 标定阶段启用：`response_window.rule` 逐资源落定）。

## 6. 首套台架（最低风险、最高信息量）

```text
2 台可控 PCS/BESS + PCC 独立电表 + 本地 EMS
跑通：真实 setpoint → 真实执行 → 能力归因 → 边界修正 → 另一 PCS 承接 → 反馈写回
```

跑通后依次接 PV（available power 估计）、再接充电桩（协议开放度）。**先验证 A 的核心，不先花时间解决第三方充电协议兼容。**

## 7. 能力边界（评审 §9，写入产品边界）

A 解决**当前时刻的功率能力**（秒级/十秒级/分钟级站级修正与重分配）；不承诺能量与时长（连续出力 X kW 多少分钟、EV 离场前充够）——那属于 **B 候选（站级时变灵活性包络 + 持续时长-能量耦合）** 的区域。产品架构分层：A = "现在真实能做多少"；B = "能持续多久、能承诺多少"。

## 8. 评审落地性打分对照（评审 §10）

| 场景 | 评审评分 | 本版变化 |
|---|---|---|
| BESS + BESS | 9/10 | 区间模型 + 命令链 + 解耦通道全部适用，适配层最薄 |
| BESS + PV | 8/10 | 区间模型原生支持 PV（p_min=0）；瓶颈 = available power 估计（HIL 数据合同） |
| BESS + 智能桩 | 7/10 | 区间模型使桩的"减吸收上向"成为一等公民（S9 已演示）；瓶颈 = OCPP 粒度 |
| 多资源多速率 | 7/10 | per-resource 窗口的规则位已留 |
| + V2G | 5–6/10 | 不变（第一轮不依赖） |

## 9. 质量门与留档

- pytest 全过（`tests/test_a_ev.py` 43 项，本次 +3：S10 上报限值非执行证据 / 命令链四层留痕 / S11 双通道解耦）；a_ev 包 ruff 0 错、mypy strict 11 文件 0 错。
- 三场景集重跑留档（config_hash=d44fe413…一致）：evaluation（12 场景 × 7 策略，新增 S10/S11/A_sup）、robustness（48 条件）、commissioning（p95=12 s，数值仍属候选）。
- 实现过程中修复三处监督层工程缺陷（§4.3），全部有对应行为变化与测试覆盖。

## 10. Open items

1. **HIL adapter 实现**（§5 规范 → 代码：BESS-PCS 先行）；
2. per-resource 响应窗的规则落定（HIL commissioning 阶段）；
3. Physical/Service 包络层接入（随 adapter）；
4. （评审提示的后续改进专利线，**未开新候选、不动第一波**）："设备级能力学习通道与站级残差闭环通道解耦"可作为一条独立改进申请线，登记时机与命名按候选池纪律另行决定。
