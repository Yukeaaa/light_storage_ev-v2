# CORE_SEARCH_R2_C_DATA_GATE：数据可行性与服务代价可辨识性

> 生成时间（UTC）：2026-09-02T14:12:57Z
> 配置：configs/core_search_r2.yaml（rule_version=core_search_r2，冻结）

## 1. 目的

> 只回答：现有观察数据能否构造 online-safe 特征 + 离线 outcome，
> 以及能否定义不依赖不可观测反事实的可信服务代价评价量。不建 policy、不报收益。

## 2. 数据覆盖

| 指标 | 值 |
|---|---|
| matched_sessions | 40644 |
| api_sessions_loaded | 51234 |
| matched_with_userinputs | 36364 |
| userinput_coverage_matched | 0.8946954039956697 |
| matched_with_offline_outcome | 40644 |

## 3. userInputs 字段级覆盖（matched 内）

| 指标 | 值 |
|---|---|
| modifiedAt_coverage | 1.000 |
| kWhRequested_coverage | 1.000 |
| minutesAvailable_coverage | 1.000 |
| requestedDeparture_coverage | 1.000 |
| n_multiple_userinputs | 6080 |

## 4. 服务代价可辨识性（离线标签，绝不入 policy）

| 指标 | 值 |
|---|---|
| requestedDeparture 与实际 disconnect 偏差样本数 | 36364 |
| 偏差绝对值中位（小时） | 1.4104166666666667 |
| 偏差绝对值 p90（小时） | 5.995583333333334 |
| kWhRequested 与 kWhDelivered 样本数 | 36364 |
| delivered/requested 中位 | 0.59525 |

## 5. online/offline 分离（红线）

- online-safe：connection age / current actual / current pilot / actual+ pilot history /
  累计 delivered energy 到 t / userInput 仅当 modifiedAt ≤ t（逐样本 guard）。
- offline-only：disconnectTime / doneChargingTime / final kWhDelivered / future actual / future pilot。
- 禁止：把自然事件中的额外功率下降直接解释为控制造成的服务损失。

## 6. 结论（DATA_GATE）

- **DATA_GATE_GO**：matched 样本与 userInput/modifiedAt 覆盖足以进入 R2-C 正式实验设计。
