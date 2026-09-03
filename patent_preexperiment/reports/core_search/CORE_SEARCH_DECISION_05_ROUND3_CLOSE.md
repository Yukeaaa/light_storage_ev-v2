# CORE_SEARCH_DECISION_05 — Round 3 关闭与 Round 4 转向

> **FROZEN DECISION — CORE SEARCH ROUND 3 CLOSED**
>
> 依据：R3-A STOP（`DECISION_03`）、R3-C STOP（`DECISION_04`）。

---

## 1. 核心判定

| 项目 | 判定 |
|---|---|
| R3-A 动态 BESS 备用 | **CLOSED**（C 对 hour-Q95 −5.8%） |
| R3-B 方向分离备用 | **no evidence**（正负误差对称 ≈1.0） |
| R3-C 需量窗口预算控制 | **CLOSED**（C 对 B1/B2 仅 +5.0%） |
| R3-D 变压器热裕量 | **DEFER / REOPEN ONLY WITH REAL THERMAL DATA** |

## 2. Round 3 共同结论（重要，冻结）

> **只要候选机制主要是在已有时间序列上再做一层"更聪明的预测/阈值/时序修正"，强简单 baseline 往往已经吃掉主要结构。**

- R3-A：`hour-Q95` 吃掉小时级结构。
- R3-C：`remaining-budget` 吃掉窗口预算结构。
- R2-C：`reported slack` 吃掉服务风险结构。

→ 下一轮**不再找"再加一个状态变量、再聪明一点"的控制器**。

## 3. R3-D 处置

```text
DEFER / REOPEN ONLY WITH REAL THERMAL DATA

原因：只有真实 load，缺真实 top-oil / hotspot / transformer-specific thermal parameters。
大部分效果会来自 IEEE/IEC 热模型假设而非现场观测 → 数字漂亮但证据弱，
且动态载流/热裕量本身已有大量成熟方案。
禁止：不靠标准热模型仿真出的大数字把 Round 3 救活。
```

## 4. 下一步

> **CORE SEARCH ROUND 4 — DATA-FIRST PHYSICAL MECHANISM SEARCH**
>
> 先找"真实物理边界变化"，再找控制算法。优先研究设备名义能力 vs 实际可用能力随状态的变化。
> 首要任务：寻找并审计公开可获得的真实 BESS 运行遥测（≥ actual power + SOC，最好 command + temperature/limit）。
