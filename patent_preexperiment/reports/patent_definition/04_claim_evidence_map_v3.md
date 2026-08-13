# 04 Claim-Evidence Map v3（E7-FAST）

> 每条 Claim 对应哪组实验 + 证据等级。代理师撰写时引用实验编号。
> 证据等级：**B**=真实数据验证+test 复现；**C**=机制成立/混合回放；**D**=假设/无真实数据/仅从属。

---

## 证据等级定义

| 等级 | 含义 | 可用于 |
|---|---|---|
| B | 真实数据 train+val + test 单次复现，方向一致 | 独立/强从属核心技术效果 |
| C | 机制成立（可运行、改变动作）或混合回放系统效果 | 独立/从属机制 + 混合回放效果 |
| D | 无真实数据 / 仅从属 / 假设 | 仅从属权利要求 |

---

## Claim ↔ 实验 ↔ 证据等级

| Claim | 内容摘要 | 支撑实验 | 证据等级 | 关键数值 |
|---|---|---|---|---|
| **Claim 1**（主链 8 步）| 园区需求→车辆信息→不同增减规则→汇总→限制→BESS/PCC | D0+D2+D3+test | **C** | D2 Over↓30%→40%；D3 shortfall↓30%→40% |
| Claim 2 | M2 双重约束（上调同时受桩侧允许+历史支持共同限制）| D2+test | **B** | D2 train+val Over↓30%；test Over↓40% |
| Claim 3 | P_upper = max(P_actual, min(P_charger_allow, P_history)) | D2+test | **B** | 同上（C_candidate_m2 实现）|
| Claim 4 | 历史支持水平 = 预定窗口内因果化统计上界 | D0+D2 | **B** | Q95 15min 窗 shift(1) 因果化 |
| Claim 5 | 缺桩侧允许但有历史 → 不主动上调，可降低 | D0+D2 B0 对照 | **C** | D0 M3 覆盖 14.8M cycle；S1(B0) flex=0 对照 |
| Claim 6 | 历史不足 → 保持原安排 | D0 | **C** | D0 M4 覆盖 416K cycle |
| Claim 7 | capability 可得时在能力范围内增减 | 无真实数据 | **D** | ACN 无 BMS capability；仅从属 |
| Claim 8 | 多车允许增减量汇总 | D3 | **C** | D3 EV 群汇总（单车场景单事件回放）|
| Claim 9 | BESS 补偿受 SOC/功率/效率约束 | D3 | **C** | D3 BESS 物理模型 SOC 50% 10-90% |
| Claim 10 | BESS 不足 → PCC 偏差 | D3 | **C** | D3 pcc_residual 未恶化 |
| Claim 11 | PV 富余/防逆流场景 | D3-U | **C** | D3-U 主场景（PV surplus=delta_pilot）|
| Claim 12 | 变压器容量受限/需量场景 | 未单独验证 | **D** | D3-D 闭合验证未做主门；仅从属 |

---

## 技术效果证据（I/J 元素）

| 技术效果 | 实验 | 证据等级 | 数值（vs S2 rolling-Q95）|
|---|---|---|---|
| I: 减少 EV 已安排但未完成的功率调整（unexpected_shortfall）| D3 train+val | **C**（混合回放）| 降 30.08% |
| I: test 复现 | D3 test | **C** | 降 39.65% |
| J: 减少事后 BESS 临时补偿（unplanned_bess_correction）| D3 train+val | **C** | 降 15.27% |
| J: test 复现 | D3 test | **C** | 降 41.41% |
| J: PCC 残差未恶化 | D3 | **C** | True |

> I/J 均为 **C 级（混合回放）**：EV 响应真实，园区 PV/load/BESS/PCC 为工程场景/模型。
> 不得声称"真实园区实测"。

---

## 数据规模证据（D0）

| 指标 | train+val | test | 评价 |
|---|---|---|---|
| 正向 pilot 上调事件 | 11,702 | 6,687 | A 级 GO（远超 100）|
| M2 评价集事件 | 10,893 | 6,643 | D2/D3 用 |
| unique sessions | 4,418 | — | A 级 GO（远超 30）|
| stations | 62 | — | A 级 GO（远超 5）|
| months | 18 | — | A 级 GO（远超 2）|
| 负向事件 | 20,725 | — | 充分（远超 50）|

---

## 未验证/无证据的 Claim（必须仅从属）

| Claim | 原因 | 处置 |
|---|---|---|
| Claim 7（capability）| ACN 无真实 BMS capability | 仅从属/可选实施例 |
| Claim 12（变压器场景）| D3-D 下降场景未做主门 | 仅从属；D3-D 仅闭合验证 |
| "真实园区储能补偿降低" | BESS/PCC 混合回放非实测 | 禁用；见 06 |
| "准确识别车辆能力" | Candidate 更保守非更准确 | 禁用；见 06 |
