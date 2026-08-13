# 03 技术交底书（E7-FAST v3）

> **状态：CURRENT AUTHORITY**（替代 v2 tech_disclosure.md，后者顶部 banner 已标注过时）
> 项目判定：FILING GO / NARROW CLAIM STRATEGY（D3 corrective audit 后主 Claim 收窄为 M2）
> 证据链：D0 GO / D2 train+val+test GO / D3 corrective audit train+val FAIL / test CONDITIONAL
> （commits cd3232c / 8f9e93d / b87edc9 / 48b5205 + D3 corrective audit）
> 配套权威：`01_claim_tree_v3_e7_fast.md` + `02_prior_art_element_map_v3_e7_fast.md`
>
> **★ 2026-08-14 D3 corrective audit 修正**：旧 D3 系统效果数字作废，主 Claim 依赖 D2。
>
> **内部工程与专利策略交底文件 · 非法律意见**

---

## 1. 发明名称

一种工商业园区光储充系统的电动汽车充电功率控制方法

---

## 2. 技术领域

工商业园区光储充（光伏-储能-充电）系统控制，具体涉及根据园区光伏、基础负荷、储能和
电网接口状态，结合各充电车辆当前可获得信息与实际充电历史，对电动汽车群充电功率调整
进行有界控制的方法。

---

## 3. 背景技术

### 3.1 真实问题

工商业园区光储充系统中，EMS 可在账面上给 EV 分配某功率预算，但车辆实际吸收能力受
车辆状态、桩侧 pilot/BMS 信息可得性、充电曲线、限流和内部控制影响，未必能执行该预算。

**真实数据证据**（ACN 数据，D0/D2）：
- 存在持续的桩侧允许值与车辆实际响应差异：D0 提取 11,702 个正向自然 pilot 上调事件
  （train+validation，62 桩、18 个月）。
- 若 EMS 长期把"安排值"当"可执行值"，计划与实际的差值会迫使储能/电网事后补偿。

### 3.2 现有技术边界（详见 02 prior-art element map）

| 现有技术 | 已覆盖 | 未覆盖（v3 差异化空间）|
|---|---|---|
| US10464435B2（ChargePoint）| 历史响应限制 | D 双重共同约束 + E fail-closed + G/H 园区协调 |
| US20220153162A1 | EMS+charger 协调 | C 历史响应 + D 双重约束 + E fail-closed |
| **US10230198B2（Schneider）**| **pilot+actual 取较小值** | **★★ D 最危险近邻；缺 E+G** |
| **US11376981B2（ACN 族）**| **pilot+actual 理解车辆能力** | **缺 D（作为限制）+ E + G** |
| CN116316754B | 光储充可调度容量评估 | C/D/E + I/J 执行缺口传播 |
| CN121886483A | 光储充多级协调架构 | 车辆侧 C/D/E 机制 |

**★ 无单一文献覆盖 D+E+G 组合**（双重共同约束 + 信息不足 fail-closed + 请求限幅）。
**Schneider US10230198B2 是 D 最危险近邻**（已教示 pilot+actual 取较小值），
创造性必须靠 D+E+G 组合，不能靠 D 单独。BESS/PCC（H）降为弱从属。

---

## 4. 发明内容

### 4.1 发明核（与 01 claim_tree 一致）

园区先根据光伏、基础负荷、储能和电网接口状态确定本周期需要增加或降低的 EV 总充电功率；
随后针对各正在充电车辆，根据当前能够获得的桩侧允许信息和实际充电历史采用不同的增加/降低
规则；对于同时具备桩侧允许信息和有效实际历史的车辆，其上调后的功率同时受当前桩侧允许值
和历史实际响应支持水平限制；对于缺少相应支撑信息的车辆，不进行未经证据支持的主动上调；
汇总各车允许调整量后，仅将其中可承担部分安排给 EV，剩余园区功率调整需求再由储能和/或
电网接口处理。

### 4.2 控制流程（Claim 1 六步；★ corrective audit 后收窄）

```
Step 1: 获取 EMS 确定的电动汽车聚合功率上调请求 ΔP_req
Step 2: 获取各车辆当前可获得信息（桩侧允许、实际功率、实际历史）
Step 3: 对有桩侧允许+有效历史的车辆，上调同时受两者共同限制（M2 双重约束）；
        缺桩侧允许 → 不主动上调（M3）；历史不足 → 保持（M4）
Step 4: 汇总各车允许增加量 → EV 群最大允许增加量 ΔP_EV,max = Σ_i ΔP_i,allow
Step 5: 实际采用 ΔP_EV = min(ΔP_req, ΔP_EV,max)（请求限幅）
Step 6: 下一周期重新获取状态重复
```

> **★ corrective audit 后**：BESS/PCC 补偿从 Claim 1 主链移至 Claim 9/10 强从属。
> Step 7（剩余交 BESS、BESS 不足 → PCC）不再是 Claim 1 必要步骤，仅作实施例背景。

### 4.3 关键实施例

**M2 双重约束实施例**（Claim 2/3/4）：
- 当前 actual = 4.0 kW，pilot 允许 = 7.2 kW，过去 15min 实际 Q95 = 5.6 kW
- 上限 P_upper = max(4.0, min(7.2, 5.6)) = 5.6 kW
- 本周期最多增加 1.6 kW
- **而非** pilot - actual = 3.2 kW 全部当作可增加能力

**信息不足 fail-closed 实施例**（Claim 5/6）：
- 刚插枪 1-2 分钟，历史样本不足 → 本周期保持原安排（M4）
- 无 pilot 信息但历史充分 → 不主动上调，可降低（M3）
- 重新获得 pilot → 信息类别自然变 M2，才允许按双重约束上调
- **永远不做** "actual 接近边界 → 单向恢复" 的 D3 recovery（已失败）

---

## 5. 技术效果（证据支撑，详见 05；★ D3 corrective audit 后修正）

### 5.1 已验证效果

| 效果 | 证据 | 数值（vs 最强简单 baseline rolling-Q95）| 判定 |
|---|---|---|---|
| 减少超过真实响应支持的上调量 | D2 train+val + test | Over 降低 30%（train+val）→ 40%（test）| **B 级 GO** |
| 减少 EV 执行缺口 | D3 corrective audit | train+val 0.01%（FAIL），test 4.46%（CONDITIONAL）| **弱/降级** |
| 减少事后 BESS 临时补偿 | D3 corrective audit | train+val 0.01%（FAIL），test 6.03%（CONDITIONAL）| **弱/降级** |
| PCC 残差未恶化 | D3 corrective audit | True | ✅ |
| 真实利用 EV 调整能力 | D3 | S3 flex 显著高于"禁止增加"的 S1 | ✅ |

> **★ corrective audit 修正**：旧 D3 数字（shortfall 降 30%→40%，bess 降 15%→41%）作废。
> 修正后 D3 系统效果弱（train+val FAIL）→ BESS/PCC 降为弱从属，不作为 Claim 1 必要技术效果。
> **主 Claim 技术效果依赖 D2**（M2 双重约束减少 Over improvement 30%→40%）。

### 5.2 效果表述边界（必须遵守，见 06）

**可以写**：
> 真实充电数据验证表明，所述双重上调限制规则相比仅基于历史实际响应的单一限制，
> 能减少超过真实事件后续响应支持的电动汽车功率上调量（Over improvement 30%→40%）。

**不可以写**（corrective audit 后加强限制）：
- "真实工商业园区实测储能补偿降低 41%"（BESS/PCC 是混合回放，非实测）
- "准确识别车辆最大充电能力"（Candidate 更保守，非更准确）
- "适用于所有车型/园区"（ACN 主要是 workplace charging）

### 5.3 时间外推稳健性

train+validation 与 test 效果方向一致，且 test 更强：
> 所述控制规则在未参与规则确定的后续数据分区上仍保持相同效果方向。

---

## 6. 实施例证据边界（诚实记录）

| 数据 | 证据等级 | 说明 |
|---|---|---|
| EV pilot / actual / 历史响应 / 自然 pilot step | REAL | ACN 真实时序 |
| 园区 PV / 基础负荷 | SYNTHETIC / ENGINEERING | 短周期验证功率平衡传播，非负荷预测 |
| BESS SOC / 功率 / 效率 | ENGINEERING | 工程参数模型 |
| PCC / 变压器 | ENGINEERING | 场景参数 |
| EMS 需求 | SYNTHETIC_CONTROLLER | = delta_pilot_kw，独立于方案 |
| 减少储能补偿/PCC 偏差 | 混合回放 | EV 响应真实，园区背景混合 |

---

## 7. 与失败实验的切割（防止代理师误写回）

| 已失败/删除 | 状态 | 不得写入交底书 |
|---|---|---|
| D3 recovery（actual 接近边界 → 恢复更高调整范围）| REMOVED（P2.1A FAIL）| 不得作为独立权利要求或从属 |
| recent_var / variance 状态判定 | 不恢复（P1 No-Go）| 不得作为状态判定依据 |
| 主动多车复杂重分配 | 不做主创新 | 不得作为核心创造性 |
| ML / RL / 新 MPC | 不做 | 不得声称需 ML 才有效 |

---

## 8. 附图建议（代理师可要求补）

1. 园区控制流程图（Step 1-8）
2. M2 双重约束示意图（actual / pilot / Q95 / P_upper）
3. 信息类别判定流程（M1/M2/M3/M4）
4. EV 执行缺口 → BESS 临时补偿 → PCC 残差 传播图
5. D2/D3 效果对比柱状图（B0/B1/B2/C 或 S0/S1/S2/S3）

---

## 9. 配套文件

- `01_claim_tree_v3_e7_fast.md`：权利要求骨架（三层防线）
- `02_prior_art_element_map_v3_e7_fast.md`：现有技术要素对照
- `04_claim_evidence_map_v3.md`：每条 Claim 对应哪组实验
- `05_experiment_evidence_summary_v3.md`：代理师可看的证据表
- `06_known_limits_and_forbidden_claims_v3.md`：禁用词与证据边界
