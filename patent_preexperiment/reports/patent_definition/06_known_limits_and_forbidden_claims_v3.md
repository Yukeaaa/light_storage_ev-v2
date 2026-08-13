# 06 已知限制与禁用表述 v3（E7-FAST）— 代理师必读

> 本文件明确哪些表述**不得**写入专利申请，哪些证据边界**必须**遵守。
> 违反这些限制将导致申请面临现有技术风险或证据不可信风险。
> 项目判定：**FILING GO / NARROW CLAIM STRATEGY**

---

## 1. 禁用表述（不得写入权利要求/说明书/效果段）

| 禁用表述 | 原因 | 正确替代 |
|---|---|---|
| "准确识别车辆最大充电能力" | Candidate 更保守非更准确；D2 Under 更大 | "更谨慎地限制未经真实历史支持的功率增加" |
| "精准预测车辆可吸收余量" | 未验证车辆真实最大能力 | "基于已观察实际响应支持水平限制上调" |
| "准确 SOC / 精确剩余需求" | ACN 无真实 SOC/remaining demand | 不主张 SOC/剩余需求准确性 |
| "真实工商业园区实测储能补偿降低 X%" | BESS/PCC 是混合回放非实测 | "混合回放结果表明储能临时补偿需求降低" |
| "真实园区节能率 / BESS 寿命提升" | 无真实园区经济/寿命数据 | 不主张经济收益/寿命 |
| "适用于所有车型/所有园区" | ACN 主要是 workplace charging | "所述控制规则在未参与规则确定的后续数据分区上仍保持效果方向" |
| "D3 recovery / Q95 触边恢复 / 单向恢复更高调整范围" | P2.1A formal FAIL，已删除 | "信息类别自然变化：重新获得 pilot → 按 M2 处理" |
| "recent_var / variance 状态判定" | P1 formal No-Go | 不使用方差状态判定 |
| "主动多车复杂重分配作为核心创新" | prior art 拥挤 + 证据不支持 | 不主张重分配为核心 |
| "需要 ML/RL 才有效" | 简单 baseline 已足够；ML 未超过 rolling | 不主张需 ML |
| "投影 / 权限"（术语）| 模糊；review §2 禁用 | "桩侧允许信息"、"预算修正允许区间" |
| "命令失败 / 拒绝"（术语）| AGENTS.md 红线 | "导引/允许电流与实际响应差异" |
| "可回收能力"（术语）| AGENTS.md 红线 | "预算差值"（仅观察值）|

---

## 2. 证据边界（必须遵守）

### 2.1 真实数据 vs 混合回放

| 数据 | 证据类型 | 表述边界 |
|---|---|---|
| EV pilot / actual / 历史响应 / 自然 pilot step | **REAL**（ACN 真实时序）| 可称"真实充电数据验证" |
| 园区 PV / 基础负荷 | SYNTHETIC / ENGINEERING | 必须称"工程场景/模型" |
| BESS SOC / 功率 / 效率 | ENGINEERING | 必须称"工程参数模型" |
| PCC / 变压器 | ENGINEERING | 必须称"场景参数" |
| EMS 需求 | SYNTHETIC_CONTROLLER | = delta_pilot_kw，独立于方案 |
| **系统层效果（shortfall/BESS/PCC）** | **混合回放** | **必须称"混合回放结果"**，不得称"实测" |

### 2.2 关键句子模板

**可以写**：
> "基于真实电动汽车充电时序数据的混合回放验证表明，所述控制规则相比仅基于历史实际响应的
> 单一限制，能减少超过真实事件后续响应支持的电动汽车功率上调量，并进一步减少模型中的
> 储能临时补偿需求和电网接口剩余功率偏差。"

**不可以写**：
> "真实工商业园区实测储能补偿降低 41%。"
> "本发明准确识别车辆最大充电能力。"
> "适用于所有 DC 快充/所有 BMS/所有工业园。"

---

## 3. Claim 范围限制

### 3.1 主 Claim 必须保持窄而具体

- **不**写"一种光储充联合功率优化方法"（宽泛，prior art 拥挤）
- **不**把 `min(pilot,Q95)` 单独当作创造性来源（易被拆成常规组合）
- **保护**：D+E+G+H 组合（双重共同约束 + 信息不足 fail-closed + 园区需求-能力差执行 + 剩余交 BESS/PCC）

### 3.2 具体参数放从属

以下放 Claim 3/4 从属，**不**入 Claim 1：
- 15min 窗口
- Q95 分位
- 5 样本下限
- max(actual, min(pilot, Q95)) 公式
- SOC 具体区间
- BESS 功率比例
- 5min 响应评价

### 3.3 仅从属权利要求

| Claim | 原因 |
|---|---|
| Claim 7（capability）| ACN 无真实 BMS capability，无数据验证 |
| Claim 12（变压器场景）| D3-D 下降场景未做主门，仅闭合验证 |

---

## 4. 与失败实验的切割（代理师不得写回）

| 已失败/删除 | 证据 | 不得写入 |
|---|---|---|
| **D3 recovery** | P2.1A formal FAIL（c6: Q95 recovery vs rolling-max 无严格正增量）| 不得作为独立权利要求或从属；v3 以"信息类别自然变化"替代 |
| recent_var/variance 状态 | P1 formal No-Go | 不得作为状态判定依据 |
| 主动多车重分配 | prior art 拥挤 + 证据不支持 | 不得作为核心创造性 |
| ML/RL/新 MPC | 未超过 rolling baseline | 不得声称需 ML 才有效 |

---

## 5. 项目状态冻结

```
E7-FAST EXPERIMENTAL EXPLORATION = CLOSED

D0 = GO (A_level)
D2_DEV (train+val) = GO
D3_DEV (train+val) = GO
D2_TEST = PASS
D3_TEST = PASS

NEW MODEL DEVELOPMENT = STOP
D3 RECOVERY = CLOSED (P2.1A FAIL)
ML/RL = CLOSED

24H DYNAMIC REPLAY = OPTIONAL IMPLEMENTATION SUPPORT
                     = NOT FILING GATE
```

24h 动态回放仅当代理师明确要求"完整日运行实施例（SOC/PV/PCC 曲线）"时再补，
**不是申请前置条件**。

---

## 6. 配套权威文件

| 文件 | 作用 |
|---|---|
| `01_claim_tree_v3_e7_fast.md` | 权利要求骨架（三层防线）|
| `02_prior_art_element_map_v3_e7_fast.md` | 现有技术要素对照 |
| `03_tech_disclosure_e7_fast_v3.md` | 技术交底书主体 |
| `04_claim_evidence_map_v3.md` | Claim ↔ 实验 ↔ 证据等级 |
| `05_experiment_evidence_summary_v3.md` | 代理师可读证据表 |
| `06_known_limits_and_forbidden_claims_v3.md` | **本文件：禁用词+证据边界** |
| `claim_tree.md`（v2）| **HISTORICAL**，保留审计，不再权威 |
| `prior_art_matrix.md`（v2）| **HISTORICAL**，保留审计，不再权威 |
| `tech_disclosure.md`（v2）| **HISTORICAL**，顶部 banner 已标注过时 |
