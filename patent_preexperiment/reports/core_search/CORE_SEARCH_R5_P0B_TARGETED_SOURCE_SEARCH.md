# CORE_SEARCH_R5_P0B_TARGETED_SOURCE_SEARCH

> 生成时间（UTC）：2026-09-03T15:40:00Z
> 状态：R5-P0b targeted source search；Round 5 仍为 NOT STARTED。
> 纪律：只审 P2 同源 PV/PCS telemetry 与 P1 transformer constraint-side telemetry；不下载大数据，
> 不写算法，不新增 family，不用 split-source 合成 7/7。

## 1. 总判定

**0 个 P1/P2 source 满足单源 7/7。**

```text
P2 same-source PV/PCS telemetry      = NOT FOUND
P1 transformer constraint telemetry  = NOT FOUND
Round 5                              = NOT STARTED
```

R5-P0b 没有改变 R5-P0 的治理结论：P2 仍是 SPLIT-SOURCE HOLD，P1 仍是 DATA-SEED ONLY。

## 2. Launch Rules Rechecked

- P2 只接受同一 asset / same causal chain / same timeline 中同时出现 setpoint/limit/state、actual AC power、irradiance 或 DC input。
- P1 只接受同一 transformer timeline 中同时出现 loading/current、ambient、top-oil/hotspot、protection/status、explicit allowable loading/thermal limit 或真实控制/保护动作。
- 只有 irradiance + actual power 的 PV 数据直接淘汰。
- 只有 dispatch/basepoint + actual 的市场数据直接淘汰。
- 只有 load + temperature 的 transformer 数据只能是 DATA-SEED，不得用 IEEE thermal model 推算 limit 后声称满足 C2。

## 3. P2 Targeted Search Result

| source | visible fields | criteria | verdict | reason |
|---|---|---|---|---|
| NREL/OEDI PVDAQ | system_id、timestamp、metric_id/value；metadata 可含 AC/DC power、irradiance、temperature、inverter metadata | C1/C3/C4/C5/C6/C7 pass, C2 fail | **REJECT** | 无同源 setpoint/curtailment limit/status/alarm |
| OEDI High-Resolution Floating Solar PV | AC power、DC voltage、inverter temperature、irradiance、DC current/voltage 类字段 | C1/C3/C4/C5/C6/C7 pass, C2 fail | **REJECT** | telemetry 强，但无 command/limit/availability/alarm |
| NREL PV inverter experimental datasets | DC/AC voltages/currents、controllable source/load conditions | lab/source characterization | **REJECT** | 非 field PV/PCS availability timeline |
| AEMO NEMWeb dispatch/SCADA | dispatch/SCADA/report families，resource actual/dispatch/availability 语义强 | C1/C2/C4/C5/C6/C7 pass, C3 fail | **REJECT** | 只有 dispatch/actual，缺 irradiance/DC/inverter physical state |
| ERCOT 60-Day SCED | basepoint、SCED/resource data、metered energy、limits/status 类 market fields | C1/C2/C4/C5/C6/C7 pass, C3 fail | **REJECT** | market/resource boundary，缺 PV/PCS physical state |
| Sandia extreme-weather PV / LBNL Solar-to-Grid / OEDI SI DOPF | production/weather/curtailment summaries or simulation | mixed | **REJECT** | 不是同源设备 telemetry 全链，或非真实数据 |

P2 结论：**无 single-source 7/7 launch candidate**。最接近的仍是两类 split-source 证据：
market dispatch feeds 有 command/actual，PV telemetry 有 irradiance/DC/AC，但不得相加形成 7/7。

## 4. P1 Targeted Search Result

| source | visible fields | criteria | verdict | reason |
|---|---|---|---|---|
| Zenodo/DynaLoad SINTEF in-service 40 MVA transformer | voltage/current、ambient、top/bottom oil、HV/LV mid/hot-spot、clamping force/pressure | 5/7 | **DATA-SEED ONLY** | 真实热遥测强，但缺 protection/status、explicit allowable loading/thermal limit、真实控制/保护动作 |
| ETT Electricity Transformer Dataset | load channels + oil temperature | 4/7 | **DATA-SEED ONLY** | forecasting dataset；缺 ambient/hotspot/protection/status/limit/constraint action |
| Zenodo top-oil anomaly detection paper | paper metadata only，未见可审 schema | 1/7 | **REJECT** | 无公开 causal telemetry schema |
| AIKOSH transformer overload aging risk | simulated hourly transformer readings / risk labels | 3/7 | **REJECT** | 非真实 field telemetry，不能满足 C1 |

P1 结论：**无 single-source 7/7 launch candidate**。DynaLoad 仍是最强数据 seed，但 load + temperature
不能替代 constraint-side telemetry。

## 5. Final R5-P0b Status

| family | current status | only allowed action |
|---|---|---|
| P1 Transformer | DATA-SEED ONLY / single-source FAIL | 找 thermal limit / protection / status / constraint execution |
| P2 PV/PCS | SPLIT-SOURCE HOLD / single-source FAIL | 找同源 setpoint/limit/state + actual + irradiance/DC |
| P3 DC charger module | PUBLIC DATA NO-GO | 只有 operator/OEM module telemetry 到位才重评 |
| P4 BESS rack/PCS | PUBLIC DATA NO-GO | 只有 BMS/PCS explicit limits/status 到位才重评 |

## 6. Exit Condition

```text
No P2 single-source 7/7
No P1 single-source 7/7
=> Round 5 remains NOT STARTED
=> Do not lower criteria
```

下一步只能是 targeted data acquisition：优先找 P2 同源 PV/PCS availability telemetry；其次找 P1
transformer thermal limit/protection/status telemetry。拿到 metadata/schema 前，不启动 Round 5。
