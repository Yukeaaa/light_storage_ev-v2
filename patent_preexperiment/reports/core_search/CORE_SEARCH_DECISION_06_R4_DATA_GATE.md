# CORE_SEARCH_DECISION_06_R4_DATA_GATE — Round 4 路线选择

> 生成时间（UTC）：2026-09-03T09:36:10Z
> 依据：CORE_SEARCH_R4_C0_GATE.md + CORE_SEARCH_R4_A0_DATA_AUDIT.md
> 决策纪律：两条线完成数据门后只保留 1 条主线；不靠 ML、子集或极端事件救活。

## 1. 冻结决策规则

1. R4-C 若存在多站、重复、系统相关量级的真实可用容量损失 → R4-C 主线。
2. 若 R4-C 量纲弱，但 R4-A = LEVEL A → R4-A 主线。
3. 若 R4-A = LEVEL B → 只允许 tracking shortfall 量级判断，不自动进入系统开发。
4. 两边均弱 → Round 4 STOP，不靠 ML / 子集 / 极端事件救活。

## 2. R4-C0 摘要

| 指标 | 值 |
|---|---:|
| verdict | STOP |
| event_count | 396 |
| station_count | 49 |
| top2_event_share | 0.21717171717171718 |
| loss_fraction_l1_p50 | 0.0 |
| loss_fraction_l1_event_share_ge_15pct | 0.09848484848484848 |
| active_fault_event_share | 0.2702020202020202 |
| multi_station_disabled_minutes | 955 |

## 3. R4-A0 摘要

| 指标 | 值 |
|---|---|
| data_level | **DATA_PENDING** |
| local_files_found | 0 |
| time_semantics_status | NOT_AUDITABLE_WITHOUT_METADATA |

## 4. 判定

### **ROUND4_STOP_OR_DATA_PENDING**

> R4-C not GO and R4-A lacks Level A/B data

不进入系统层；先补数据或关闭 Round 4。