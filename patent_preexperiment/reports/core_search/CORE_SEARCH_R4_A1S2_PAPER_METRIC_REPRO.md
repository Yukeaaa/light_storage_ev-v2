# CORE_SEARCH_R4_A1S2_PAPER_METRIC_REPRO：S0 exact paper metric audit

> 生成时间（UTC）：2026-09-03T14:20:58Z
> 纪律：固定 S0 raw-label pairing；不搜索新 shift，不调 tolerance，不运行 A1b。

## 1. Paper Definition Evidence

- power_metric_text: Fig. 9 compares optimized schedule with measured power at the grid connection point and reports RMSE and mean absolute deviation.
- energy_metric_text: Fig. 11 panel b shows unfulfilled energy delivery to the grid in 15-minute resolution, defined as total energy deviation in the quarter-hour.
- event_metric_text: Fig. 10 reports a curtailment around hour 61 and a -52.50 kWh single 15-minute interval energy deviation.
- extraction_status: pdfminer text extraction; formulas not explicitly specified in extracted text

## 2. Metric Variant Reproduction

| family | variant | anchor | value | secondary | rel err | secondary err | pass |
|---|---|---|---:|---:|---:|---:|---|
| power | p_15min_mean | rmse_kw | 23.2283 | 11.6492 | 0.674718 | 2.51941 | False |
| power | p_1s_forward_fill_all | rmse_kw | 157.572 | 14.8284 | 10.3606 | 3.47989 | False |
| power | p_1s_forward_fill_exclude_first_15s | rmse_kw | 27.0447 | 4.95581 | 0.949867 | 0.497225 | False |
| power | p_1s_forward_fill_exclude_first_30s | rmse_kw | 25.1475 | 4.83632 | 0.813089 | 0.461123 | False |
| power | p_1s_forward_fill_exclude_first_60s | rmse_kw | 25.5387 | 4.86532 | 0.841291 | 0.469885 | False |
| energy | e_15min_unfulfilled_all_nonzero_schedule | cumulative_unfulfilled_energy_kwh | 540.384 | nan | 1.27052 | nan | False |
| energy | e_15min_unfulfilled_first_61h_nonzero_schedule | cumulative_unfulfilled_energy_kwh | 307.331 | nan | 0.291306 | nan | False |
| energy | e_15min_abs_deviation_first_61h | cumulative_unfulfilled_energy_kwh | 557.55 | nan | 1.34265 | nan | False |
| energy | e_15min_abs_deviation_ge_3_61kwh_first_61h | cumulative_unfulfilled_energy_kwh | 449.035 | nan | 0.886702 | nan | False |
| energy | e_15min_abs_deviation_ge_5kwh_first_61h | cumulative_unfulfilled_energy_kwh | 424.911 | nan | 0.785341 | nan | False |
| energy | e_15min_abs_deviation_ge_10kwh_all | cumulative_unfulfilled_energy_kwh | 224.305 | nan | 0.0575417 | nan | True |
| event | first_major_curtailment_hour | first_major_curtailment_hour | 61 | nan | 0 | nan | True |
| event | largest_single_window_abs_deviation | single_window_deviation_kwh | 49.1103 | nan | 0.0645661 | nan | True |

## 3. Decision

verdict：**DATA_SEMANTICS_OR_METRIC_UNRESOLVED**
R4-A status：**R4_A_STOP**
power_pass：False
energy_pass：True
event_pass_count：2
A1b status：**BLOCKED**
system layer status：**BLOCKED**

S0 固定配对能复现 hour-61 与单窗口偏差锚点，但公开文本可还原的 power RMSE/MAD
口径均未在 ±15% 内同时复现。因此 S0 只能称 preferred pairing，不能升级为
authoritative execution alignment。按预注册规则，R4-A STOP，不运行 corrected A1a/A1b。

## 4. Outputs

- `results/raw/core_search/r4_a1s2/rwth_m5bat_a1s2_metric_variants.csv`