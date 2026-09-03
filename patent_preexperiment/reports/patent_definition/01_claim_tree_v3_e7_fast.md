# 01 Claim Tree v3（E7-FAST）— HISTORICAL/HOLD

> **2026-09-03 SUPERSEDED FOR CORE-PATENT STATUS**：本文件是 E7-FAST/M2 阶段的窄防御性候选包，
> 只表示 D2 vehicle-side mechanism VALID / package HOLD。当前项目状态以 CORE-SEARCH 决策链为权威：
> **core-patent status = NO-GO / 当前无成熟 GO 核心专利**。不得再把本文件的 FILING GO 口径解释为
> 系统级核心专利 GO。

> **状态：E7-FAST PACKAGE AUTHORITY ONLY（替代 v2 claim_tree.md；已被 CORE-SEARCH core status 超越）**
> 历史候选包判定：**FILING GO / NARROW CLAIM STRATEGY**（D3 corrective audit 后降级为 M2 主 Claim + BESS/PCC 弱从属）
> 依据：D0 GO + D2 train+val/test GO + D3 corrective audit train+val FAIL / test CONDITIONAL
> （commits cd3232c / 8f9e93d / b87edc9 / 48b5205 + D3 corrective audit）
>
> **D3 corrective audit（review/申请前技术尽调-审查.md P0 修正）**：
> - 旧 D3 代码 ev_accepted = arm_allowed_up（未与 park_requested 取 min）→ 系统效果数字作废。
> - 修正后 ev_accepted = min(park_requested, arm_allowed_up)：
>   train+val shortfall 降 0.01%（FAIL），test 降 4.46%（CONDITIONAL）。
> - **D2 不受影响**（D2 不使用 park_requested/BESS/PCC），D2 train+val/test 仍 GO。
> - 因此 Claim 1 主保护点收窄为 **M2 EV 功率上调限制方法**，BESS/PCC 降为强从属/背景。
>
> **历史处置**：
> - `claim_tree.md`（v2）= **HISTORICAL**，保留审计历史，**不再作为当前权威**。
> - **D3 recovery = REMOVED**（P2.1A formal FAIL）。E7-FAST 以"信息类别自然变化"替代。
> - recent_var / variance 状态判定 = **不恢复**（P1 formal No-Go）。
>
> **创造性策略**：不把发明概括成"一种光储充联合功率优化方法"，也不把 `min(pilot,Q95)`
> 单独当作创造性来源。保护的是**M2 双重上调限制如何嵌入园区 EMS 请求→EV 群执行→剩余协调**的控制链。
> **系统层效果（BESS/PCC）因 corrective audit 降为弱从属**，不作为 Claim 1 必要技术效果。

---

## 0. 发明核（冻结于本文件；D3 corrective audit 后收窄）

> 园区能源管理系统已提出电动汽车聚合功率上调请求后，对每辆正在充电的车辆，根据当前能够
> 获得的桩侧允许信息和本控制周期之前的实际充电历史，**共同限制**该车辆本周期允许增加的
> 功率——上调后的功率同时不得超过当前桩侧允许值和历史实际响应支持水平；对于缺少桩侧允许
> 信息或历史不足的车辆，不进行未经证据支持的主动上调；汇总各车辆允许增加量得到电动汽车群
> 最大允许增加量，**真正采用的电动汽车群增加量取园区请求与该最大允许增加量中的较小值**。

**核心公式**（从属）：
```
ΔP_EV = min(ΔP_req, Σ_i ΔP_i,allow)
其中 ΔP_i,allow = max(min(P_charger_allow, P_history) - P_actual, 0)
```

**关键**：`min(ΔP_req, Σ_i ΔP_i,allow)` 这一步是审查 corrective audit 后必须进入 Claim 的
请求限幅——园区不能把超过 EV 群可承担量的功率全部安排给 EV。

---

## 1. 三层权利要求防线

### 第一层：主 Claim 1（M2 双重上调限制 + EV 群请求限幅）

> **审查 corrective audit 后收窄**：Claim 1 不再以"完整园区控制链+BESS/PCC 系统效果"
> 为必要技术特征（D3 corrective audit train+val FAIL，系统效果不成立）。
> 主保护点 = **M2 双重上调限制 + EV 群汇总 + 请求限幅 min(req, sum_allow)**。
> BESS/PCC 降为强从属（Claim 9/10），不作为 Claim 1 必要技术效果。

一种工商业园区光储充系统的电动汽车充电功率控制方法，包括：

**Step 1**：获取由园区能源管理系统根据园区光伏、基础负荷、储能和电网接口中的至少一种
运行状态确定的电动汽车聚合功率上调请求 ΔP_req；

**Step 2**：对当前每辆正在充电的车辆，获取其当前能够获得的充电相关信息，所述信息包括
该车辆的桩侧允许功率或允许电流、该车辆实际充电功率、以及该车辆在本控制周期之前的
实际充电历史响应；

**Step 3**：对于同时具备桩侧允许信息和有效实际充电历史的车辆，其本周期允许增加的功率
同时受当前桩侧允许值和历史实际响应支持水平的限制，得到该车辆本周期允许增加量 ΔP_i,allow；
对于缺少桩侧允许信息或实际充电历史不足的车辆，本周期不进行未经证据支持的主动上调；

**Step 4**：汇总各车辆本周期允许增加量，得到电动汽车群本周期最大允许增加量
ΔP_EV,max = Σ_i ΔP_i,allow；

**Step 5**：本周期实际采用的电动汽车群功率增加量 ΔP_EV = min(ΔP_req, ΔP_EV,max)，
即园区请求超过电动汽车群可承担量时仅执行可承担部分；

**Step 6**：下一控制周期重新获取最新状态并重复上述步骤。

> **Claim 1 不包含**：BESS 补偿、PCC 偏差（降为 Claim 9/10 强从属）；
> 具体公式 Q95/15min（降为 Claim 3/4 从属）；M3/M4 详细规则（降为 Claim 5/6 从属）。
> Claim 1 保护的是"双重共同约束上调 + 群汇总 + 请求限幅"的控制逻辑，不保护系统效果。

---

### 第二层：强从属（M2 双重约束的具体实施）

**Claim 2**（M2 双重约束）：
如 Claim 1 所述方法，对于同时具备桩侧允许功率和有效实际充电历史的车辆，其上调后的功率
上限由当前桩侧允许值与历史实际响应支持水平共同确定，且不低于该车辆当前实际运行功率。

**Claim 3**（双重约束的具体公式）：
如 Claim 2 所述方法，所述上调后功率上限 P_upper 满足：
P_upper = max(P_actual, min(P_charger_allow, P_history))
其中 P_actual 为车辆当前实际功率，P_charger_allow 为当前桩侧允许功率，
P_history 为本控制周期之前该车辆实际充电历史响应的支持水平。

**Claim 4**（历史支持水平的具体定义）：
如 Claim 3 所述方法，所述历史实际响应支持水平由该车辆在本控制周期之前、预定时间窗口内、
非空实际充电功率样本的统计上界确定，且仅使用当前控制周期之前的数据构造。

**Claim 5**（缺桩侧允许信息 → 不主动上调）：
如 Claim 1 所述方法，对于具备有效实际充电历史但缺少当前桩侧允许信息的车辆，本周期
允许降低其功率但不主动增加，直至重新获得桩侧允许信息后按 Claim 2 处理。

**Claim 6**（历史不足 → 保持）：
如 Claim 1 所述方法，对于实际充电历史样本不足的车辆，本周期不改变其功率安排，
直至其历史样本达到预定下限后按 Claim 4 或 Claim 5 处理。

---

### 第三层：fallback 从属（M3/M4 信息不足保护 + BESS/PCC 背景）

> **审查 corrective audit 后降级**：M3/M4 无系统收益验证（D3 corrective audit 未分别验证），
> 降为从属 fallback；BESS/PCC 系统效果 train+val FAIL、test CONDITIONAL，降为强从属/背景，
> 不作为 Claim 1 必要技术效果。

**Claim 5**（缺桩侧允许 → 不主动上调）：
如 Claim 1 所述方法，对于具备有效实际充电历史但缺少当前桩侧允许信息的车辆，本周期
允许降低其功率但不主动增加，直至重新获得桩侧允许信息后按双重约束处理。

**Claim 6**（历史不足 → 保持）：
如 Claim 1 所述方法，对于实际充电历史样本不足的车辆，本周期不改变其功率安排。

**Claim 7**（明确车辆能力信息可得时）：
如 Claim 1 所述方法，当车辆或电池管理系统明确提供最大可充电功率信息时，该车辆本周期
允许增加量在该最大可充电功率与当前安排功率之差范围内确定。

**Claim 8**（多车汇总 + 请求限幅）：
如 Claim 1 所述方法，所述电动汽车群本周期最大允许增加量为各车辆允许增加量之和；
本周期实际采用的电动汽车群功率增加量取园区请求与该最大允许增加量中的较小值。

**Claim 9**（储能补偿 — 强从属，非必要技术效果）：
如 Claim 1 所述方法，对于电动汽车未承担的剩余功率调整量，由储能系统在当前可充功率
范围内承担；受储能当前荷电状态、最大充/放功率和充/放效率约束。

**Claim 10**（储能不足 → PCC — 强从属）：
如 Claim 9 所述方法，当储能补偿不足以覆盖剩余功率调整量时，不足部分反映为电网接口
功率偏差。

**Claim 11**（PV 富余 / 防逆流场景）：
如 Claim 1 所述方法，当光伏出力超过基础负荷与当前 EV 充电功率之和时，所述电动汽车
聚合功率上调请求为增加 EV 充电功率以吸收光伏富余。

**Claim 12**（变压器容量受限 / 需量场景）：
如 Claim 1 所述方法，当园区总功率超过变压器或电网接口容量限制时，园区 EV 调整需求
为降低 EV 充电功率。

---

## 2. Claim 1 不写死 Q95 的理由

Claim 1 保护的是**控制链如何嵌入园区动作**，不保护具体公式。原因：
- 若 Claim 1 = `min(pilot,Q95)`，审查员易拆成"已知桩侧上限 + 已知历史功率上限 → 取更小安全值"
  的常规组合，创造性风险高。
- Q95 / 15min 窗 / 5 样本下限等具体参数放 Claim 3/4 从属，主 claim 用"共同限制"上位表述。

---

## 3. 禁止入 v3 的内容（来自失败实验 / 证据不支持）

| 内容 | 状态 | 理由 |
|---|---|---|
| D3 recovery（actual 接近边界 → 单向恢复更高调整范围）| **REMOVED** | P2.1A formal FAIL；E7-FAST 以信息类别自然变化替代 |
| recent_var / variance 状态判定 | **不恢复** | P1 formal No-Go |
| 主动多车复杂重分配 | **不做主创新** | prior art 拥挤 + 证据不支持 |
| ML / RL / 新 MPC | **不做** | 简单 baseline 已足够；ML 未超过 rolling |
| "准确识别车辆能力" | **禁用** | Candidate 更保守，非更准确；见 06 禁用词 |
| "真实园区储能补偿降低 X%" | **禁用** | BESS/PCC 证据是混合回放，非实测 |
| 旧 D3 系统效果数字（shortfall 降 30%/40%，bess 降 15%/41%）| **作废** | D3 corrective audit 修正 request-cap 后 train+val FAIL（0.01%），test CONDITIONAL（4.46%）|

---

## 4. 证据等级标注（每条 Claim 对应实验，详见 04_claim_evidence_map_v3.md）

| Claim | 证据等级 | 支撑实验 |
|---|---|---|
| Claim 1（M2 双重限制 + 群汇总 + 请求限幅）| B（D2 真实数据+test 复现）| D0 + D2 train+val/test |
| Claim 2/3/4（M2 双重约束公式/历史支持水平）| B（真实数据 + test 复现）| D2 train+val + D2 test |
| Claim 5（无 pilot → 不上调）| C（机制成立，无系统收益验证）| D0 M3 覆盖 |
| Claim 6（历史不足 → 保持）| C（机制成立）| D0 M4 覆盖 |
| Claim 7（capability）| D（无真实数据，仅从属）| ACN 无 BMS capability |
| Claim 8（群汇总 + 请求限幅 min）| B（D2 验证 allowed_up；请求限幅是工程必然）| D2 + 工程逻辑 |
| Claim 9/10（BESS/PCC 补偿）| **D**（corrective audit 后系统效果弱）| D3 corrective audit train+val FAIL / test CONDITIONAL |
| Claim 11/12（PV 富余/变压器场景）| C（场景定义，非系统效果验证）| D3-U 场景定义 |

> 证据等级：B=真实数据验证+test 复现；C=机制成立/混合回放；D=假设/无真实数据/仅从属/系统效果弱。
> **D3 corrective audit 后 Claim 9/10 降为 D 级**（系统效果 train+val FAIL）。

---

## 5. 与 v2 的关键差异

| 维度 | v2（HISTORICAL）| v3（CURRENT）|
|---|---|---|
| 核心 | D1+D2+D3 设备动作链（含 recovery）| M2 双重上调限制 + 群汇总 + 请求限幅（recovery 删除）|
| 性能证据 | 无（mechanism only）| D2/D3/test GO（混合回放系统效果）|
| 主 claim | 10 步设备动作链 | 8 步园区控制链（光→充→储→网）|
| 创造性锚 | D1+D2+D3 组合 | 控制链嵌入 + M2 双重约束 + 信息不足保护 |
| 证据上限 | 机制可实现 | 减少事后 BESS 临时补偿 + PCC 偏差（混合回放）|
