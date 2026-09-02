# CORE_SEARCH_R2_P0B0：pilot-stable 下调事件上的响应幅度异质性

> 生成时间（UTC）：2026-09-02T14:11:47Z
> 配置：configs/core_search_r2.yaml（rule_version=core_search_r2，冻结）
> 方法学：自然控制事件推断设备响应，必须审计 (t,t+h] 控制输入轨迹（master plan 通用规则）

## 1. 目的

> pilot 持续压低后，车辆下调是否还存在值得预测的欠交付异质性？

## 2. 主判集与敏感性

- 主判集：binding down + pilot-stable(<1A over t..t+5) + train+val
- 敏感性：<2A
- 欠交付定义：r_1m < 0.8

## 3. response_fraction 汇总（pilot-stable）

| set | lag | n | median | p10 | p25 | p75 | p90 | IQR | under80 |
|---|---|---|---|---|---|---|---|---|---|
| primary(<1A) | 1 | 204 | 1.239 | 1.000 | 1.079 | 1.461 | 1.783 | 0.382 | 0.000 |
| primary(<1A) | 3 | 204 | 1.225 | 1.000 | 1.070 | 1.478 | 1.753 | 0.408 | 0.000 |
| primary(<1A) | 5 | 204 | 1.222 | 1.000 | 1.078 | 1.463 | 1.818 | 0.385 | 0.000 |
| sensitivity(<2A) | 1 | 364 | 1.295 | 1.000 | 1.133 | 1.554 | 1.877 | 0.420 | 0.014 |
| sensitivity(<2A) | 3 | 364 | 1.278 | 1.003 | 1.127 | 1.543 | 1.880 | 0.416 | 0.005 |
| sensitivity(<2A) | 5 | 364 | 1.281 | 1.000 | 1.118 | 1.541 | 1.889 | 0.423 | 0.008 |

## 4. 三区门判定

### 判定：**CLOSED**

> pilot-stable(<1A) 下欠交付几乎不存在：under80=0.000≤0.1 且 p10=1.000≥0.9；<2A 敏感性无方向性反转

| 指标 | 值 | 阈值 |
|---|---|---|
| primary under80 (r_1m<0.8) | 0.000 | CLOSED if ≤0.1 |
| primary r_1m p10 | 1.000 | CLOSED if ≥0.9 |
| primary r_1m median | 1.239 | — |
| primary r_1m IQR | 0.382 | — |
| sensitivity(<2A) under80 | 0.014 | 无方向性反转 |
| sensitivity(<2A) p10 | 1.000 | 无方向性反转 |
| sensitivity reversed | False | False |

## 5. station 分层（描述性，不参与主门）

| station_id | n | r_1m_median | under80 |
|---|---|---|---|
| 2-39-79-382 | 17 | 1.384 | 0.000 |
| 2-39-79-378 | 15 | 1.277 | 0.000 |
| 2-39-79-380 | 14 | 1.387 | 0.000 |
| 2-39-79-376 | 14 | 1.446 | 0.000 |
| 2-6-3-1623 | 13 | 1.031 | 0.000 |
| 2-39-79-379 | 12 | 1.417 | 0.000 |
| 2-39-79-377 | 11 | 1.409 | 0.000 |
| 2-39-79-383 | 10 | 1.446 | 0.000 |
| 2-6-3-1631 | 9 | 1.065 | 0.000 |
| 2-6-3-1632 | 8 | 1.130 | 0.000 |
| 2-6-3-1628 | 8 | 1.048 | 0.000 |
| 2-6-3-1624 | 7 | 1.000 | 0.000 |
| 2-6-3-1627 | 7 | 1.000 | 0.000 |
| 2-39-127-19 | 7 | 1.194 | 0.000 |
| 2-6-3-1625 | 6 | 1.129 | 0.000 |
| 2-6-3-1629 | 6 | 1.074 | 0.000 |
| 2-39-79-381 | 6 | 1.201 | 0.000 |
| 2-6-3-1626 | 5 | 1.000 | 0.000 |
| 2-39-90-440 | 2 | 1.330 | 0.000 |
| 2-105-277-1698 | 2 | 1.305 | 0.000 |

## 6. robustness appendix（step_magnitude × retention_5m，non-gating）

| step_magnitude_bin | n | retention_5m median | p25 | p75 |
|---|---|---|---|---|
| large | 19 | 1.000 | 0.999 | 1.000 |
| medium | 60 | 0.999 | 0.986 | 1.004 |
| small | 125 | 1.000 | 0.992 | 1.005 |

> 注：此表只作 robustness，不重新打开 R2-A（R2-A 已 CLOSED）。

## 7. 结论

- 下调欠交付几乎不存在 → **R2-B CLOSED**（无 selection problem）。
- 下调侧高度可靠、常过冲（r>1）；唯一变化在过冲方向，指向服务代价 → R2-C。

## 8. 产物文件

- `results/raw/core_search/r2_p0b0/binding_down_pilot_trace.parquet`
- `results/raw/core_search/r2_p0b0/r2_p0b0_gate_verdict.csv`
- `results/raw/core_search/r2_p0b0/r2_p0b0_summary.csv`
- `results/raw/core_search/r2_p0b0/station_strata.csv`
- `results/raw/core_search/r2_p0b0/step_magnitude_robustness.csv`
