# CORE_SEARCH_DECISION_07_ROUND4_CLOSE：Round 4 正式关闭

> 生成时间（UTC）：2026-09-03T14:30:00Z
> 依据：Decision #06、R4-C0、R4-A0b、R4-A1、R4-A1S、R4-A1S-2。
> 纪律：关闭 Round 4；不启动 Round 5；不通过 timestamp shift、metric variant、ML 或子集救援。

## 1. Round 4 总判定

**ROUND 4 CLOSED / NO CORE PATENT GO**

| 方向 | 状态 | 依据 | 后续 |
|---|---|---|---|
| R4-A BESS tracking/capability | **STOP** | RWTH Level B 数据可得，但 timestamp/metric semantics unresolved；A1a STRONG suspended | 不做 corrected A1a，不做 A1b |
| R4-B transformer thermal | **DEFER** | 缺真实 transformer thermal telemetry | 仅真实热遥测到位时重开 |
| R4-C EVSE availability | **CLOSED** | 多站事件存在，但 operational lost-capacity 量级不足 | 不进 R4-C1，不做子集/极端事件救援 |
| R4-D PV/PCS availability | **NOT STARTED** | 缺 adequate real state / limit / alarm data | 不用合成或代理状态启动 |

## 2. R4-C 关闭理由

R4-C0 ACN EVSE infrastructure event audit 发现 396 个事件、49 个站点，说明不是“没有故障”。
但 L1 operational lost-capacity 中位数为 0，达到 >=15% 损失的事件占比约 9.85%，
955 分钟多桩并发也不足以构成系统量级 operational capacity loss。

冻结结论：**R4-C CLOSED**。

禁止动作：
- 不进入 R4-C1。
- 不按子集、月份、站点或极端事件救援。
- 不把 fault existence 说成 system-level capacity mechanism。

## 3. R4-A 关闭理由

R4-A0b 已消除官方源 DATA_PENDING：RWTH Aachen M5BAT 数据集达到 LEVEL B，包含 actual power、
optimized schedule 和 SOC；但缺 temperature/status/power limit/alarm，只能讨论 tracking capability，
不得称 BESS 物理降额。

R4-A1 在 literal supplementary timezone normalization 下产生 A1a STRONG_A1B：active 15min
equivalent shortfall ratio 0.696。但 raw-label diagnostic 只有 0.015，说明该强信号对 timestamp
语义高度敏感。

A1S 证明 S1 supplementary UTC+1/UTC+2 execution pairing 产生伪强信号；S0 raw-label pairing
相对 S1 更接近论文 Test 2 anchors，但只可称 preferred，不能直接升 authoritative。

A1S-2 固定 S0 后复现论文指标：hour 61 和单窗口 49.1 kWh event anchors 通过；energy 有一个
sensitivity variant 落入 238 kWh 的 ±15%；但所有公开文本可还原的 power RMSE/MAD variants
均不能同时复现 13.87 kW / 3.31 kW 的 ±15% gate。

冻结结论：**DATA_SEMANTICS_OR_METRIC_UNRESOLVED / R4-A STOP**。

禁止动作：
- 不用 raw-label 1.5% 继续做 corrected A1a。
- 不回到 S1 69.6% 做 A1b。
- 不通过新的 timestamp shift、metric variant、ML 或 SOC 子集重开 R4-A。
- 不把 Level B 数据解释为 thermal derating、BMS dynamic power limit 或 degradation-induced limit。

## 4. R4-B / R4-D 处置

R4-B transformer thermal 只在取得真实 transformer temperature / thermal limit / loading telemetry
后重开。没有真实热状态数据时，不用负荷代理或仿真温度启动。

R4-D PV/PCS availability 尚未启动。只有取得真实 PCS/PV availability state、limit、alarm 或 curtailment
telemetry，才允许新增数据门；不得用光伏出力缺口反推设备状态。

## 5. 当前项目状态

```text
core-patent status = NO-GO
E7-FAST/M2        = VALID MODULE / narrow defensive package HOLD
R4-A              = STOP
R4-B              = DEFER / real thermal telemetry only
R4-C              = CLOSED
R4-D              = NOT STARTED / adequate real state data required
Round 5           = NOT STARTED
```

下一步只能做问题级复盘：是否值得开启 Round 5，以及 Round 5 是否有新的真实数据支撑的物理机制。
不能在现有 R4-A/R4-C 数据上继续修预测、阈值、shift 或子集。
