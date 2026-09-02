# CORE_SEARCH_R2_C1_GATE：服务目标有效性与决策机会门

> 生成时间（UTC）：2026-09-02T14:49:48Z
> 配置：configs/core_search_r2c1.yaml（rule_version=core_search_r2c1，冻结）

## 1. 目的

> 只回答：userInput 是否可信作为服务目标、哪些量是服务完成度/proxy、
> 是否存在足够多服务选择决策机会。不建 Candidate、不报收益。

## 2. 服务目标有效性

| 指标 | 值 |
|---|---|
| matched 会话数 | 40644 |
| 有 userInput 的会话数 | 36364 |
| userInput 覆盖 | 0.895 |
| 请求电量完成比(delivered/requested) 中位 | 0.595 |
| 完成比 IQR | 0.394 |
| 完成比 p10 / p90 | 0.239 / 0.972 |
| 完成比 <0.5 占比 | 0.372 |
| 物理可实现占比(kWhRequested≤7.2kW×时长×1.1) | 0.826 |
| 多 userInput 会话数 | 6080 |

## 3. departure 偏差（requestedDeparture 是 proxy 而非硬目标）

| 指标 | 值 |
|---|---|
| disconnect − requestedDeparture 中位（小时） | 0.52 |
| 偏差绝对值中位（小时） | 1.41 |
| 偏差绝对值 p90（小时） | 6.00 |
| 会话时长中位（小时） | 7.49 |
| 偏差<时长/2（有信息量） | True |

## 4. 决策机会（小时 bin × 并发会话 × kWhRequested 分歧）

- 决策机会 bin 数（并发≥2 且 kWhRequested IQR≥5kWh）：10730

## 5. 门判定

### 判定：**GO**

- validity_go: True
- opportunity_go: True

- userInput 可信度与决策机会均满足 → 可进入 R2-C2 五臂正式 allocation experiment。

## 6. 术语纪律

- delivered/requested 仅称"请求电量完成比"，不得称"服务损失"。
- requestedDeparture 是 proxy（偏差中位明显），不得作为硬服务目标。
- 不把自然事件额外功率下降归因为控制造成的服务损失。
