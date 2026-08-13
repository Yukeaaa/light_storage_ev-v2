# E7-FAST D3 园区系统验证门报告

> 生成时间（UTC）：2026-08-13T08:25:52Z
> 配置：`D:\JobWorkspaces\light_storage_ev-v2\patent_preexperiment\configs\e7_fast.yaml`（rule_version=e7_fast_v1，冻结）
> 依据：review §19-31 / §36 step 9 + 用户 D3 冻结口径

## 1. 实验设计（冻结）

- **D3 真正要证明**：当 `min(pilot,Q95)` 限制接入园区光储充后，能否减少“EMS 已安排给 EV、但 EV 后续实际未完成”的功率缺口，从而减少事后 BESS 临时补偿和/或 PCC 功率偏差。
- **关键区分**（用户口径 §5）：planned_bess（事前正常协调）≠ unplanned_bess_correction（事后控制失败补偿）。BESS_compensation 必须是后者。
- **5 个核心量**：park_requested / ev_accepted / ev_observed_support / ev_realized / planned_bess / unexpected_shortfall / unplanned_bess / pcc_residual。
- **园区需求** = delta_pilot_kw（独立于 S2/S3）；PV 富余 = delta_pilot_kw；基础负荷 500kW 固定（验证功率平衡传播，非负荷预测）。
- **BESS 主场景**：P_BESS_max=0.5×actual_before，SOC=50%，10-90%，eta=0.95，2h。
- **四 arm**：S0=乐观 / S1=禁止增加 / S2=rolling-Q95 / S3=M2 双重限制。不新增第五个。
- **D3-U 主杀伤门**（PV 富余/上调）；test 物理过滤未看。

## 2. 第一屏：四 arm 系统指标（D3-U，事件总体求和）

| arm | ①unexpected_shortfall | ②unplanned_bess | ③pcc_residual | ④accepted_flex | ⑤conservatism | ⑥total_bess(诊断) |
|---|---:|---:|---:|---:|---:|---:|
| S0_unrestricted | 10196.94 | 6958.24 | 3238.69 | 5914.77 | 2764.18 | 6958.24 |
| S1_conservative | 0.00 | 0.00 | 0.00 | 0.00 | 8678.96 | 16111.71 |
| S2_rolling_q95 | 5337.80 | 2566.56 | 2771.24 | 3717.90 | 4961.05 | 12543.28 |
| S3_our_scheme | 3731.98 | 2174.53 | 1557.45 | 3232.85 | 5446.11 | 12152.20 |

> ①②③ 为 GO 门核心（越小越好）；④ 防止靠禁止取胜（越大越好）；⑤ 实际有能力但没用掉（越小越好）；⑥ 只诊断，不入 GO 门（Candidate 更谨慎可能 planned_bess 更高，这是正常 trade-off）。

## 3. 系统 Go 门判定（S3 vs S2 rolling-Q95；用户口径 §15）

| 指标 | S3 | S2 | 改善 | 阈值 |
|---|---|---|---|---|
| ① unexpected_shortfall | 3731.98 | 5337.80 | 30.08% | GO>=10% / COND 5-10% / FAIL<5% |
| ② unplanned_bess_correction | 2174.53 | 2566.56 | 15.27% | GO>=10% |
| ③ pcc_residual 未恶化 | — | — | True | True |
| ④ S3 flex > S1×1.1 | — | — | True | True |

### 判定：**GO — D3_system_value_valid** （GO）

> S3 vs S2: unexpected_shortfall 降 30.1%>=10.0%，unplanned_bess 降 15.3%>=10.0%，PCC residual 未恶化，S3 flex(3233)>S1(0)×1.1。

> **诚实记录**：Candidate 更保守 → planned_bess 可能更高，total_bess_activity 不入门；只比 unplanned_bess_correction（事后临时补偿）。

## 4. 红灯检查（review §37）

- 无红灯触发。

## 5. 下一步决策

- D3 通过（GO）。一次性暴露 D2 test 验证时间外推 → 通过后决定是否做完整 24h 动态回放。
- 专利方向（用户口径 §18）：园区根据光/储/负荷/电网状态产生 EV 调整需求后，根据充电桩允许信息与车辆历史实际响应共同限制 EV 上调量，减少已安排但未完成的功率调整量，降低由此引起的储能临时补偿和/或 PCC 偏差。

## 6. 产物文件

- `results/raw/e7_fast/park_replay/d3_u_trainval_replay.parquet`（每事件每 arm 8 核心量）
- `results/raw/e7_fast/park_replay/d3_u_system_summary.csv`（arm 汇总）
- `results/raw/e7_fast/park_replay/d3_gate_verdict.csv`（门判定）
