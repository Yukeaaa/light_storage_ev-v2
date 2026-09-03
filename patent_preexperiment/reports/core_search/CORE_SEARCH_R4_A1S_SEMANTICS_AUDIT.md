# CORE_SEARCH_R4_A1S_SEMANTICS_AUDIT：timestamp/execution semantics adjudication

> 生成时间（UTC）：2026-09-03T14:02:30Z
> 纪律：纠错审计；不改 threshold，不执行 A1b，不进入系统层。

## 1. 背景

09419f3 的实现忠实执行 supplementary UTC+1/UTC+2 表，但该结果与论文公开
Test 2 执行 anchor 严重冲突。因此 A1a STRONG_A1B 先挂起，用论文 anchor 裁决
timestamp/execution pairing 语义。

## 2. 冻结 hypotheses

| hypothesis | alignment |
|---|---|
| S0_raw_label | raw timestamp label direct pairing |
| S1_supplementary_timezone | schedule UTC+1 -> UTC; measurement UTC+2 -> UTC |

## 3. Published anchors

| anchor | value |
|---|---:|
| rmse_kw | 13.87 |
| mean_absolute_deviation_kw | 3.31 |
| cumulative_unfulfilled_energy_kwh | 238.0 |
| first_major_curtailment_hour | 61.0 |
| single_window_deviation_kwh | 52.5 |

## 4. Reproduction metrics

| hypothesis | RMSE kW | MAD kW | unfulfilled kWh | first major hour | single-window kWh | tolerance hits | anchor score |
|---|---:|---:|---:|---:|---:|---:|---:|
| S0_raw_label | 23.2283 | 11.6492 | 540.384 | 61 | 49.1103 | 2 | 4.52921 |
| S1_supplementary_timezone | 1183.01 | 632.942 | 24250.7 | 2 | 1209.55 | 0 | 633.447 |

## 5. Adjudication

verdict：**S0_RAW_LABEL_AUTHORITATIVE**
reason：S0 dominates S1 against published Test 2 anchors
dominance_ratio：139.858
A1a status：**SUSPENDED_PENDING_RERUN_UNDER_S0**
A1b status：**BLOCKED**
system layer status：**BLOCKED**

S0 未完全复现论文连续指标的具体统计口径，但它在 RMSE/MAD/unfulfilled energy、
hour-61 重大偏差位置与单窗口偏差量级上压倒性接近 S1。S1 产生的是另一套物理世界，
因此 09419f3 的 STRONG_A1B 不可作为后续 A1b 依据。

## 6. Consequence

- A1a STRONG_A1B = SUSPENDED。
- raw-label execution alignment becomes authoritative for rerun. 极低 raw-label shortfall
  将作为 corrected A1a 的预期核验对象，而不是事后救援。
- A1b、控制器、系统层全部 BLOCKED，直到 corrected A1a 完成。

## 7. 产物

- `results/raw/core_search/r4_a1s/rwth_m5bat_a1s_hypothesis_metrics.csv`
- `results/raw/core_search/r4_a1s/rwth_m5bat_a1s_intervals.csv`