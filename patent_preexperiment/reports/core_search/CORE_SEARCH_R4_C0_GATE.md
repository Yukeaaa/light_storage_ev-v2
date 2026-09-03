# CORE_SEARCH_R4_C0_GATE：EVSE 基础设施事件存在性与量纲审计

> 生成时间（UTC）：2026-09-03T09:35:50Z
> 配置：configs/core_search_r4c0.yaml（rule_version=core_search_r4c0_v1，冻结）
> 纪律：不预测故障、不做控制器、不做系统收益结论；L1 operational 为主口径，L0 nominal 只作上界。

## 1. 事件定义

- 同 station、同 fault family、相邻记录 gap <= 2min 合并为同一 event。
- fault family：hard_disabled = DISABLED CHARGER；pilot_violation = DISABLED PILOT VIOLATION / PILOT VIOLATION。
- 同时保留 raw state，并输出 any_infrastructure_abnormal。

## 2. 核心量

| 指标 | 值 |
|---|---:|
| event_count | 396 |
| session_count | 421 |
| station_count | 49 |
| duration_median_min | 2.0000 |
| duration_p75_min | 15.2500 |
| duration_p90_min | 83.5000 |
| duration_max_min | 989.0000 |
| top1_event_share | 0.1136 |
| top2_event_share | 0.2172 |
| top3_event_share | 0.3182 |
| concurrency_p50 | 1.0000 |
| concurrency_p90 | 1.0000 |
| concurrency_max | 7.0000 |
| loss_fraction_l1_p50 | 0.0000 |
| loss_fraction_l1_event_share_ge_15pct | 0.0985 |
| active_fault_event_share | 0.2702 |
| state_loss_sync_share | 0.2399 |
| precursor_5m_share | 0.2020 |
| precursor_15m_share | 0.3232 |
| precursor_30m_share | 0.3763 |

## 3. 按 fault family

| fault_family | events | stations | median duration | p90 duration | ge15% event share |
|---|---:|---:|---:|---:|---:|
| hard_disabled | 299 | 39 | 1.0 | 55.2 | 0.087 |
| pilot_violation | 97 | 22 | 16.0 | 152.6 | 0.134 |

## 4. 判门

### 判定：**STOP**

STOP reasons：median operational lost-capacity fraction <5%

## 5. 产物

- `results/raw/core_search/r4_c0/r4_c0_events.csv`
- `results/raw/core_search/r4_c0/r4_c0_concurrency.csv`
- `results/raw/core_search/r4_c0/r4_c0_gate_stats.csv`