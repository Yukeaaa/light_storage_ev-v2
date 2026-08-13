# E7-FAST D2 真实 EV 数据验证门报告

> 生成时间（UTC）：2026-08-13T14:35:25Z
> 配置：`D:\JobWorkspaces\light_storage_ev-v2\patent_preexperiment\configs\e7_fast.yaml`（rule_version=e7_fast_v1，冻结）
> 依据：review §14-18 / §36 step 6-7 + 用户 D2 冻结口径

## 1. 实验设计（冻结）

- **问题**：`min(pilot, historical-Q95)` 双重限制是否在真实自然 pilot 上调事件上，比 rolling-Q95 单独使用产生足够大的“少高估、不过度牺牲真实机会”的增量价值？
- **时序锁定**：actual_before=t-1；pilot_after=t 新允许值（拟执行调整值，非响应证据）；q95_before 严格由 t 之前 actual 构造；actual_1/3/5min 只作结果，绝不进 Candidate。
- **P_support** = max(actual_5min - actual_before, 0)：真实观察到的实际增加量；**非车辆理论最大能力**。
- **禁止外推**（review §22）：candidate 允许量 <= P_support 视为未超出；超出 = Over。
- **C = min(B1, B2)**：天然不比 B2 激进；Over 下降可能因更保守，必须与 Under 同看。
- **评价集**：正向 + info_mode==M2 + q95/actual 有效 + train+validation（排除 office001/stress）。
- **四控制器**：B0=0 / B1=max(pilot-actual,0) / B2=max(Q95-actual,0) / C=max(min(pilot,Q95)-actual,0)。

## 2. M2 评价集过滤后规模

| 指标 | 值 |
|---|---|
| 评价事件数 | 10893 |
| unique sessions | 4065 |
| stations | 58 |
| months | 18 |
| 真实有上调支持(P_support>0)事件数 | 6550 |

> D0 正向总数 11702；过滤后见上。若远高于 A 级规模则继续。

## 3. 第一屏：四控制器指标（事件总体）

| 方法 | Over(Σ) | Over(mean) | Under(Σ) | Under(mean) | Hit rate | Coverage | mean allowed_up |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0_no_increase | 0.00 | 0.0000 | 8678.96 | 0.7967 | 0.0000 | 0.0000 | 0.0000 |
| B1_pilot_only | 14865.36 | 1.3647 | 2047.84 | 0.1880 | 0.6014 | 0.7640 | 1.9734 |
| B2_rolling_q95 | 5337.80 | 0.4900 | 4961.05 | 0.4554 | 0.6324 | 0.4284 | 0.8313 |
| C_candidate_m2 | 3731.98 | 0.3426 | 5446.11 | 0.5000 | 0.6324 | 0.3725 | 0.6394 |

> **Over** 越小越好；**Under** 越小越不保守（必须同看）；
> **Coverage** = Σmin(allowed,support)/Σsupport（功率加权，禁止靠每事件放一点虚称高覆盖）。

## 4. session 等权汇总（防高频会话支配）

| 方法 | session 等权 Over(mean) |
|---|---:|
| B0_no_increase | 0.0000 |
| B1_pilot_only | 1.3131 |
| B2_rolling_q95 | 0.4086 |
| C_candidate_m2 | 0.2570 |

> session 等权 Over improvement = 37.10%；方向一致。

## 5. 负向 pilot 事件响应标定（review §18；园区回放用）

| 指标 | 值 |
|---|---|
| 负向事件数 | 20725 |
| response_gain_5m median | 0.0045 |
| response_gain_5m p25 | -0.0003 |
| response_gain_5m p75 | 0.5149 |
| delta_actual_5min median (kW) | -0.0106 |
| 不响应比例（actual 未下降） | 0.4233 |

## 6. Go 门判定（review §17 + 用户冻结公式）

| 指标 | 值 | 阈值 |
|---|---|---|
| 最强 baseline（固定） | B2_rolling_q95 | review §15 |
| C vs B2 Over improvement (1-ΣOver_C/ΣOver_B2) | 30.08% | GO>=10% / COND 5-10% / FAIL<5% |
| C vs B2 CoverageRatio (Coverage_C/Coverage_B2) | 86.95% | GO>=50% |
| session 等权 Over improvement | 37.10% | 方向一致 |
| 方向一致 | True | True |

### 判定：**GO — M2_active_increase_valid** （GO）

> C vs B2 Over improvement=30.1%>=10.0%，CoverageRatio=87.0%>=50.0%，session 等权方向一致（37.1%）；M2 双重限制有效。

> **Under 警示**：若 Over 改善但 Under 损失大，只能描述为“更保守抑制未经历史支持的功率增加”，不得称“更准确识别车辆能力”。

## 7. 红灯检查（review §37）

- 无红灯触发。

## 8. 下一步决策（review §36）

- D2 通过（GO）。进入 §36 step 9：真实事件→园区光储充短周期嵌入，比较四个 system arm。

## 9. 产物文件

- `results/raw/e7_fast/ev_validation/d2_trainval_event_scores.parquet`（每事件四控制器得分）
- `results/raw/e7_fast/ev_validation/d2_trainval_summary.csv`（事件总体汇总）
- `results/raw/e7_fast/ev_validation/d2_session_equal_summary.csv`（session 等权）
- `results/raw/e7_fast/ev_validation/d2_station_month_diagnostic.csv`（station×month 诊断）
- `results/raw/e7_fast/ev_validation/d2_negative_calibration.csv`（负向标定）
- `results/raw/e7_fast/ev_validation/d2_gate_verdict.csv`（门判定）
- `d2_test_summary.csv`：主判定 commit 后单独生成（test 单次暴露）
