# CORE_SEARCH_R5_P0_DATA_SCOUTING：pre-launch data feasibility search

> 生成时间（UTC）：2026-09-03T15:10:00Z
> 状态：R5-P0 PRE-LAUNCH DATA SCOUTING；Round 5 仍为 NOT STARTED。
> 纪律：只审公开 metadata/schema/论文语义；不下载大数据，不写算法，不同时开发 P1/P2/P3/P4。

## 1. 总判定

**0 个 problem family 满足 Round 5 七条启动条件。**

```text
Round 5 = NOT STARTED
next action = targeted data acquisition / metadata audit only
```

P1 transformer thermal 与 P2 PV/PCS 有可继续做数据门的近邻候选；P3/P4 在公开数据层面不足。

## 2. Family Screen

| family | best public lead | criteria pass | verdict | reason |
|---|---|---:|---|---|
| P1 Transformer dynamic thermal capacity | Zenodo/DynaLoad in-service 40 MVA transformer | 5/7 | **DATA-SEED ONLY** | 有 current、ambient、top/bottom oil、hotspot；缺 explicit protection/status/thermal-limit 与执行约束端 |
| P2 PV inverter / PCS available-power boundary | AEMO/ERCOT dispatch feeds + PVDAQ/Solar Data Prize | 5/7 split-source | **SPLIT-SOURCE HOLD** | market feeds 有 dispatch/limit/actual，PVDAQ 有 irradiance/DC/AC；未发现同一数据源含 setpoint/limit/state/actual/irradiance 全链 |
| P3 DC charger power-module available capacity | UCLA/OCPP、INL/EV Project、EV WATTS 等 | 3/7 | **PUBLIC DATA NO-GO** | 公开源多为 session/OCPP/status，缺模块级 temperature/fault/derating/limit 与 commanded/actual 同链 |
| P4 BESS rack/PCS protection-limited envelope | Mafate microgrid、UCSD、Pecan Street | 4/7 | **PUBLIC DATA NO-GO** | 有真实 battery/microgrid actual 或 physical state 近邻，但缺 command/setpoint、SOC、explicit limit/alarm/status 全链 |

详表见 `results/raw/core_search/r5_p0/r5_p0_family_screen.csv`。

## 3. Candidate Notes

### P1 Transformer Dynamic Thermal Capacity

最强公开线索是 Zenodo/DynaLoad 的 in-service 40 MVA transformer monitoring 数据，字段线索包含
voltage/current、ambient、top-oil、bottom-oil、HV/LV mid-spot、HV/LV hotspot 等。

它满足真实设备、物理状态、语义可复核、固定额定值 baseline 可挑战等条件，但没有看到 explicit
protection/status/thermal-limit 或控制/约束执行端。因此它只能作为 P0 seed，不能直接启动 Round 5。

### P2 PV Inverter / PCS Available-Power Boundary

没有发现单一公开源同时包含 actual AC power、setpoint/curtailment command/limit、irradiance/DC input、
inverter/PCS status/alarm/availability。

AEMO/ERCOT/Elexon 类市场源对 dispatch/basepoint/availability/actual 语义强，但缺设备物理状态。
PVDAQ/Solar Data Prize 类 PV telemetry 源对 irradiance/DC/AC 和设备 metadata 较强，但公开 schema
未保证 curtailment/setpoint/status/alarm。

P2 仍是下一批最优先的数据搜索方向，但必须先找到同源全链字段，不能用两类数据拼接后宣称 7/7。

### P3 DC Charger Module Available Capacity

公开源主要是 OCPP/session/connector status/security traces，不含 DC fast charger power module 的
module temperature、active module count、fault/derating、explicit power limit、commanded power 与 actual
DC output 同链。P3 需要 operator/OEM telemetry；公开数据不足以启动。

### P4 BESS Rack/PCS Protection-Limited Envelope

UCSD、Mafate、Pecan Street 等能提供真实 battery/microgrid actual 或部分 physical state，但没有公开
command/setpoint、rack/PCS/BMS status、charge/discharge power limit、alarm/derate/protection reason 同链。
由于 R4-A 已证明 schedule semantics 风险很高，P4 不能在缺 explicit limit/status 时继续。

## 4. Criteria Outcomes

Round 5 七条启动条件逐 family 结果：

| family | C1 real data | C2 requirement+actual | C3 physical state | C4 system magnitude | C5 baseline | C6 semantics | C7 non-isomorphic | pass |
|---|---|---|---|---|---|---|---|---:|
| P1 | PASS | PARTIAL | PASS | PARTIAL | PASS | PASS | PASS | 5/7 |
| P2 | PASS | PASS | PARTIAL | PASS | PASS | PASS | PASS | 5/7 split-source |
| P3 | PASS | FAIL | FAIL | PARTIAL | PARTIAL | PASS | PASS | 3/7 |
| P4 | PASS | FAIL | PARTIAL | PARTIAL | PASS | PARTIAL | PASS | 4/7 |

## 5. Freeze Rules

- 0 个 family 满足 7/7，因此 Round 5 继续 NOT STARTED。
- P1 只有在补到真实 thermal limit/protection/status 或等价约束端后，才可进入数据门。
- P2 只有在同一数据源内看到 setpoint/limit/state/actual/irradiance 或 DC input 全链后，才可进入数据门。
- P3 只有拿到 DC charger module-level operator/OEM telemetry 后，才可重评。
- P4 只有拿到 BESS rack/PCS/BMS command、actual、SOC、temperature、explicit limit/alarm/status 后，才可重评。
- 不用 split-source 拼接、代理状态、仿真温度、历史统计量或 ML 代替缺失字段。

## 6. Next Action

下一步不是 Round 5 实验，而是 targeted data acquisition：优先继续查 P2 同源 PV/PCS setpoint/limit/state
公开或半公开数据，其次查 P1 transformer thermal limit/status telemetry。拿到 metadata/schema 后重新按七条
启动条件判定，仍只允许一个 family 进入正式 Round 5。
