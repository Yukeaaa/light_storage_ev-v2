# CORE_SEARCH_R3_C0_GATE：需量窗口机会存在性门

> 生成时间（UTC）：2026-09-03T02:49:34Z
> 配置：configs/core_search_r3c0.yaml（rule_version=core_search_r3c0，冻结）

## 1. 目的

> 真实 1min 负荷里，多少瞬时超限是 false alarm / 可延迟动作。不建控制器。

## 2. 窗口分类（validation 段）

| 指标 | 值 |
|---|---|
| 总窗口数 | 35040 |
| train / val 窗口 | 21024 / 7008 |
| Pcap (train Q90) | 287.0 kW |
| Pcap Q85 / Q95 | 254.5 / 349.6 kW |
| trigger 窗口(max>Pcap) | 1287 |
| false alarm(A) | 381 |
| delayable(B) | 906 |
| unavoidable(C) | 0 |
| opportunity=(A+B)/trigger | 1.000 |

## 3. 门判定

### 判定：**GO**

> opportunity = 1.000

- 机会显著(>0.30) → 可进入 R3-C 系统层 B0/B1/B2/C 预注册。

## 4. 术语

- demand-ceiling scenario，非真实合同需量。
