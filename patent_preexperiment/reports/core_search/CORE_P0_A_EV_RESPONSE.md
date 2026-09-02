# CORE_P0_A：真实 EV 响应时间谱

> 生成时间（UTC）：2026-09-02T13:09:01Z
> 配置：`D:\JobWorkspaces\light_storage_ev-v2\patent_preexperiment\configs\core_search_v1.yaml`（rule_version=core_search_v1，冻结）
> 依据：review/CORE-PATENT SEARCH：系统级核心专利筛选阶段.md §五
> 数据来源：results/raw/e7_fast/d0/d0_pilot_step_events.parquet（E7-FAST D0 复用，DERIVED_REAL）

## 1. 目的

> EV 到底是不是一种具有可利用时间动态的柔性资源？
> 严格区分 binding / non-binding 事件，对 binding 事件计算 1/3/5min response_fraction。

## 2. binding / non-binding 分类

- tolerance = 0.5 kW
- binding decrease: pilot_after < actual_before − 0.5
- binding increase: pilot_after > actual_before + 0.5

### 全量事件分类（含 test/external/stress）

| direction | binding | events |
|---|---|---|
| down | binding | 8668 |
| down | non_binding | 26136 |
| up | binding | 18752 |
| up | non_binding | 1383 |
| **合计** | | 54939 |
| **binding 占比** | | 27420/54939 = 49.9% |

### gate 主判集（train+validation，排除 external/stress）

| direction | binding | events | sessions | stations | months |
|---|---|---|---|---|---|
| up | binding | 11698 | 4416 | 62 | 18 |
| down | binding | 4699 | 2631 | 61 | 18 |

## 3. response_fraction 汇总（binding 事件，train+validation）

- down: r = (actual_before − actual_lag) / (actual_before − pilot_after)
- up: r = (actual_lag − actual_before) / (pilot_after − actual_before)
- clip [0.0, 2.0]

| direction | lag_min | median | p25 | p75 | mean | std | count |
|---|---|---|---|---|---|---|---|
| down | 1 | 1.1450 | 0.2983 | 1.9365 | 1.0703 | 0.7571 | 4699 |
| down | 3 | 0.6475 | 0.0091 | 1.7186 | 0.8458 | 0.8138 | 4699 |
| down | 5 | 0.5853 | 0.0068 | 1.7434 | 0.8362 | 0.8216 | 4699 |
| up | 1 | 0.2369 | 0.0000 | 0.8183 | 0.4739 | 0.5648 | 11698 |
| up | 3 | 0.0095 | 0.0000 | 0.7064 | 0.3837 | 0.5440 | 11698 |
| up | 5 | 0.0043 | 0.0000 | 0.6454 | 0.3739 | 0.5818 | 11698 |

> **关键诊断**：1/3/5min median 是否不同 → 是否有可利用的时间动态。
> 若 1min median ≈ 1.0 且 std 很小 → 1min 内确定性完全响应 → BESS先接EV接力 无意义。

## 4. 车辆间响应异质性（station 级）

- station 数：123
- response_fraction_3m median 的 IQR（站间异质性）：0.2019
- 判据：IQR > 0.05 → 存在稳定异质性

## 5. session repeatability（同 session first → later）

- 有 >=2 binding 事件的 session 数：3033
- first vs later response_fraction_3m Pearson corr：0.2972
- 判据：|corr| > 0.1 → 最近响应对下次有信息价值

## 6. 分层汇总（binding 事件，train+validation）

### 按 site

| value | events | sessions | rf_3m_median |
|---|---|---|---|
| caltech | 16397 | 5652 | 0.0852 |

### 按 station_id

| value | events | sessions | rf_3m_median |
|---|---|---|---|
| 2-39-79-381 | 1065 | 169 | 0.0041 |
| 2-39-79-376 | 773 | 194 | 0.2656 |
| 2-39-79-383 | 767 | 173 | 0.2514 |
| 2-39-79-378 | 763 | 182 | 0.1161 |
| 2-39-79-379 | 755 | 197 | 0.1433 |
| 2-39-79-377 | 681 | 196 | 0.4175 |
| 2-39-79-380 | 604 | 146 | 0.2494 |
| 2-6-3-1631 | 565 | 163 | 0.0875 |
| 2-105-277-1697 | 511 | 118 | 0.0000 |
| 2-6-3-1623 | 499 | 194 | 0.1444 |
| 2-6-3-1629 | 478 | 181 | 0.3262 |
| 2-6-3-1626 | 466 | 159 | 0.1538 |
| 2-39-79-382 | 466 | 119 | 0.5912 |
| 2-6-3-1628 | 450 | 193 | 0.2944 |
| 2-6-3-1624 | 440 | 147 | 0.0114 |

### 按 month

| value | events | sessions | rf_3m_median |
|---|---|---|---|
| 2019-01 | 1566 | 472 | 0.1269 |
| 2019-10 | 1349 | 485 | 0.5027 |
| 2018-12 | 1297 | 391 | 0.2125 |
| 2019-08 | 1206 | 437 | 0.1259 |
| 2019-06 | 1161 | 369 | 0.0083 |
| 2019-05 | 1137 | 390 | 0.0269 |
| 2018-11 | 1129 | 354 | 0.1269 |
| 2019-09 | 1126 | 422 | 0.4152 |
| 2019-04 | 1099 | 402 | 0.0192 |
| 2020-01 | 1050 | 409 | 0.0395 |
| 2019-11 | 1048 | 367 | 0.4266 |
| 2019-07 | 977 | 344 | 0.0170 |
| 2019-02 | 851 | 293 | 0.0093 |
| 2019-03 | 781 | 257 | 0.0155 |
| 2020-03 | 568 | 243 | 0.0195 |

### 按 session_phase

| value | events | sessions | rf_3m_median |
|---|---|---|---|
| late | 8281 | 2775 | 0.0128 |
| mid | 7022 | 3665 | 0.1909 |
| early | 1094 | 1046 | 0.2414 |

### 按 actual_before_bin

| value | events | sessions | rf_3m_median |
|---|---|---|---|
| low | 6980 | 2763 | 0.0029 |
| high | 5383 | 2651 | 0.1400 |
| mid | 4034 | 2284 | 0.3773 |

### 按 step_magnitude_bin

| value | events | sessions | rf_3m_median |
|---|---|---|---|
| small | 11100 | 4351 | 0.0345 |
| medium | 4751 | 2479 | 0.1613 |
| large | 546 | 504 | 0.8043 |

### 按 previous_pilot_bin

| value | events | sessions | rf_3m_median |
|---|---|---|---|
| low | 5946 | 2481 | 0.0050 |
| high | 5767 | 2807 | 0.1751 |
| mid | 4684 | 2478 | 0.1687 |

## 7. 门判定

### 判定：**GO**

> binding 事件充分（up=11698, down=4699）；可利用时间动态信号：1/3/5min 响应明显不同; 车辆间响应异质性 IQR=0.202; session repeatability corr=0.297

| 指标 | 值 | 阈值 |
|---|---|---|
| binding up 事件 (train+val) | 11698 | >=100 |
| binding down 事件 (train+val) | 4699 | >=100 |
| binding up sessions | 4416 | >=30 |
| binding down sessions | 2631 | >=30 |
| binding up stations | 62 | >=5 |
| binding down stations | 61 | >=5 |
| binding up months | 18 | >=2 |
| binding down months | 18 | >=2 |
| rf_1m median up | 0.2369 | NO_GO if >0.9 |
| rf_1m median down | 1.1450 | NO_GO if >0.9 |
| rf_1m std up | 0.5648 | NO_GO if <0.1 |
| rf_1m std down | 0.7571 | NO_GO if <0.1 |
| rf_3m median up | 0.0095 | — |
| rf_3m median down | 0.6475 | — |
| rf_5m median up | 0.0043 | — |
| rf_5m median down | 0.5853 | — |
| 时间动态不同 | True | True |
| 异质性 IQR | 0.2019 | >0.05 |
| repeatability corr | 0.2972 | |corr|>0.1 |
| binding 充分 | True | True |
| 1min 确定性响应 | False | False |

## 8. Decision #1 含义

- EV 具有可利用时间动态 → CORE-A（BESS-EV 接力）可启动。
- 配合 P0-B 量纲门，两门都过则正式启动 A/B/C。

## 9. 产物文件

- `results/raw/core_search/p0_a/binding_events.parquet`（全量 binding 事件）
- `results/raw/core_search/p0_a/response_1_3_5m_summary.csv`（1/3/5min 响应汇总）
- `results/raw/core_search/p0_a/station_response_summary.csv`（站级异质性）
- `results/raw/core_search/p0_a/session_repeatability.csv`（session 一致性）
- `results/raw/core_search/p0_a/strata_binding_summary.csv`（分层汇总）
