# CORE_SEARCH_R4_A1_TRACKING_GATE：RWTH M5BAT tracking magnitude

> 后续纠错：R4-A1S 使用作者论文 Test 2 published anchors 裁决 timestamp/execution 语义，判定
> S0 raw-label execution alignment 为权威口径；本报告中基于 S1 supplementary UTC+1/UTC+2
> 归一得到的 A1a STRONG_A1B = **SUSPENDED**，不得作为 A1b 或系统层依据。
> 详见 `reports/core_search/CORE_SEARCH_R4_A1S_SEMANTICS_AUDIT.md`。

> 生成时间（UTC）：2026-09-03T10:16:17Z
> 纪律：A1-0 + A1a only；不执行 A1b，不进入系统层，不称 BESS 物理降额。

## 1. A1-0 timezone-normalized alignment

| test | schedule intervals | usable intervals | coverage | raw label hits | UTC range note |
|---:|---:|---:|---:|---:|---|
| 1 | 288 | 0 | 0.0000 | 0 | 2023-08-14 10:00:00+00:00 -> 2023-08-17 10:00:00+00:00 |
| 2 | 288 | 284 | 0.9861 | 288 | 2024-05-28 10:00:00+00:00 -> 2024-05-31 10:00:00+00:00 |

A1-0 verdict：**PASS**，timezone-normalized alignment usable。

## 2. A1a tracking magnitude

| 指标 | 值 |
|---|---:|
| verdict | STRONG_A1B |
| reason | active 15min equivalent tracking shortfall >=20% |
| active_interval_count | 96 |
| charge_interval_count | 62 |
| discharge_interval_count | 34 |
| requested_energy_kwh_abs | 34505.5 |
| shortfall_energy_kwh | 24014.3 |
| steady_shortfall_energy_kwh | 22287.5 |
| abs_tracking_error_energy_kwh | 27911 |
| equivalent_shortfall_ratio | 0.695956 |
| steady_equivalent_shortfall_ratio | 0.645912 |
| equivalent_abs_error_ratio | 0.808887 |
| mae_kw | 1162.96 |
| steady_mae_kw | 1160.72 |
| p50_abs_error_kw | 928.074 |
| p90_abs_error_kw | 2436.14 |
| p95_abs_error_kw | 2518.28 |
| p50_shortfall_kw | 291.407 |
| p90_shortfall_kw | 2436.07 |
| p95_shortfall_kw | 2518.28 |
| charge_equivalent_shortfall_ratio | 0.647281 |
| discharge_equivalent_shortfall_ratio | 0.753211 |
| large_shortfall_interval_share | 0.604167 |
| max_consecutive_large_shortfall_intervals | 8 |
| top5_abs_error_share | 0.160379 |

## 3. 判定

A1a verdict：**STRONG_A1B**。
若 A1a 未达到 WORTH_A1B，不启动 A1b、控制器或系统传播。

## 4. raw-label diagnostic

| 指标 | 值 |
|---|---:|
| active_interval_count | 98 |
| equivalent_shortfall_ratio | 0.0151282 |
| verdict | STOP |

raw-label alignment 只作 sensitivity/diagnostic。它与官方时区归一主口径出现量级分歧：
raw-label tracking shortfall 很低，而 timezone-normalized shortfall 很高。
因此 A1a 的主结果只能说明按 supplementary 时区语义存在 material tracking gap；
进入 A1b 前必须人工复核 timestamp 语义，不能直接把该 gap 解释为 BESS 物理能力原因。

## 5. 产物

- `reports/core_search/CORE_SEARCH_R4_A1_PREREG.md`
- `results/raw/core_search/r4_a1/rwth_m5bat_a1_alignment.csv`
- `results/raw/core_search/r4_a1/rwth_m5bat_a1_intervals.csv`
- `results/raw/core_search/r4_a1/rwth_m5bat_a1_summary.csv`
