可以。下一阶段不要再以“把某个算法做深”为主线，而应正式切换成：

> # **CORE-PATENT SEARCH：系统级核心专利筛选阶段**
>
> 目标不是证明某个 EV 子模块有效，而是在现有真实 EV 数据基础上，快速找到一个能够带来**明显系统收益**、且能够形成完整控制机制的方向。
>
> 下一阶段的核心原则只有三个：
> **真实数据先行、系统效果先行、强简单 baseline 先行。**

我建议把下一阶段设计成 **“数据补齐 → 两道零成本数据门 → 统一系统试验台 → 三方向并行 P0 → 选一条做深 → 专利定义”** 六步，而不是直接选一个热点一路做下去。

------

# 一、阶段总目标

最终不是输出论文模型，而是回答：

> **在工商业园区光储充系统中，哪一种新的 EV/BESS/负荷/光伏协调机制，能够在真实 EV 行为和真实园区能源背景下，稳定地产生足够大的系统级技术效果，并值得作为核心专利申请？**

“足够大”建议从现在开始冻结成统一标准：

| 系统效果 | 判断                       |
| -------- | -------------------------- |
| <5%      | **DEAD**                   |
| 5–10%    | 工程小改进，不作为核心专利 |
| 10–15%   | 观察                       |
| 15–20%   | 值得深入                   |
| **>20%** | **强核心候选**             |

这里必须是**系统 KPI**，不是预测误差。

优先看：

- 最小 BESS 功率需求；
- 最小 BESS 能量需求；
- BESS 实际吞吐；
- BESS 峰值功率；
- PCC/变压器越限；
- EV 被削减能量；
- EV 最终交付；
- PV 弃光；
- 可承载 EV 渗透率；
- 可用 BESS 备用容量。

------

# 二、先冻结旧项目，不再救 E7-FAST

当前 E7-FAST 的处理建议正式写死：

```text
E7-FAST / M2
--------------------------
D2 vehicle-side mechanism     VALID
core-patent status            NO-GO
D3 system value               CLOSED
D3 recovery                   CLOSED
24h rescue                    CLOSED
Q95 retuning                  CLOSED
ML rescue                     CLOSED
```

但 M2 不删除。

它以后作为：

1. 新系统实验的 **EV flexibility baseline**；
2. 信息不足时的 fallback；
3. 证明“被动历史边界优化未必产生系统收益”的反例；
4. 后续新核心专利的可能从属模块。

旧 `phase3_p2/`、`phase3_p2_1/`、`e7_fast/` 全部冻结。

新阶段单独建：

```text
patent_preexperiment/
├── core_search/
│   ├── data/
│   ├── ev_response/
│   ├── ev_flexibility/
│   ├── system_bench/
│   ├── directions/
│   │   ├── core_a_handoff/
│   │   ├── core_b_bess_sizing/
│   │   └── core_c_dynamic_reserve/
│   ├── metrics/
│   └── reports/
└── configs/
    └── core_search_v1.yaml
```

这样不会再污染冻结证据。

------

# 三、Phase 0：先建立新的数据资产注册表

第一件事不是写控制器。

建立：

```text
reports/core_search/CORE_DATASET_REGISTRY.md
```

至少分五类：

### REAL_CORE

已有：

- ACN-Data-Static；
- ACN API metadata。

### DERIVED_REAL

已有：

- 1min session table；
- 5min pool；
- 15min pool；
- positive pilot-step library；
- negative pilot-step library；
- M2 train/validation/test events；
- session/station/month split。

### REAL_EXTERNAL

下一步补：

- EMSx 工业站点 load/PV/forecast；
- 1min building load+PV；
- 后续若方便再加第二套建筑数据作外部复现。

### ENGINEERING

- BESS 功率/容量/SOC/效率模型；
- PCC；
- transformer nominal constraints。

### SYNTHETIC

只允许用于：

- stress test；
- penetration scaling；
- 参数敏感性。

不允许当核心真实证据。

------

# 四、Phase 1：数据补齐

这一阶段建议同时做两件事。

## 1. EMSx

先别把 70 个站全部整合。

先做 6–10 个代表站：

```text
低负荷
中负荷
高负荷

低PV
中PV
高PV

工作日模式不同
```

先完成：

```text
emsx_site_registry.csv
emsx_load_pv_15min.parquet
emsx_forecast_errors.parquet
EMSX_DATA_AUDIT.md
```

检查：

- 时间跨度；
- 缺失率；
- 时间分辨率；
- load/PV 单位；
- forecast horizon；
- load 和 PV 的定义；
- 是否有异常连续零值；
- 不同站功率尺度。

### 第一阶段不要求：

- 和 ACN 同地；
- 和 ACN 同日期；
- 做成“真实园区现场”。

它就是：

> **真实工业能源背景 + 真实 EV 行为的 hybrid replay。**

------

## 2. 一套 1min load+PV 数据

这个专门支撑：

> EV/BESS 快慢响应。

需要至少：

```text
timestamp
load_kw
pv_kw
```

最好有：

```text
weather
submeter
```

但不是必须。

输出：

```text
real_building_1min.parquet
REAL_BUILDING_1MIN_AUDIT.md
```

------

# 五、Phase 2：先做两道完全不需要新园区数据的 CORE-P0

这是整个新阶段最重要的一步。

如果这两道门失败，后面很多方向直接杀掉。

------

# P0-A：真实 EV 响应时间谱

目的：

> **EV 到底是不是一种具有可利用时间动态的柔性资源？**

不能再用全部 negative step 粗统计。

首先严格区分：

### binding decrease

```text
pilot_after < actual_before - tolerance
```

意味着新的桩侧允许值确实压到了原实际功率以下。

### non-binding decrease

```text
pilot_after >= actual_before - tolerance
```

这种事件即使 actual 不下降也不说明 EV 不响应。

这是必须重新做的。

------

## 正向也同样分类

正向需要确认：

```text
pilot_after > actual_before + tolerance
```

并且确有允许增加空间。

------

## 对 binding event 统计

每个事件：

```text
delta_command
delta_actual_1m
delta_actual_3m
delta_actual_5m

response_fraction_1m
response_fraction_3m
response_fraction_5m
```

例如下降：

[
r_{1m}=
\frac{P_{before}-P_{1m}}
{P_{before}-P_{pilot-after}}
]

限制到合理区间只用于诊断，不掩盖异常。

------

## 分层

必须看：

```text
site
station
month
session phase
actual_before
step magnitude
previous pilot state
```

如果能够识别同一 session 多次 step，再加：

```text
first response
→ later response
```

一致性。

------

## P0-A 输出

```text
results/core_search/p0_a/
    binding_events.parquet
    response_1_3_5m_summary.csv
    station_response_summary.csv
    session_repeatability.csv

reports/core_search/
    CORE_P0_A_EV_RESPONSE.md
```

------

## P0-A 判断门

### GO

同时出现：

- binding events 数量充分；
- 1/3/5min 响应明显不同；
- 或车辆间响应幅度具有稳定异质性；
- 或最近一次真实响应对下一次有明显信息价值。

### NO-GO

如果发现：

> 真正 binding 后绝大多数车辆在 1min 内几乎完全、确定性响应，

那么：

> **“BESS先接、EV慢慢接力”这一方向直接降级。**

非常省时间。

------

# 六、P0-B：EV 群真实短时柔性规模

这是判断：

> **EV 是否真的足以改变 BESS 尺寸/运行。**

不用园区 load。

直接对 ACN 的真实 5min / 15min pool 做。

------

## 每个控制周期至少计算

```text
P_EV_actual

P_down_5m
P_up_5m

P_down_15m
P_up_15m

active_sessions
responsive_sessions
```

这里不要追求神奇“真实能力”。

建议建立多档柔性口径：

### F0 乐观

pilot/rated headroom。

### F1 历史简单

rolling-Q95。

### F2 已验证 M2

pilot + historical actual。

### F3 conservative

没有足够证据不允许增加。

下降侧根据 P0-A 得到的 binding response 使用真实响应率。

------

# 七、P0-B 最重要的是做量纲比较

统计：

```text
EV总功率
柔性功率
柔性/EV功率比例
```

例如如果得到：

```text
EV peak             400 kW
reliable down flex  160 kW
reliable up flex     90 kW
```

那 EV 柔性已经和：

> 100–200 kW BESS

处于一个量级。

这个方向值得进入系统层。

如果得到：

```text
EV peak             400 kW
reliable flex        15 kW
```

那：

> “用EV少配很多BESS”

量纲上就值得怀疑。

------

## P0-B 输出

```text
results/core_search/p0_b/
    flex_pool_5min.parquet
    flex_pool_15min.parquet
    flexibility_distribution.csv
    flexibility_by_hour.csv
    flexibility_by_concurrency.csv

reports/core_search/
    CORE_P0_B_EV_FLEX_SCALE.md
```

------

# 八、P0-A/P0-B 过门后，再做 SYSTEM-BENCH

不要一开始造复杂平台。

只做一个非常薄的统一回放层。

15min 版本：

```text
真实工业load/PV
+
ACN真实EV pool
+
BESS physical model
+
PCC limit
```

1min 版本：

```text
真实building load/PV
+
ACN真实EV response
+
BESS physical model
```

------

# 九、统一系统方程先保持最简单

统一约定：

# [ P_{PCC}

## P_{base} + P_{EV} + P_{BESS,ch}

## P_{BESS,dis}

P_{PV}
]

BESS：

[
SOC_{min}\le SOC_t\le SOC_{max}
]

[
0\le P_{ch}\le P_{ch,max}
]

[
0\le P_{dis}\le P_{dis,max}
]

能量守恒必须有单测。

不允许再出现 D3 那种：

> 变量名看起来对，实际控制语义不一致。

------

# 十、ACN 和外部负荷怎么组合

不要声称共址。

统一叫：

> **hybrid system replay**

匹配规则提前冻结：

### 时间

工作日配工作日。

保持当地 clock-time：

```text
08:00 EV
↔
08:00 load
```

### EV 渗透率

不要只用一种。

冻结：

```text
10%
20%
30%
40%
```

例如：

# [ r_{EV}

\frac{P_{EV,peak}}
{P_{base,peak}}
]

通过 scale ACN EV pool 做 penetration sensitivity。

这允许回答：

> EV 占园区负荷多少时新控制开始真正产生价值？

这个结果本身可能很有专利价值。

------

# 十一、第一轮只开三个核心方向

我现在不建议四五个都写完整控制器。

先开三个数据最匹配的。

------

# CORE-A：EV+BESS 多时间尺度协同

核心问题：

> BESS 是否可以只承担 EV 尚未响应的快速部分，而把持续功率逐步转移给 EV？

Baseline 必须包括：

### A0 BESS-only

所有 PCC 偏差都由 BESS。

### A1 instant-EV

假定 EV 指令立即生效。

这是理论乐观上界。

### A2 fixed-delay handoff

最简单固定响应时间接力。

### A3 candidate

使用 P0-A 中真实 1/3/5min 响应特性动态转移。

------

## KPI

主指标：

```text
PCC violation
BESS peak kW
BESS throughput kWh
```

保护指标：

```text
EV curtailed energy
EV delivery loss
control action count
```

------

## CORE-A GO

必须：

```text
PCC 不恶化
且
BESS peak 或 throughput
相对 strongest simple baseline ↓ >=15%
```

> 20% 强候选。

如果只赢 BESS-only、打不过 fixed-delay：

> No-Go。

------

# 十二、CORE-B：利用 EV 柔性降低最小 BESS 功率/容量

这个我认为可能最有商业价值。

问题不是：

> 给定一个 500kW BESS 怎么调？

而是：

> **满足同样 PCC/EV 服务约束到底最少要多少储能？**

------

## 每个场景进行 BESS sizing search

例如：

```text
Pmax:
0
50
100
150
...
500 kW
```

能量：

```text
0.5h
1h
2h
4h
```

判断满足：

```text
PCC violation <= threshold
EV delivery >= threshold
SOC feasible
```

的最小 BESS。

------

## Baseline

B0：

> EV 全部按原始轨迹/刚性负荷。

B1：

> 简单峰值削 EV。

B2：

> 简单 rolling EV flexibility。

Candidate：

> 使用 P0-B 真实柔性 + 系统协调。

------

## 最有价值的输出

不是：

```text
cost ↓
```

而是：

```text
Minimum feasible BESS power:
450 → 300 kW

Minimum feasible BESS energy:
900 → 650 kWh
```

或者：

> 同样的 BESS，可以把 EV penetration 从 20% 提升到 35%。

这是非常强的系统效果。

------

## CORE-B GO

至少：

> 最小 BESS P/E 相对 strongest baseline 下降 **15%**。

超过 20%：

> **优先晋级核心专利候选。**

------

# 十三、CORE-C：动态 BESS reserve

EMSx 的真实 forecast 很适合这里。

问题：

> 是否有必要永远保留固定 SOC/功率备用？

Baseline：

```text
fixed reserve = 10%
20%
30%
```

Candidate：

```text
reserve(t)
=
f(
 load forecast uncertainty,
 PV forecast uncertainty,
 EV flexibility uncertainty
)
```

但第一版绝对不要 ML。

先用：

```text
rolling forecast error quantile
```

即可。

------

## KPI

在同一可靠度：

```text
PCC violation rate
```

下比较：

```text
available BESS capacity
PV curtailment
EV curtailment
BESS throughput
```

------

## CORE-C GO

例如：

> PCC 风险相同，平均被锁死的 BESS reserve 减少 20%。

或者：

> 同样 reserve 资源，PCC violation 明显下降 >20%。

否则不做深。

------

# 十四、第二批候选暂时不要编码

以下先等第一批结果：

### CORE-D：Transformer thermal headroom

需要更多：

- ambient；
- thermal model；
- transformer parameters。

先不抢资源。

### CORE-E：短时 deliverable flexibility

需要 P0-A/P0-B 的结果。

很可能能从前三条自然生长出来。

### demand control

作为系统 baseline / 场景，不作为独立第一候选。

------

# 十五、三条方向应该怎样并行

不要三组人各写一套系统。

共同模块：

```text
core_search/system_bench/
```

共享：

- data loader；
- time alignment；
- EV pool；
- BESS；
- PCC；
- metrics；
- scenario registry。

每个方向只实现：

```text
policy.py
gate.py
report.py
```

------

# 十六、统一 scenario matrix

不要无限扩展。

第一轮只冻结：

### 外部站点

6–10 个 EMSx representative sites。

### EV penetration

```text
10%
20%
30%
40%
```

### BESS power

第一轮：

```text
0.1
0.25
0.5
× base-load peak
```

### SOC init

先：

```text
50%
```

只有 GO 后再做：

```text
20%
80%
```

### 天气/工作日

先自然数据。

不做人工极端压力场景作为主门。

------

# 十七、统一输出指标

所有方向必须输出同一张表：

```text
site_id
date
policy

pcc_violation_kw
pcc_violation_kwh
max_pcc_kw

bess_peak_kw
bess_charge_kwh
bess_discharge_kwh
bess_throughput_kwh

ev_delivered_kwh
ev_curtailed_kwh

pv_curtailed_kwh

control_actions
```

以后方向之间才能直接 PK。

------

# 十八、建立 Core Patent Score，而不是只看单指标

P0 过后，对三个方向评分：

| 项                     | 权重   |
| ---------------------- | ------ |
| 系统 KPI 改善量        | **35** |
| 跨站稳定性             | **15** |
| 真实数据占比           | **15** |
| 技术链完整程度         | **10** |
| 相对简单 baseline 增量 | **10** |
| 工程可实施性           | **5**  |
| 专利差异化空间         | **10** |

总计 100。

但有两个“一票否决”：

### 否决 1

核心系统 KPI：

```text
<10%
```

无论总分多高：

> 不进入核心专利。

### 否决 2

收益主要来自：

```text
极端 synthetic 参数
```

也不进入。

------

# 十九、prior art 应该什么时候介入？

这一次调整成：

### P0 前

只做 30–60 分钟快速扫：

> 有没有单一文献几乎完全同链。

如果有，注意即可，不阻止实验。

### 系统 P0 >15%

马上做 targeted prior-art。

不要等全部开发完。

检索的是：

> **导致效果的具体控制链。**

而不是：

```text
“EV+BESS”
“光储充”
“MPC”
```

这一次不能再因为“领域有人做过”就自己把方向杀了。

------

# 二十、推荐时间安排：压缩到三周左右

如果工程推进顺畅，我建议：

## 第 1–3 天：Data Gate

完成：

- EMSx download/audit；
- 1min load/PV download/audit；
- CORE_DATASET_REGISTRY；
- ACN 派生数据检查。

同时不写系统控制器。

------

## 第 3–6 天：CORE-P0-A + P0-B

完成：

### P0-A

EV binding response spectrum。

### P0-B

5/15min EV flexibility scale。

### Decision #1

判断：

```text
CORE-A 是否启动
CORE-B 是否启动
CORE-C 是否启动
```

如果 EV 柔性本身量纲不足，马上改路线。

------

## 第 6–9 天：System Bench v1

完成：

```text
load/PV
+
EV
+
BESS
+
PCC
```

能量守恒测试。

至少：

```text
BESS-only
EV-simple
```

两个 reference controllers 跑通。

------

## 第 9–14 天：A/B/C 三方向快速 P0

不允许追求漂亮算法。

每个只需要：

```text
最强简单 baseline
+
一个候选机制
```

输出：

```text
CORE_A_GATE.md
CORE_B_GATE.md
CORE_C_GATE.md
```

------

## 第 14 天：第一轮核心方向决策会

只允许三种结果：

### STRONG GO

> > 20% 系统改善，跨多个站稳定。

### CONDITIONAL GO

> 15–20%，有清晰机制。

### STOP

> <15% 或只有极端场景有效。

最多留 **1–2 条**。

------

## 第 15–19 天：最强方向做深

这时才：

- 更多 EMSx 站；
- external building dataset；
- parameter sensitivity；
- strongest baseline 扩展；
- failure mode；
- control loop 完整化。

------

## 第 19–21 天：核心专利评审

重新判断：

```text
问题是真实的吗？

系统收益 >15–20% 吗？

收益跨站吗？

strongest simple baseline 打赢了吗？

核心机制依赖真实数据吗？

是不是几个普通模块简单拼接？

能不能写成清楚的：
设备读取什么
计算什么
控制什么
设备产生什么变化？
```

满足才：

> **PATENT DEFINITION GO**

否则：

> 下一候选。

------

# 二十一、几个纪律必须提前冻结

### 1. 禁止再次出现“子指标漂亮 = 系统成功”

M2 已经给了我们一次非常好的教训。

以后：

> predictor / boundary / classification metric

只能是中间证据。

**最终门永远是系统 KPI。**

------

### 2. request、device capability、能量必须有物理约束

凡是：

```text
command
accepted
realized
```

都必须明确区分。

任何 controller：

```text
accepted <= requested
```

类似这种物理/语义约束从第一版就写断言。

------

### 3. strongest simple baseline 第一版就出现

不许：

> 做完 candidate 才找 baseline。

------

### 4. synthetic 只用于 stress

核心结果至少来自：

```text
REAL EV
+
REAL external load/PV
+
physical BESS
```

------

### 5. 不要求学术“惊艳”

这一点跟你前面的纠正一致。

如果一个很简单的：

```text
动态reserve规则
```

能够让：

```text
BESS被锁定的备用容量 ↓25%
PCC风险不增加
```

那就值得深入。

不需要为了看起来高级再塞 RL。

------

# 二十二、下一阶段最重要的两个文件

建议马上建立：

## `CORE_SEARCH_MASTER_PLAN.md`

记录：

- 目标；
- 数据；
- A/B/C 三方向；
- metrics；
- gates；
- stop rules；
- 时间表。

## `CORE_DATASET_REGISTRY.md`

记录每个字段：

```text
source
REAL / DERIVED / ENGINEERING
resolution
coverage
leakage risk
online availability
candidate directions
```

以后不允许任何工程师凭印象说：

> “这个数据应该有。”

------

# 二十三、最终路线图

压缩成一张图就是：

```text
                    已有 ACN REAL EV
                           │
              ┌────────────┴────────────┐
              │                         │
      P0-A 响应时间谱             P0-B EV柔性规模
              │                         │
              └────────────┬────────────┘
                           │
                  柔性/响应是否有肉？
                           │
                    NO ────┴──── YES
                    │               │
                   STOP         补真实load/PV
                                    │
                            SYSTEM-BENCH v1
                                    │
                ┌───────────────────┼───────────────────┐
                │                   │                   │
             CORE-A              CORE-B              CORE-C
           BESS-EV接力        最小BESS sizing       动态reserve
                │                   │                   │
                └───────────────────┼───────────────────┘
                                    │
                         系统KPI统一强baseline PK
                                    │
                         <15%                 >15%
                           │                    │
                          STOP              做深1–2条
                                                │
                                     多站/外部数据复现
                                                │
                                      targeted prior art
                                                │
                                         Claim tree
                                                │
                                     CORE PATENT GO/NO-GO
```

------

## 我的建议执行顺序

**现在立刻做的不是 A/B/C 控制器。**

先下达两项工程任务：

> **任务 1：完成 EMSx + 1min load/PV 数据获取和审计。**
>
> **任务 2：同时利用现有 ACN 运行 P0-A“binding EV 1/3/5min 响应谱”和 P0-B“5/15min EV 群柔性规模”。**

这四个结果——**响应速度、响应幅度、短时柔性 kW、柔性占 EV 总功率比例**——会决定后面几十%的工作是否值得继续。

如果它们有肉，就正式启动 A/B/C 三方向系统 PK；如果没有，就立即换问题，不再烧时间搭大模型。