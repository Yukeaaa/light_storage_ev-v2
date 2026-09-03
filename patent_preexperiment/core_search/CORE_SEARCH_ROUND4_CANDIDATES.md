# CORE_SEARCH_ROUND4_CANDIDATES — DATA-FIRST PHYSICAL MECHANISM SEARCH

> **本文件只冻结"问题级"候选 + 数据可行性结论，不冻结算法。**
> 依据：`CORE_SEARCH_DECISION_05_ROUND3_CLOSE.md`（Round 3 关闭）
> 转向：不再从 forecast/load 序列里挖更多统计结构，而先找"真实物理边界变化"。

## 共同机制链（Round 4 搜索范式）

```text
设备名义能力
    ↓
实际可用能力随状态变化（降额/故障/限发）
    ↓
传统 EMS 仍按固定额定值决策
    ↓
产生真实约束错误 / 保守浪费
    ↓
在线估计真实可用边界
    ↓
改变系统控制决策
```

---

## 候选矩阵

| 搜索族 | 需要的新数据 | 当前处置 |
|---|---|---|
| **R4-A BESS 真实能力边界/降额** | real BESS power + SOC + setpoint + temperature/alarms | **第一优先** |
| **R4-B 变压器动态热容量** | load + ambient + top-oil/hotspot | DEFER（有真实热数据才重开 R3-D） |
| **R4-C EVSE/充电设施降额与故障** | pilot/actual/state/故障事件 | **ACN 已有信号，可立即审计** |
| **R4-D PV/PCS 真实可用功率与限发** | inverter actual + setpoint/limit + irradiance | 有数据才启动 |

---

## R4-A：BESS 真实能力边界（第一优先）

- **问题**：同样 SOC 下，BESS 实际可交付功率是否有显著、可重复的动态降额？
  固定 Pmax 假设造成多大控制误差？
- **量纲判断**：实际能力变化 2–3% → 死；经常 20–40% 且在线状态可解释 → 有系统级量纲。
- **数据现状（本轮审计）**：
  - 本地 UCSD `BatteryStorage.csv` / `TradeStreetBattery.csv`：**仅 `DateTime + RealPower`**，
    无 SOC / 温度 / command / limit → **不足以研究降额**。
  - 公开候选：**Iontech（Aachen 混合 BESS 现场试验）**——秒级 power flows + SOC（unit/system 级）
    + 电网交互 + 对应优化调度计划。**下一步下载并审计其字段。**
  - 次选：URI-PBEST（PV-BESS SOC 估计，Zenodo 19487496）、Sandia ESS R&D 仓库、IEEE DataPort BESS。

## R4-B：变压器动态热容量

- **处置**：`DEFER / REOPEN ONLY WITH REAL THERMAL DATA`。无 top-oil/hotspot 时只做标准热模型仿真，
  数字漂亮但证据弱，且动态载流/热裕量已有大量成熟方案。

## R4-C：EVSE 降额与故障（ACN 已有信号，可立即审计）

- **问题**：充电桩真实可用容量是否随故障/降额状态变化？EMS 按固定额定值分配是否产生约束错误？
- **数据现状（本轮审计，caltech 全量 session_response_1min 的 state_norm）**：

  | state | 分钟行数 | session 数 |
  |---|---|---|
  | DISABLED CHARGER | 7286 | 267 |
  | DISABLED PILOT VIOLATION | 4540 | 33 |
  | PILOT VIOLATION | 685 | 7 |

- **关键**：这些是**基础设施侧**的容量变化（充电桩自禁用/故障/pilot 违规），不是 Round 2 的
  "车辆愿不愿响应"问题。这是真实物理边界变化。
- **下一步**：先做存在性审计（这些事件是否可在线观测、是否影响实际交付、覆盖/切分如何），
  不直接开发算法。

## R4-D：PV/PCS 真实可用功率与限发

- **处置**：有 inverter actual + setpoint/limit + irradiance 数据才启动，当前不启动。

---

## 优先级排序（本轮）

```text
1. R4-A：下载并审计 Iontech Aachen BESS 遥测（是否含 SOC + command + 温度）
2. R4-C：ACN EVSE derating/fault 事件存在性审计（零新增数据，可立即做）
3. R4-B / R4-D：无真实物理状态数据 → 不启动
```

## 首要任务

> 寻找并审计可公开获得的真实 BESS 运行遥测，要求至少 actual power + SOC，
> 最好再有 command/setpoint + temperature/limit。
