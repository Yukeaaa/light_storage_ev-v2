# CORE_SEARCH_DECISION_01 — EV 柔性规模与响应动态路线处置

> **Decision #1 — EV 柔性规模与响应动态路线处置**
>
> 状态：**FROZEN DECISION**（CORE-SEARCH 第一份正式路线处置记录）
>
> 依据：`reports/core_search/CORE_P0_A_EV_RESPONSE.md`（GO）+ `reports/core_search/CORE_P0_B_EV_FLEX_SCALE.md`（NO-GO）
> 冻结配置：`configs/core_search_v1.yaml`（rule_version=core_search_v1，2026-08-14 冻结）
> 目的：决定 CORE-A / CORE-B / CORE-C 是否进入系统级开发，并冻结"关闭条件"与"重开条件"。
>
> **本文件地位高于 P0-A/P0-B 两份门报告**：它定义哪些结果有效、哪些方向因此关闭、
> 什么条件下允许重新打开，防止后续因为 P0-A 的动态现象"很有意思"而回头继续烧时间。

---

## 1. 核心判定（冻结）

| 项目 | 判定 | 后续处置 |
|---|---|---|
| P0-A EV 响应时间谱 | **GO** | 保留为真实响应机制资产 |
| P0-B EV 群柔性规模 | **NO-GO** | 关闭当前 ACN 域下的规模替代路线 |
| CORE-A BESS-EV 快慢接力 | **NO-GO as CORE** | 仅保留从属/实施机制，不作核心候选 |
| CORE-B EV 柔性降低最小 BESS P/E | **STOP** | 不建 system bench |
| CORE-C dynamic reserve + EV flexibility | **STOP** | 不继续 |
| ACN → 大规模 EV/BESS 替代 | **CLOSED** | 禁止通过简单倍乘 ACN 规模"救活" |
| P0-A 下调动态 | **RETAIN** | 可供未来其他主方向复用 |

---

## 2. 两个 P0 回答的是不同问题（防误判）

P0-A 的 GO **不能覆盖** P0-B 的 NO-GO。二者分别回答：

```text
P0-A: 有没有真实动态？        → YES
P0-B: 这个真实动态的功率量级
      够不够改变园区系统？     → NO
```

最容易误判成"下调动态这么明显，快慢接力值得继续"。正式冻结为：

```text
真实响应动态存在（P0-A GO）
        ↓
但真实池规模下，可可靠调用的功率不足（P0-B NO-GO）
        ↓
无法预期形成 ≥15–20% 的 BESS/PCC 系统级核心收益
        ↓
因此不进入系统开发
```

这是好的 **No-Go**，不是失败。

---

## 3. P0-A：下调动态为 RETAIN 的"真实响应机制资产"

下调 response_fraction（binding down，train+val，median）：

```text
1 min ≈ 1.145
3 min ≈ 0.648
5 min ≈ 0.585
```

现象不是普通的"EV 响应慢"，而是：

> **桩侧限制下降后，车辆实际功率先出现较强快速下降，随后部分回升，
> 5 分钟稳定在约 60% 的有效下降水平。**

即真实响应具有：

```text
快速瞬态 → 部分恢复 → 较低稳态削减
```

而不是：

```text
0 → 慢慢到 100%
```

该现象对任何后续研究 EV 控制动态的方向都有价值，**作为 REAL RESPONSE ASSET 保留**，
不随 CORE-A 一起关闭。

---

## 4. 上调侧：正式关闭"EV 吸收 PV 富余"的强假设

上调 response_fraction（binding up，train+val，median）：

```text
1 min = 0.237
3 min = 0.010
5 min = 0.004
```

在当前 ACN 场景下，**看到 pilot 有 headroom，不意味着车辆会吸收额外功率**（与 E7-FAST D2 一致）。

正式冻结：

> 在当前数据域内，不把"上调 EV"作为能够承担显著园区功率平衡任务的核心柔性资源。
> 凡提出"PV 富余 → EV 多吃 100kW"，第一问必须是"真实数据支持吗？"——当前答案：不支持。

---

## 5. P0-B：量纲天花板（分池，不可加总）

| site | EV 峰值 kW | 可靠下调柔性峰值 kW | 中位 kW |
|---|---|---|---|
| jpl | 148.9 | 87.1 | 8.8 |
| caltech | 107.4 | 62.9 | 3.9 |
| office001 | 40.3 | 23.6 | 2.7 |

- 可靠下调柔性峰值：**87.1 kW**（< 100 kW BESS 下界）
- 高并发时段（>20 活动会话）p95：**~80 kW**
- 可靠下调中位：**~8.8 kW**

结论：当前 ACN 数据域里值得相信的是

> **偶尔可以形成几十 kW 级下调资源，但不是稳定的 100–200 kW 级园区资源。**

因此 CORE-B 不是"暂时没跑"，而是：

> **在现有真实数据尺度下，缺乏启动 BESS sizing 主线的量纲依据。**

---

## 6. EMSx 不是"更大 EV 池"（纠正）

EMSx 解决的是园区 **load/PV/forecast 背景**，**不提供更大的真实 EV 响应池**。

```text
ACN 柔性规模不足 → 换 EMSx   【不能解决 P0-B】
```

因为即便园区 load 变成 2 MW，而 EV 真实可靠柔性仍是 80 kW，比例反而更小。

EMSx 仅在已有一个值得进入系统层的 EV/控制机制之后，用于真实工业 load/PV 系统传播验证。
**现在不必为了 A/B/C 下载 EMSx、搭 system bench。**

---

## 7. 重开 EV↔BESS 规模方向的 Reopen Gate

要重开，需要的是**新 EV 数据**（不是新园区数据），且不能只是"会话数量更多"。
必须**同时满足**以下全部条件：

```text
EV↔BESS SCALE DIRECTION REOPEN ONLY IF:
```

1. **同一场站/园区**（co-located pool；Caltech+JPL+Office001 不得相加，因非同一园区同时可调资源）；
2. **actual + controllable limit/setpoint 可用**（charger allowed / pilot / setpoint + actual power +
   timestamp + session/station；只给 arrival/departure/kWh 不够，P0-A 核心证据是真实控制响应）；
3. **至少 1–3 个月连续时序**；
4. **聚合 EV peak 显著高于当前 ACN**；
5. **初步可靠下调柔性量级**：
   - 峰值 ≥ 150 kW，且高并发期 p95 ≥ 120–150 kW；或
   - 柔性 / 园区目标 BESS 功率 ≥ 0.5；
6. **上述量级必须来自真实池，不得通过简单倍乘 ACN 获得。**

量纲定义沿用 `core_search_v1.yaml` 的 100/200 kW BESS 比较基线，不另造阈值。
核心：**必须先过新数据量纲门，才允许重新建 system bench。**

---

## 8. 当前下一步：不救 CORE-A，不单包 P0-A，进入 Round 2 问题重筛

### 不建议 1
为救 CORE-A 去找"大一点 ACN"——这是"先认定方向再找数据"，风险高。

### 不建议 2
把 P0-A 单独包装成核心专利——"EV 功率下降→1min 过冲→3/5min 回落"只是响应特性，
还缺"利用该特性后系统有何明显收益"，当前最多是 supporting/从属机制。

### 正式转向
A/B/C 都隐含同一假设："EV 柔性必须有足够大 kW 才能替代 BESS"，P0-B 已否掉。

**CORE-SEARCH Round 2** 应寻找：

> **即使 EV 功率不是特别大，它的信息、动态或状态变化能否改变另一个重要系统决策？**

候选的"低成本信息/动态收益"形态（不依赖大 kW）：一个状态信号、一个响应趋势、
一个预测误差修正、一个局部约束、一个控制优先级变化，进而影响 BESS 何时动作、
哪些桩先调、变压器是否提前保护、demand window 是否干预、某控制动作是否持续。

---

## 9. Decision #1 正式结论

> **Decision #1 结论：**
>
> P0-A 证明 ACN 真实 EV 下调响应具有可重复的时间动态与异质性（GO），但 P0-B 表明在现有
> 单场站数据域下，可靠聚合 EV 柔性不足以达到 100–200 kW BESS 同量级（NO-GO），因此停止以
> "EV 功率替代 BESS"为核心收益来源的 CORE-A/B/C 三条路线。
>
> P0-A 作为真实响应机制资产保留，可在后续其他系统控制方向中复用。
>
> 下一阶段不立即搭建 load/PV+BESS 系统 benchmark，也不通过缩放 ACN EV 池救活当前路线；
> 转入 **CORE-SEARCH Round 2：寻找不依赖大规模 EV 功率替代、但可利用现有真实响应/会话/
> 信息状态产生明显系统效果的新问题。**
>
> 若未来获得同一真实园区的大规模 EV 控制响应数据，仅在重新通过 EV flexibility scale gate
> 后允许重启 EV↔BESS sizing/handoff 路线。

---

## 10. 决策状态快照（冻结）

```text
CORE SEARCH ROUND 1
===========================

P0-A RESPONSE DYNAMICS
  GO / RETAIN

P0-B FLEXIBILITY SCALE
  NO-GO

CORE-A HANDOFF
  NO-GO AS CORE
  RETAIN P0-A MECHANISM ONLY

CORE-B BESS SIZING
  STOP

CORE-C DYNAMIC RESERVE
  STOP

SYSTEM BENCH FOR A/B/C
  DO NOT BUILD

EMSx FOR A/B/C
  NOT REQUIRED

ACN SCALING RESCUE
  FORBIDDEN

NEW LARGE EV DATA
  OPTIONAL REOPEN PATH ONLY
  (see §7 Reopen Gate)

NEXT:
  CORE SEARCH ROUND 2
```

---

## 附：证据锚点（本文件引用的冻结数字来源）

| 数字 | 值 | 来源 |
|---|---|---|
| P0-A binding up/down 事件（train+val） | 11698 / 4699 | CORE_P0_A_EV_RESPONSE.md §2 |
| P0-A down 1/3/5min median | 1.145 / 0.648 / 0.585 | 同上 §3 |
| P0-A up 1/3/5min median | 0.237 / 0.010 / 0.004 | 同上 §3 |
| P0-A 异质性 IQR / repeatability corr | 0.202 / 0.297 | 同上 §4/§5 |
| P0-B 分池 EV 峰值 | jpl 148.9 / caltech 107.4 / office001 40.3 kW | CORE_P0_B_EV_FLEX_SCALE.md §3 |
| P0-B 可靠下调柔性峰值 / 中位 | 87.1 / 8.8 kW | 同上 §3/§6 |
| P0-B 高并发(>20) p95 | ~80 kW | 同上 §5 |
| BESS 量级比较 | 100–200 kW | core_search_v1.yaml p0_b.gate |
