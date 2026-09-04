# CORE_SEARCH_R5_DATA_ACQUISITION_SPEC

> 生成时间（UTC）：2026-09-03T16:05:00Z
> 状态：data acquisition specification only；Round 5 仍为 NOT STARTED。
> 纪律：这是数据合同，不是实验计划；不写算法，不启动 controller，不承诺系统收益。

## 1. Scope

R5-P0/P0b 已确认公开数据源不足以启动 Round 5。下一步从 public-source search 转为 targeted data acquisition：
向内部场站、合作方、OEM 或科研机构索取同源、同设备链、同时间线的数据。

优先级只保留两类：

1. P2 PV inverter / PCS available-power boundary。
2. P1 transformer dynamic thermal capacity。

P3 DC charger module 与 P4 BESS rack/PCS 暂不主动推进；只有 operator/OEM 级 telemetry 到位才重评。

## 2. P2 PV/PCS Data Contract

P2 只接受同一 asset / same timeline 的数据链。最小字段：

| field group | required fields | purpose |
|---|---|---|
| identity/time | timestamp + timezone, plant_id, inverter_id or PCS_id | 因果对齐与设备边界 |
| requirement/limit | active_power_setpoint, or curtailment_command, or explicit_active_power_limit | 外部要求或显式约束端 |
| execution | actual_ac_power | 实际执行端 |
| physical availability | irradiance, or dc_power, or dc_voltage + dc_current | DC/PV 可用输入端 |
| state/status | inverter/PCS status, availability state, alarm or derating reason | 设备状态端 |
| metadata | rated_power, configuration metadata | 固定额定值 baseline |

Preferred extra fields：

- reactive_power_setpoint
- dc_bus_voltage
- module/inverter temperature
- grid voltage/frequency
- controller mode

最低因果链必须闭合：

```text
external requirement / explicit limit
-> current physical availability state
-> device status / derating reason
-> actual AC execution
```

若只有 irradiance + actual power，直接淘汰。若只有 dispatch/basepoint + actual，也直接淘汰。

## 3. P1 Transformer Data Contract

P1 只接受同一 transformer / same timeline 的数据链。最小字段：

| field group | required fields | purpose |
|---|---|---|
| identity/time | timestamp + timezone, transformer_id | 因果对齐与设备边界 |
| loading | HV/LV current or loading | 实际负载端 |
| thermal state | ambient temperature, top-oil temperature, hot-spot temperature | 真实热状态 |
| equipment state | protection/status, fan/pump/cooling stage, alarm | 设备运行状态 |
| constraint/action | explicit allowable loading, or dynamic thermal limit, or protection trip/curtailment threshold, or real overload/control action | 约束或动作端 |

若只有 load + ambient + top-oil + hotspot，它仍然只是 DynaLoad 类型 thermal monitoring dataset，不能触发 Round 5。
不得用 IEEE thermal model 或经验公式推算一个 limit 后声称满足 constraint-side evidence。

## 4. Intake Gate For Any New Data

收到任何数据后，统一按以下顺序审计：

1. Schema gate：字段是否满足对应 P1/P2 数据合同。
2. Semantics gate：timestamp、timezone、单位、符号、设备边界、setpoint/limit 生效语义是否可独立复核。
3. Event-existence gate：真实 constraint/state variation 是否发生。
4. Effect gate：constraint/state variation 是否与 actual available capability 或 system-scale consequence 发生可观测差异。
5. R5 seven-criteria gate：同一数据源/设备链/时间线是否满足 7/7。

只有同时满足：

```text
schema 7/7
+ independently verified semantics
+ real constraint/state variation exists
+ preliminary system-scale effect exists
```

才允许把 Round 5 从 NOT STARTED 改为 STARTED。

## 5. Non-Negotiable Rules

- 不同数据源的 PASS 不得相加形成 7/7。
- 不用代理状态、仿真温度、估算 limit、历史统计量或 ML 填补缺失字段。
- 不把 market/resource availability 自动等同于 inverter/PCS physical availability。
- 不把 thermal monitoring 自动等同于 dynamic thermal limit。
- 不在数据语义复核前写算法或 controller。

## 6. Practical Acquisition Targets

优先联系/查找：

- 内部光伏场站 / PCS SCADA。
- OEM inverter logs。
- 集控平台 curtailment / AGC / active-power-limit logs。
- 变压器在线监测系统。
- 保护装置 / 冷却控制 / DTR 或 overload-limit logs。

当前瓶颈不是算法，也不是候选概念，而是缺少真实、同源、可因果对齐的设备能力约束数据链。
