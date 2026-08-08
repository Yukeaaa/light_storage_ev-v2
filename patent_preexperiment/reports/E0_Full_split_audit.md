# E0-Full 时间切分审计（E0F-02）

## 口径声明

split registry 表示**时间位置**，不表示**训练资格**。
全部 85,877 个有静态时序的会话进入统一 registry；40,644 matched 属 L1 严格集，
45,233 static_only 属 L0 扩展集；api_only 无静态响应时序，不进入本 registry。
训练资格由后续实验显式过滤：E1 严格主结论 = `sample_layer==L1_strict_matched` ∧ `split in {train,validation,test}` ∧ `role==main`；
JPL boundary/current_only_fallback 即使 `split==train` 也不得获得主模型调参资格。

## 验收不变量

- registry 行数：85877
- matched：40644
- static_only：45233
- api_only：0
- session_id 唯一：True
- 每会话单一 split：True
- sample_layer↔match_status 一致：True
- external 不进主切分：True
- stress 不进主切分：True

## connection_time_source 分布

connection_time_source  api_metadata  first_observation_fallback
match_status                                                    
matched                        40644                           0
static_only                        0                       45233

- anomaly 会话：0（仅登记，禁止自动替换）

## field_mode 分布（field_mode_registry 同源）

field_mode
measured_pilot       46173
current_only         25585
measured_no_pilot    14119

## role 分布（独立于时间 split）

role
main                     56680
current_only_fallback    26843
external_only             1474
boundary                   880

## stress 分布

_m
2019-12    2909
2020-02    3292
2020-04     529
2020-12     199

注：stress 标记（=True 含外部站点）总数 6929，其中 office001 外部站点在异常月 299 个会话 因 external 优先被归为 `split==external`（不进 stress/test 主集合）。

## 主切分（train/validation/test）按站点

- caltech（n=52641）：train=31585 (60.0%)  validation=10528 (20.0%)  test=10528 (20.0%)
- jpl（n=25132）：train=15079 (60.0%)  validation=5026 (20.0%)  test=5027 (20.0%)

## role×split 交叉（证明时间位置与角色相互独立）

split                  external  stress   test  train  validation
role                                                             
boundary                      0       0    880      0           0
current_only_fallback         0    2591   4147  15079        5026
external_only              1474       0      0      0           0
main                          0    4039  10528  31585       10528

## 规则依据

- split.rule：`站点内按 session connection_time 排序：前 60% train / 中 20% validation / 后 20% test`
- split.rule_version：`e0_full_split_v1`
- split.external_only：`['office001']`
- anomaly_months：`['2019-12', '2020-02', '2020-04', '2020-12']`，anomaly_year_2021：`True`
- connection_time 审计规则：`matched：API connectionTime 可解析且不矛盾 → api_metadata；缺失/无法解析 → first_observation_fallback；可解析但与首条观测矛盾 → 仅登记 anomaly，禁止自动替换`
- field_mode 类别：`['computed_no_pilot', 'computed_pilot', 'current_only', 'measured_no_pilot', 'measured_pilot']`
- role：main=`caltech`，boundary=`jpl.Arroyo_Garage_01`，
  current_only_fallback=`jpl.current_only`，external_only=`['office001']`

金标准对齐：split 由 `assign_split` 按 [connection_time, session_id] mergesort 稳定排序
逐会话生成，与 `tests/test_e0_split.py` 参考实现逐会话对齐（无随机性）。
