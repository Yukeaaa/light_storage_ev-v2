# CORE_SEARCH_R4_A0b_RWTH_OFFICIAL_AUDIT：RWTH M5BAT 官方数据落地审计

> 生成时间（UTC）：2026-09-03T10:04:47Z
> 配置：configs/core_search_r4a0b.yaml（rule_version=core_search_r4a0b_v1，冻结）
> 纪律：只做官方数据源、字段、单位、粒度、schedule 语义与对齐审计；不启动 Round 5。

## 1. 数据源状态

| 指标 | 值 |
|---|---|
| DOI | 10.18154/RWTH-2025-06555 |
| source status | **DATA_SOURCE_RESOLVED** |
| local root | `D:\Users\Micko\Documents\工作\华润集控\光储充\数据\RWTH` |
| local files found | 4 |
| data level | **LEVEL B** |
| level meaning | actual + optimized dispatch schedule + SOC with at least one aligned test; tracking capability only |

## 2. 文件、字段、单位与采样频率

| file | rows | columns | sampling | start | end |
|---|---:|---:|---|---|---|
| test_1_measurement_data.csv | 259201 | 15 | 1 second | 2023-08-14 12:00:00 | 2023-08-17 12:00:00 |
| test_1_schedule_data.csv | 288 | 17 | 15 minutes | 2022-10-05 00:00:00 | 2022-10-07 23:45:00 |
| test_2_measurement_data.csv | 259201 | 15 | 1 second | 2024-05-28 12:00:00 | 2024-05-31 12:00:00 |
| test_2_schedule_data.csv | 288 | 17 | 15 minutes | 2024-05-28 12:00:00 | 2024-05-31 11:45:00 |

字段单位详见 `results/raw/core_search/r4_a0b/rwth_m5bat_2025_schema.csv`。

## 3. schedule 语义

| 项 | 审计结论 |
|---|---|
| source | M5Use scheduling optimization framework |
| optimization_type | MILP |
| time_resolution | 15 minutes |
| execution_semantics | operation plans used for physical system execution and comparison with measurement data |
| reoptimization_during_execution | NOT_IDENTIFIED_IN_AUDIT |
| timestamp_timezone_note | schedule UTC+1; measurement UTC+2 per supplementary field table |

## 4. timestamp 对齐

| test | measurement range | schedule range | overlap seconds | schedule timestamp hits | raw label aligned | semantics |
|---:|---|---|---:|---:|---|---|
| 1 | 2023-08-14 12:00:00 -> 2023-08-17 12:00:00 | 2022-10-05 00:00:00 -> 2022-10-07 23:45:00 | 0.0 | 0 | False | NOT_ALIGNED |
| 2 | 2024-05-28 12:00:00 -> 2024-05-31 12:00:00 | 2024-05-28 12:00:00 -> 2024-05-31 11:45:00 | 258300.0 | 288 | True | RAW_LABEL_ALIGNED_WITH_TIMEZONE_CAVEAT |

- test_1 schedule 与 measurement 时间戳不重叠，不能作为严格对齐回放样本。
- test_2 schedule 与 measurement 原始 timestamp 标签同期，15 分钟 schedule timestamp 均命中 1 秒 measurement。
- supplementary PDF 同时标注 schedule timestamp 为 UTC+1、measurement timestamp 为 UTC+2；
  因此 tracking gate 前必须冻结时区归一化规则，不能在本审计中声称绝对时间已无歧义严格对齐。

## 5. Level 判定

| 字段族 | present | matched keywords |
|---|---|---|
| actual_bess_power | True | bess_power_ac, power_ac, power_dc |
| dispatch_schedule | True | schedule_data, optimized schedules |
| soc | True | bess_soc, lmo1_soc, lmo2_soc, lmo3_soc, lmo4_soc |
| temperature | False |  |
| charge_discharge_limit | False |  |
| alarms_status | False |  |

结论：**LEVEL B**。官方数据已落地，具备 actual power + optimized schedule + SOC，
且 test_2 存在原始 timestamp 标签对齐；但未发现 temperature / status / power limit / alarm，
test_1 也不能作为严格对齐样本。因此只能进入 tracking-capability gate，禁止称 BESS 物理降额。

## 6. 后续唯一允许问题

> 在相同 SOC 和外部 dispatch requirement 下，真实 BESS 的 schedule-tracking shortfall 是否存在显著、重复、状态相关的结构。

## 7. 产物

- `data_registry/rwth_m5bat_2025_registry.json`
- `results/raw/core_search/r4_a0b/rwth_m5bat_2025_schema.csv`
- `results/raw/core_search/r4_a0b/rwth_m5bat_2025_alignment.csv`