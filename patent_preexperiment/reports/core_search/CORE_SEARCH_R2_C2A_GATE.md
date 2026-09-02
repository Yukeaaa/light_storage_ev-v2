# CORE_SEARCH_R2_C2A_GATE：在线恢复风险可预测性门

> 生成时间（UTC）：2026-09-02T15:26:19Z
> 配置：configs/core_search_r2c2.yaml（rule_version=core_search_r2c2，冻结）

## 1. 目的

> 在线安全信息能否比 reported_service_slack 明显更好识别真实 post-charge temporal slack？

## 2. 数据与标签

| 指标 | 值 |
|---|---|
| caltech matched 会话数 | 11820 |
| train / validation | 7092 / 2364 |
| T_slack 中位（小时） | 2.34 |
| has_slack(>=15min) 占比 | 0.710 |

## 3. 可预测性（validation）

| 指标 | baseline(reported_slack) | candidate(OLS) | Δ |
|---|---|---|---|
| AUC(has_slack) | 0.705 | 0.679 | -0.026 |
| Spearman(T_slack) | 0.341 | 0.307 | -0.034 |
| false-safe rate | 0.130 | 0.150 | — |

## 4. 门判定

### 判定：**STOP**

- 在线特征几乎无增量 → R2-C 作为核心专利方向中止。

## 5. 术语纪律

- T_slack 仅作离线标签；不用人工补能折扣函数。
- false-safe = 预测有恢复余量实际无余量的比例。
