# E7-FAST D0 数据充分性门报告

> 生成时间（UTC）：2026-08-13T05:17:05Z
> 配置：`D:\JobWorkspaces\light_storage_ev-v2\patent_preexperiment\configs\e7_fast.yaml`（rule_version=e7_fast_v1，冻结）
> 依据：review/工商业园区光储充快速闭环验证.md §4-7 / §36 step 2-4

## 1. 冻结纪律

- 阈值/规则在查看任何事件计数前冻结于 `configs/e7_fast.yaml`。
- gate 主判集 = train+validation（拟合集）；test 报告 single-exposure 可用量；office001 external 单列不计入 gate。
- 不修改 frozen P2/P2.1；只读复用 phase3_p2.d1 / phase3_p2.boundary。

## 2. D0-1 信息类别覆盖审计

### 按 site × info_mode × split 汇总

| site | info_mode | split | cycle_count | session_count | station_count | month_count | share_of_active_min |
|---|---|---|---|---|---|---|---|
| caltech | M2_pilot_actual | stress | 1188313 | 3754 | 139 | 7 | 0.0729 |
| caltech | M2_pilot_actual | test | 2113177 | 7356 | 130 | 8 | 0.1297 |
| caltech | M2_pilot_actual | train | 5188503 | 15409 | 82 | 10 | 0.3185 |
| caltech | M2_pilot_actual | validation | 3049325 | 9871 | 133 | 10 | 0.1872 |
| caltech | M3_current_only | test | 421 | 1 | 1 | 1 | 0.0 |
| caltech | M3_current_only | train | 4488015 | 13257 | 54 | 7 | 0.2755 |
| caltech | M4_history_insufficient | stress | 19846 | 4039 | 143 | 5 | 0.0012 |
| caltech | M4_history_insufficient | test | 42427 | 10528 | 132 | 7 | 0.0026 |
| caltech | M4_history_insufficient | train | 150763 | 31585 | 82 | 16 | 0.0093 |
| caltech | M4_history_insufficient | validation | 51468 | 10528 | 133 | 7 | 0.0032 |
| jpl | M2_pilot_actual | stress | 16406 | 44 | 23 | 1 | 0.0014 |
| jpl | M2_pilot_actual | test | 987548 | 2760 | 50 | 7 | 0.0858 |
| jpl | M3_current_only | stress | 1004054 | 2545 | 52 | 5 | 0.0872 |
| jpl | M3_current_only | test | 888794 | 2215 | 52 | 6 | 0.0772 |
| jpl | M3_current_only | train | 6404308 | 15076 | 52 | 11 | 0.5565 |
| jpl | M3_current_only | validation | 2062158 | 5025 | 52 | 5 | 0.1792 |
| jpl | M4_history_insufficient | stress | 13374 | 2591 | 52 | 4 | 0.0012 |
| jpl | M4_history_insufficient | test | 25006 | 5027 | 52 | 10 | 0.0022 |
| jpl | M4_history_insufficient | train | 78828 | 15079 | 52 | 11 | 0.0068 |
| jpl | M4_history_insufficient | validation | 27854 | 5026 | 52 | 5 | 0.0024 |
| office001 | M2_pilot_actual | external | 493986 | 1386 | 8 | 22 | 0.9859 |
| office001 | M4_history_insufficient | external | 7083 | 1474 | 8 | 22 | 0.0141 |

> 关注：M2_pilot_actual（pilot+actual+history 充分）是否覆盖足够多 cycle/session/station/month；
> M3_current_only（actual+history，无 pilot）是否广泛存在（current-only 主数据现实）。

## 3. D0-2 自然 pilot step 事件库

### 按 direction × site × split 事件计数

| direction | site | split | events | sessions | stations | months |
|---|---|---|---|---|---|---|
| down | caltech | stress | 2535 | 1482 | 84 | 6 |
| down | caltech | test | 4479 | 2084 | 90 | 8 |
| down | caltech | train | 13537 | 6254 | 59 | 10 |
| down | caltech | validation | 7188 | 3898 | 71 | 10 |
| down | jpl | stress | 81 | 30 | 18 | 1 |
| down | jpl | test | 5707 | 2129 | 47 | 7 |
| down | office001 | external | 1277 | 755 | 8 | 22 |
| up | caltech | stress | 1122 | 505 | 48 | 5 |
| up | caltech | test | 2582 | 671 | 56 | 8 |
| up | caltech | train | 7543 | 2806 | 58 | 10 |
| up | caltech | validation | 4159 | 1612 | 54 | 9 |
| up | jpl | stress | 76 | 28 | 18 | 1 |
| up | jpl | test | 4105 | 1389 | 42 | 7 |
| up | office001 | external | 548 | 220 | 8 | 21 |

## 4. 数据充分性门判定（review §7 三级门）

**gate 主判集（train+validation，排除 office001/stress）**

| 指标 | 值 | 阈值 |
|---|---|---|
| 正向上调事件 | 11702 | A>=100 / B 30-99 / C<30 |
| 正向 unique sessions | 4418 | A>=30 |
| 正向 stations | 62 | A>=5 |
| 正向 months | 18 | A>=2 |
| 负向事件 | 20725 | >=50 |
| 负向 sessions | 10152 | >=20 |
| 负向 stations | 77 | >=3 |
| 负向充分(neg_sufficient) | True | True |
| test 正向事件（single-exposure 可用量，不入 gate） | 6687 | — |
| external(office001) 正向事件（不入 gate） | 548 | — |

### 判定：**A_level — GO_active_increase** （GO）

> 正 pilot 上调事件 11702>=100、sessions 4418>=30、stations 62>=5、months 18>=2；足以支持主动增加功率实验。

## 5. 红灯检查（review §37）

- 无红灯触发。

## 6. 下一步决策（review §36）

- D0 通过（A 级）。进入 §36 step 6：补 M2 数值上限 → step 7 真实 EV 事件比较（pilot-only / rolling-Q95 / Candidate）。

## 7. 产物文件

- `results/raw/e7_fast/d0/d0_info_mode_coverage.csv`（D0-1 明细）
- `results/raw/e7_fast/d0/d0_info_mode_summary.csv`（D0-1 汇总）
- `results/raw/e7_fast/d0/d0_pilot_step_events.parquet`（D0-2 事件库）
- `results/raw/e7_fast/d0/d0_evidence_registry.csv`（证据台账）
