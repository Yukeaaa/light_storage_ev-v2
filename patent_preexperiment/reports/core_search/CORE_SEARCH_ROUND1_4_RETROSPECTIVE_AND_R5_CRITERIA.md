# CORE_SEARCH_ROUND1_4_RETROSPECTIVE_AND_R5_CRITERIA

> 生成时间（UTC）：2026-09-03T14:45:00Z
> 依据：Decision #01-#07、R1/R2/R3/R4 gates、E7-FAST corrective audit。
> 目的：不是重写历史结论，而是冻结 Round 5 是否允许启动的 problem-level 准入规则。

## 1. 当前总状态

```text
CORE PATENT = NO-GO
Round 1     = CLOSED
Round 2     = CLOSED
Round 3     = CLOSED
Round 4     = CLOSED
Round 5     = NOT STARTED
```

E7-FAST/M2 仍是 VALID MODULE / narrow defensive package HOLD，不是系统级核心专利 GO。

## 2. Round 1-4 搜索规律

1. 依赖同一时间序列上更聪明的预测、阈值或近期状态修正的候选，容易被强简单 baseline 吸收。
R2-C、R3-A、R3-C 均显示：若没有新的真实设备状态维度，复杂化很难转化为核心控制价值。

2. 真实设备状态变化必须先证明系统量纲。R4-C 有 EVSE infrastructure faults，但多数事件没有
系统量级 operational capacity loss，因此 fault existence 不能直接升级为 EMS 发明问题。

3. 外部数据必须先做语义复现，再做算法实验。R4-A 显示：actual power + schedule + SOC 字段齐全
仍不足够；timestamp/execution semantics 一旦误读，tracking shortfall 可从约 1.5% 放大到约 69.6%。

## 3. 候选空间矩阵

| 候选类型 | 已知问题 | Round 5 是否允许 |
|---|---|---|
| EV 响应预测 / 用户信息 / 优先级 | R1/R2 已充分失败或弱化；强简单 baseline 吃掉主要结构 | **禁止重开** |
| 动态 BESS reserve / 时间窗优化 | R3 已被强简单 baseline 吸收，系统收益不足 | **禁止轻微变体** |
| EVSE fault-aware accounting | R4-C 事件存在但 operational magnitude 不足 | **禁止 ACN 子集救援** |
| BESS schedule tracking | R4-A timestamp/metric semantics unresolved | **禁止继续 RWTH metric/shift 救援** |
| transformer thermal headroom | 缺真实 transformer thermal telemetry | **允许，但先拿数据** |
| PV/PCS availability / curtailment | 缺真实 limit/setpoint/state/curtailment 数据 | **允许，但先拿数据** |
| 新设备物理约束 | 尚未系统搜索；必须有真实状态与执行两端 | **优先** |

## 4. Round 5 启动条件

Round 5 candidate 只有同时满足以下条件才允许立项：

1. 有真实设备或场站数据，不靠纯仿真发现问题。
2. 能看到“要求/约束”与“实际执行/实际能力”至少两端。
3. 存在明确物理或设备状态变量，而非只有历史统计量。
4. 初步 effect 有系统量纲，而不是单设备小偏差。
5. 有一个明显的固定额定值、固定约束或简单 EMS baseline 可被挑战。
6. 数据语义能独立复核，至少能用论文、metadata、日志或另一字段族复现关键 anchor。
7. 不与 Round 1-4 已关闭机制同构。

任一条件不满足，Round 5 不启动；不得先做算法再回补数据语义。

## 5. 优先问题族

Round 5 若启动，只优先看两类问题族：

| 优先级 | 问题族 | 最小数据要求 |
|---|---|---|
| A | 有真实热 / 电 / 保护遥测的设备动态容量边界 | transformer、PCS、BESS rack 或 DC charger module 的 loading、temperature、limit/status/alarm 与实际功率 |
| B | 有 actual setpoint / limit / curtailment state 的功率电子设备可用能力 | PV inverter、PCS 或 DC charging module 的 setpoint、availability/limit state、actual output 与 curtailment/alarm |

这两类仍必须先过数据门；没有真实状态数据时不得用负荷、PV 出力缺口或仿真温度做代理。

## 6. 禁止重开清单

- 不重开 EV 响应预测、用户行为、优先级排序或近期统计阈值方向。
- 不重开 R4-A RWTH timestamp shift、metric variant、SOC 子集或 ML rescue。
- 不重开 R4-C ACN EVSE 子集、月份、站点或极端故障救援。
- 不用纯仿真、合成状态、经验温度、负荷代理或后验筛选证明新物理机制。

## 7. 下一步

先做问题级复盘会：按第 4 节七条准入条件筛 3-5 个 Round 5 problem families，再只做数据可得性搜索。
在数据源过门前，不写算法、不做 controller、不产出系统收益。
