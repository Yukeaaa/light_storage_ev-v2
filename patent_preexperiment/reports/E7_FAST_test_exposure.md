# E7-FAST D2+D3 Test Single-Exposure 报告

> 生成时间（UTC）：2026-08-13T10:10:42Z
> 配置：`D:\JobWorkspaces\light_storage_ev-v2\patent_preexperiment\configs\e7_fast.yaml`（rule_version=e7_fast_v1，冻结）
> 依据：用户 D2 冻结口径 §16；test single-exposure，禁止重复

## 1. 治理纪律

- test 判定标准在跑 test 前冻结（test_policy），与 train+val 同标准。
- single-exposure：只能跑一次，禁止重复；禁止 test FAIL 后调 Q95/换模型/加 ML/恢复 D3。
- D3 train+val 已 GO（commit b87edc9），才允许暴露 test。

## 2. D2 test: EV gate（M2 vs B2 rolling-Q95）

| 方法 | n | Over(Σ) | Over(mean) | Under(Σ) | Hit | Coverage |
|---|---|---:|---:|---:|---:|---:|
| B0_no_increase | 6643 | 0.00 | 0.0000 | 4984.95 | 0.0000 | 0.0000 |
| B1_pilot_only | 6643 | 6227.33 | 0.9374 | 1971.32 | 0.5823 | 0.6045 |
| B2_rolling_q95 | 6643 | 2477.79 | 0.3730 | 3291.66 | 0.6406 | 0.3397 |
| C_candidate_m2 | 6643 | 1495.26 | 0.2251 | 3664.77 | 0.6406 | 0.2648 |

| 指标 | 值 | 阈值 |
|---|---|---|
| C vs B2 Over improvement | 39.65% | GO>=10% |
| C vs B2 CoverageRatio | 77.97% | GO>=50% |
| 判定 | **GO — M2_active_increase_valid** | — |

> C vs B2 Over improvement=39.7%>=10.0%，CoverageRatio=78.0%>=50.0%，session 等权方向一致（44.8%）；M2 双重限制有效。

## 3. D3 test: system gate（S3 vs S2 rolling-Q95）

| arm | ①shortfall | ②unplanned_bess | ③pcc | ④flex |
|---|---:|---:|---:|---:|
| S0_unrestricted | 3627.42 | 2757.67 | 869.74 | 2976.44 |
| S1_conservative | 0.00 | 0.00 | 0.00 | 0.00 |
| S2_rolling_q95 | 2477.79 | 1285.50 | 1192.29 | 1693.29 |
| S3_our_scheme | 1495.26 | 753.17 | 742.10 | 1320.18 |

| 指标 | 值 | 阈值 |
|---|---|---|
| S3 vs S2 shortfall 降 | 39.65% | GO>=10% |
| S3 vs S2 unplanned_bess 降 | 41.41% | GO>=10% |
| 判定 | **GO — D3_system_value_valid** | — |

> S3 vs S2: unexpected_shortfall 降 39.7%>=10.0%，unplanned_bess 降 41.4%>=10.0%，PCC residual 未恶化，S3 flex(1320)>S1(0)×1.1。

## 4. 总判定

### **TEST_PASS**

- D2+D3 test 均通过。M2 时间外推验证通过。
- **直接转专利交底书**（claim_tree_v3_e7_fast.md + prior-art element map）。
- 不需做 24h 动态回放（除非明确要求）。

## 5. 产物文件

- `results/raw/e7_fast/ev_validation/d2_test_summary.csv`
- `results/raw/e7_fast/park_replay/d3_test_summary.csv`
- `results/raw/e7_fast/test_exposure_verdict.csv`
