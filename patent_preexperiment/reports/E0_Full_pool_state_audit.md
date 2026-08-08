# E0-Full 控制池状态表审计（E0F-04）

## 口径声明

pool_state 把 session_response_1min 聚合到池级：pool_id = site + garage(cluster)，
禁止跨车库合并；只含 matched 会话（严格会话验证口径），static_only 不进池表。
只做确定性聚合与一致性验收，不生成 E3 机会指标。
- pool_registry：115 行（pool_id×station），3 个池，115 个 gold 池站，冻结 115。
- pool_state_1min：1,458,623 行，81 分区。
- pool_state_5min：293,122 行，3 池。
- 能量口径：actual_power_kw/60；measured_kwh/estimated_kwh 按 power_source
 ∈ {measured, computed}/{estimated} 拆分（与 gold 口径一致）。

## 一致性验收

- 跨粒度（5min == 1min 同 reducer 重算全等）：PASS；5min 总能量 483227.92 kWh
- session 同源（从 session_response_1min 重聚合全等）：PASS；检查 81 个分区
- gold 一致性：PASS；每个 gold 池中位 |rel dev| < tolerance（overall 中位仅作摘要，p95 仅报告）；gold_consistency=false 即 hard STOP（审查结论20 P0-1）

### gold 逐池（per-pool gate：每个池中位 |rel dev| < tolerance）

| pool_id | buckets | 中位 |rel dev| | 中位 rel dev | p95 | gold kWh | ours kWh | PASS |
|---|---|---|---|---|---|---|---|
| caltech__California_Garage_01 | 94,957 | 0.002712 | 0.000420 | 0.026296 | 130549.42 | 129964.85 | PASS |
| jpl__Arroyo_Garage_01 | 94,326 | 0.001982 | 0.000017 | 0.142578 | 353914.91 | 331522.40 | PASS |
| office001__Parking_Lot_01 | 37,804 | 0.002241 | 0.000064 | 0.011446 | 21732.16 | 21740.67 | PASS |

## 冻结证据池复现审计（#15 acceptance-3）

- sample_layer <-> match_status 1:1（L1<->matched、L0<->static_only）：PASS
- **caltech_main_window**（site=caltech，field_mode=None）：冻结窗口 ['2018-11', '2019-03', '2019-04', '2019-05', '2019-08', '2019-10'] 内 n=11,776 会话，matched=6,060，static_only=5,716；组成 {'matched/L1_strict_matched': 6060, 'static_only/L0_static_extension': 5716}；split 分布 {'matched/train': 4936, 'matched/validation': 1124, 'static_only/train': 3952, 'static_only/validation': 1764}；role={"('main',)": 11776}
- **jpl_current_only_window**（site=jpl，field_mode=current_only）：冻结窗口 ['2018-11', '2019-03', '2019-04', '2019-05', '2019-08', '2019-10'] 内 n=9,023 会话，matched=9,023，static_only=0；组成 {'matched/L1_strict_matched': 9023}；split 分布 {'matched/train': 7333, 'matched/validation': 1690}；role={"('current_only_fallback',)": 9023}
- K1 冻结样本计数交叉核对：PASS（matched 子集 == k1_sample_registry，{'caltech_main_window': 6060, 'jpl_current_only_window': 9023}）

## 池清单（n_stations / gold）

- caltech__California_Garage_01：55 stations，gold
- jpl__Arroyo_Garage_01：52 stations，gold
- office001__Parking_Lot_01：8 stations，gold

## 规则依据

- 池定义：`pool_id = site + garage(cluster) 唯一组合；禁止跨车库合并`
- 范围：`只含 matched 会话（严格会话验证口径）；static_only 仅用于响应机制扩展，不进池表`
- gold 冻结站数：`115`；tolerance：`0.02`
- 证据池：`冻结证据池人口审计：windows 内 matched 会话子集必须 == k1_sample_registry.csv 冻结计数（machine-verifiable）`
