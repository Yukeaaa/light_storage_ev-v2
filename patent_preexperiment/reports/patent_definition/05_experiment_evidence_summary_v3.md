# 05 实验证据摘要 v3（E7-FAST）— 代理师可读

> 精简版证据表，供代理师快速理解技术效果支撑。完整数据见
> `results/raw/e7_fast/` + `reports/E7_FAST_*_gate.md`。
> 项目判定：**FILING GO / NARROW CLAIM STRATEGY**

---

## 1. 证据链总览

```
D0 数据充分性门        → A 级 GO（11702 正向事件）
D2 EV 验证 (train+val) → GO（M2 双重约束 vs rolling-Q95）
D3 系统验证 (train+val)→ GO（S3 vs S2 系统层效果）
D2+D3 test 单次暴露    → TEST_PASS（未见时段复现，效果更强）
```

全部 commit：cd3232c / 8f9e93d / b87edc9 / 48b5205

---

## 2. D0 数据充分性

| 指标 | 值 | 阈值 |
|---|---|---|
| 正向 pilot 上调事件（train+val）| 11,702 | A≥100 |
| unique sessions | 4,418 | A≥30 |
| stations | 62 | A≥5 |
| months | 18 | A≥2 |
| 负向事件 | 20,725 | ≥50 |

**结论**：真实数据足以支撑问题验证，无红灯。

---

## 3. D2 EV 验证（M2 双重约束 vs B2 rolling-Q95）

### 3.1 train+validation

| 方法 | Over(Σ) | Under(Σ) | Hit rate | Coverage |
|---|---|---|---|---|
| B0 不增加 | 0 | 8679 | 0 | 0 |
| B1 pilot-only | 14865 | 2048 | 0.60 | 0.76 |
| **B2 rolling-Q95**（最强 baseline）| 5338 | 4961 | 0.63 | 0.43 |
| **C M2 双重约束**（候选）| 3732 | 5446 | 0.63 | 0.37 |

| 指标 | C vs B2 | 阈值 |
|---|---|---|
| Over improvement | **30.08%** | ≥10% ✅ |
| CoverageRatio | **86.95%** | ≥50% ✅ |
| session 等权方向 | 一致（37.1%）| ✅ |

### 3.2 test（single-exposure）

| 指标 | C vs B2 | 阈值 |
|---|---|---|
| Over improvement | **39.65%** | ≥10% ✅ |
| CoverageRatio | **77.97%** | ≥50% ✅ |

**结论**：M2 双重约束比 rolling-Q95 单独使用**少高估 30%→40%**，保留 78-87% 真实上调覆盖。
test 比 train+val 更强 → 时间外推稳健。

**诚实边界**：C 的 Under(5446) > B2 Under(4961) → 改善部分来自更保守抑制，
**不能称"更准确识别车辆能力"**。

---

## 4. D3 系统验证（S3 vs S2，园区短周期嵌入）

### 4.1 train+validation

| arm | ①shortfall | ②unplanned_bess | ③pcc_residual | ④accepted_flex |
|---|---|---|---|---|
| S0 乐观 | 10197 | 6958 | 3239 | 5915 |
| S1 禁止增加 | 0 | 0 | 0 | 0 |
| **S2 rolling-Q95**（最强 baseline）| 5338 | 2567 | 2771 | 3718 |
| **S3 M2 方案**（候选）| 3732 | 2175 | 1558 | 3233 |

| 指标 | S3 vs S2 | 阈值 |
|---|---|---|
| ① unexpected_shortfall 降 | **30.08%** | ≥10% ✅ |
| ② unplanned_bess 降 | **15.27%** | ≥10% ✅ |
| ③ pcc_residual 未恶化 | True | ✅ |
| ④ S3 flex > S1×1.1 | True（3233 > 0）| ✅ |

### 4.2 test（single-exposure）

| 指标 | S3 vs S2 | 阈值 |
|---|---|---|
| ① shortfall 降 | **39.65%** | ≥10% ✅ |
| ② unplanned_bess 降 | **41.41%** | ≥10% ✅ |
| ③ pcc 未恶化 | True | ✅ |

**结论**：M2 方案接入园区光储充后，减少 **EV 执行缺口 30%→40%**、**事后 BESS 临时补偿
15%→41%**，PCC 残差未恶化。

**关键区分**：比较的是"**事后** BESS 临时补偿（unplanned_bess_correction）"，
**不是**笼统的"BESS 总补偿能量"。事前 planned_bess 是正常协调，不算控制失败。
S3 的 total_bess（12152）与 S2（12543）接近 → planned_bess 未失控增加。

**诚实边界**：BESS/PCC 证据是**混合回放**（EV 响应真实，园区 PV/load/BESS/PCC 为
工程场景/模型），**不是真实园区实测**。

---

## 5. 核心量化公式

### M2 双重约束（Claim 3）
```
P_upper = max(P_actual, min(P_charger_allow, P_history))
allowed_up = max(P_upper - P_actual, 0)
```
数学上 C = min(B1, B2)：天然不比 rolling-Q95 激进。

### 历史支持水平（Claim 4）
- 窗口 15min，Q95，因果化 shift(1)，最小 5 样本

### 执行缺口传播（技术效果 I/J）
```
unexpected_shortfall = max(ev_accepted - ev_observed_support, 0)
unplanned_bess = min(shortfall, bess_fast_available)
pcc_residual = shortfall - unplanned_bess
```

---

## 6. 证据边界一览

| 证据 | 等级 | 可说 | 不可说 |
|---|---|---|---|
| EV 响应（pilot/actual/历史）| REAL | 真实充电数据 | "车辆真实最大能力" |
| 园区 PV/load/BESS/PCC | 混合回放 | "混合回放表明…" | "真实园区实测储能补偿降低 X%" |
| M2 双重约束效果 | B（真实+test）| "少高估 30-40%" | "准确识别车辆能力" |
| 系统层效果 | C（混合回放）| "减少执行缺口/事后补偿" | "真实园区节能率" |
| 时间外推 | B（test 复现）| "未见时段仍保持效果方向" | "适用于所有车型/园区" |
