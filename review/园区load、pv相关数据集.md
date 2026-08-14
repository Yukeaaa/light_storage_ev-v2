对。现在“补真实园区 load/PV”其实不需要自己到处拼零散数据，我查了一轮后发现有一个**非常适合我们当前项目的现成数据集**，优先级明显高于我之前提到的普通建筑数据。

> ## 第一选择：EMSx —— 70 个工业站点的真实负荷/PV历史数据
>
> 这套数据和我们现在缺的“工商业园区能源背景”高度匹配。

EMSx 数据由 Schneider Electric 提供，包含 **70 个匿名工业站点**的历史负荷、光伏和预测数据，时间分辨率是 **15 min**；同时还有为 EMS benchmark 配套的储能容量、功率和效率参数。它本身就是为 microgrid/EMS 控制算法 benchmark 建的。([Zenodo](https://zenodo.org/records/5510400?utm_source=chatgpt.com))

这意味着我们现阶段其实已经能形成：

```text
ACN
真实 EV 充电与响应
        +
EMSx
真实工业站负荷/PV
        +
BESS
工程物理模型
        ↓
工商业园区 hybrid system benchmark
```

比之前“500 kW 固定负荷 + 人造 PV step”强太多。

------

# 一、EMSx 为什么特别适合我们

它的数据文件按站点组织，每个时间步都有：

```text
actual load / historical consumption
actual PV / historical PV

load forecasts:
未来 15min
未来 30min
...
未来 24h

PV forecasts:
未来 15min
...
未来 24h
```

同时是 **15 分钟分辨率**。([Zenodo](https://zenodo.org/records/5510400?utm_source=chatgpt.com))

这正好能支持我们前面讨论的：

- EV 柔性降低 BESS 所需功率/容量；
- 动态 BESS reserve；
- PV/负荷预测误差控制；
- EV+BESS 多时间尺度协调的 15min 层；
- 需量控制；
- 工业站 microgrid EMS。

而且 benchmark 原论文已经使用这套数据比较过 MPC、Open Loop Feedback、Stochastic Dynamic Programming 等控制器。([Institut Polytechnique de Paris](https://researchportal.ip-paris.fr/en/publications/emsx-a-numerical-benchmark-for-energy-management-systems/?utm_source=chatgpt.com))

所以以后我们的 baseline 甚至都不必自己凭空设计。

------

# 二、但 EMSx 有一个重要的 PV 边界

这个要提前说清楚。

虽然 EMSx 描述为 70 个工业站点的历史 PV/load 数据，但其公开包还包含一个**统一的历史 PV profile**，并按不同站点进行了相应缩放；官方数据说明明确提到，这个 PV profile 被用于各站点并可缩放到 `[0,1]`。([Zenodo](https://zenodo.org/records/5510400?utm_source=chatgpt.com))

因此以后不要把 EMSx 表述成：

> “70 个完全独立工业园的 70 套独立现场 PV 测量曲线。”

更准确是：

> **70 个工业站点的真实/现实工业微网负荷背景，以及 benchmark 所使用的历史 PV 生产曲线及其站点尺度化。**

对于我们的系统 P0 来说完全够。

但正式证据注册表里 PV 和 load 应分别记录来源，不要粗暴都打成同等级的“70站现场实测”。

------

# 三、我建议先直接拿 EMSx，而不是立刻找中国园区数据

原因是现在目的是：

> **先杀核心专利方向。**

不是证明：

> “某个中国园区已经运行成功。”

EMSx 已经足够回答更重要的问题：

### 例如 BESS sizing

在 70 个工业背景里：

```text
真实工业负荷
+
真实/历史PV
+
ACN真实EV pool
```

比较：

```text
方案0：
EV刚性
→ 需要多大 BESS

方案1：
允许EV柔性
→ 最小BESS是多少
```

如果：

```text
70站里
多数站 BESS Pmax
下降20~30%
```

这已经是非常强的方向筛选结果。

反过来，如果只有：

```text
2~4%
```

我们马上关闭。

不用等中国现场。

------

# 四、具体怎么下载

EMSx 公开数据托管在 Zenodo，并且配套的 EMSx 软件本身支持直接下载全部站点或指定站点。官方数据说明显示可以一次下载全部数据，也可以只指定例如 site 1–5。([Zenodo](https://zenodo.org/records/5510400?utm_source=chatgpt.com))

所以我建议**不要一开始全下 70 个**。

第一阶段只下：

```text
site 1
site 5
site 10
site 20
site 30
site 40
site 50
site 60
site 70
```

或者先审 metadata 后选：

```text
低负荷
中负荷
高负荷

低PV penetration
中PV
高PV
```

各 2–3 个。

先做 6–10 个站 P0。

如果方向有肉，再跑 70 站。

这样省时间。

------

# 五、第二套我建议补：真实建筑 load+PV 同站点数据

EMSx 偏工业站 benchmark。

为了避免结果完全依赖 EMSx，我们最好再找一个**真实建筑、load 和 PV 在同一个现场同步测量**的数据集。

这里已有不错的公开选择。

LBNL/IEA Annex 81 发布过 **6 个真实建筑**的亚小时级测量数据：

- 实际能源表计；
- PV generation；
- 天气；
- 部分室内环境和技术设备数据；
- 分辨率从 **1 min 到 15 min**。

这些是真实建筑采集，不是 ComStock 模拟；观测期按建筑约数周到两个月。([建筑与工业能源系统部](https://bies.lbl.gov/publications/sub-hourly-measurement-datasets-6?utm_source=chatgpt.com))

这非常适合做：

> **cross-dataset replication。**

即：

```text
EMSx industrial sites
     ↓
主要系统实验

LBNL real buildings
     ↓
外部不同场景复现
```

------

# 六、我还找到一个很适合快速调试的 1min load+PV 数据

一个公开的 Energy Demand Management 数据集里，Building C 有：

- 全楼实际总功率 `L_Tot`
- 多路分项负荷；
- 四个 PV inverter；
- `PV_Tot`
- **1 分钟分辨率**
- 覆盖 **2019 年**。([Zenodo](https://zenodo.org/records/19006030?utm_source=chatgpt.com))

这个特别适合我们做：

### EV+BESS 快慢接力

因为 EMSx 是 15min。

而如果我们想研究：

```text
0–1min BESS
1–3min EV响应
3–5min EV进一步接管
```

15min load 根本不够。

这个 1min 建筑数据就能提供系统背景。

我们可以：

```text
1min真实建筑load/PV
+
ACN 1min EV response
+
1min BESS模型
```

直接构建真正的分钟级 hybrid replay。

这是一个很值得加的数据集。

------

# 七、因此“真实园区 load/PV”最好不要只有一套

我建议形成三层。

### L1：工业系统主验证

**EMSx**

```text
70 industrial sites
15min
load + PV + forecasts
```

用途：

- BESS sizing；
- dynamic reserve；
- 需量；
- 跨工业站点复现。

------

### L2：分钟级系统验证

**1min real building load+PV**

用途：

- BESS→EV 多时间尺度接力；
- 快速 PCC 调节；
- 1/3/5min EV 响应传播。

------

### L3：外部真实建筑复现

**LBNL/IEA 6 real buildings**

用途：

- 防止结果只在一个数据来源成立；
- PV/load 同步真实测量；
- 1–15min 数据。

------

# 八、NREL ComStock 能不能用？

能，但**不能作为“真实 load”主证据**。

ComStock 提供大量商业建筑的 15min load profiles，而且模型经过大量真实电表数据校准；官方说明其建立过程中用了来自 11 个 utilities、约 230 万个 meters 的电力数据，但最终公开的单建筑 profile 本身仍然是建筑能耗模型输出。([美国可再生能源实验室](https://www.nrel.gov/buildings/end-use-load-profiles?utm_source=chatgpt.com))

所以应该标：

```text
ComStock
= CALIBRATED_SIMULATION
```

不是：

```text
REAL_EXTERNAL
```

它很适合做：

> 1000 个建筑规模的 stress test。

不适合做：

> 核心效果的第一真实证据。

------

# 九、NREL PVDAQ 也可以补 PV，但优先级不高

PVDAQ 是真实 PV performance 数据资源。

不过旧 PVDAQ API 已经下线，现在官方已迁移到新的 data map / GitHub 数据访问方式。([NREL Developer](https://developer.nrel.gov/docs/solar/pvdaq-v3/?utm_source=chatgpt.com))

它适合：

> 以后需要更多真实 PV 天气波动、云变化、PV ramp 时使用。

例如 dynamic reserve：

```text
突然云遮
PV -200kW / 5min
```

这种研究就会很有用。

但现阶段 EMSx + 1min load/PV 已经足够开始，不需要又花很多时间建 PVDAQ pipeline。

------

# 十、如果能拿到企业真实园区数据，那当然是最高等级

如果你们自身、客户、合作单位能拿到一个实际园区的数据，最低要求其实非常低。

不需要 SCADA 全量。

我只要：

```text
timestamp
P_grid / PCC
P_load
P_PV
```

最好增加：

```text
P_BESS
SOC
```

分辨率：

> **5min 或 15min 已经够绝大多数方向。**

如果做 BESS/EV 快速接力：

> 需要 1min 左右。

周期：

```text
最低：1个月
可用：3个月
很好：6个月
理想：12个月
```

------

# 十一、企业现场最容易拿错的是“负荷”定义

比如现场给你：

```text
电网总表 = 600 kW
PV = 100 kW
```

这 600 kW 可能是：

> **PCC 从电网购买的功率**

而不是：

> 园区实际负荷。

如果没有 BESS：

[
P_{load}=P_{grid}+P_{PV}
]

如果还有 BESS，则还需要考虑 BESS 充放电：

```text
P_load
=
P_grid
+
P_PV
+
P_BESS_discharge
-
P_BESS_charge
```

符号定义必须统一。

不然整个 system benchmark 会再次出现类似 D3 那种语义错误。

------

# 十二、还有一个特别重要的问题：外部 load 最好不包含 EV

因为我们后面会：

```text
外部 park base load
+
ACN EV
```

如果外部 load 本身已经包含大量 EV charging，然后我们又把 ACN EV 叠上去：

> **会重复计算 EV。**

所以最理想的数据是：

```text
non-EV base load
PV
```

然后：

```text
P_site =
P_base
+
P_ACN_EV
-
P_PV
```

如果实际数据无法分离 EV：

1. 优先选无明显 EV 负荷的工业/建筑站点；
2. 或明确说它是 external background load，并把 ACN EV 作为额外新增 penetration；
3. 不能说这是原现场真实总负荷。

------

# 十三、不同国家、不同日期的 ACN EV 和 EMSx load 能不能直接叠？

**可以做 hybrid replay，但不能假装共址。**

我们真正研究的是：

> 控制机制在一批真实 EV 轨迹和一批真实工业负荷轨迹组合以后是否仍有系统效果。

不是研究：

> Caltech 2020 年某一天真实发生了某工业站的负荷。

所以应该这样写：

> “从真实工业负荷/PV数据集中选取园区能源背景，从 ACN 数据集中选取真实 EV 充电池，在统一功率基值和时间分辨率下构建混合回放。”

这完全合理。

------

# 十四、怎么把两个数据组合起来才不会随便拼

不要随机乱配。

建议至少按三个维度匹配。

### 1. 工作日

```text
weekday EV
↔
weekday industrial load
```

周末：

```text
weekend
↔
weekend
```

### 2. 时段

保持当地时钟：

```text
08:00 ACN
↔
08:00 EMSx
```

不要把美国 8:00 的 EV 峰随机放到工业负荷凌晨 3:00。

### 3. 功率规模

采用 penetration ratio，而不是硬把 ACN 原始 kW 塞进去。

例如：

```text
EV peak / base-load peak
=
10%
20%
30%
40%
```

真实 ACN 只提供 EV **形状和响应行为**。

通过统一倍率构造不同园区 EV penetration。

这不是造假，是正常工程 scaling。

但倍率必须事前冻结。

------

# 十五、我建议 SYSTEM-BENCH 最终采用这个数据结构

```text
timestamp
site_id

# REAL_EXTERNAL
base_load_kw
pv_kw
load_forecast_kw
pv_forecast_kw

# DERIVED_REAL FROM ACN
ev_uncontrolled_kw
ev_session_count
ev_up_flex_5m_kw
ev_down_flex_5m_kw
ev_up_flex_15m_kw
ev_down_flex_15m_kw
ev_response_1m
ev_response_3m
ev_response_5m

# ENGINEERING
bess_soc
bess_charge_limit_kw
bess_discharge_limit_kw
transformer_limit_kw

# CONTROL OUTPUT
ev_command_kw
ev_realized_kw
bess_power_kw
pcc_power_kw
```

这么一张统一表，以后所有热点方向都能复用。

------

# 十六、现在其实可以把之前列出的候选重新映射

### EV+BESS 多时间尺度接力

使用：

```text
1min真实building load/PV
+
ACN 1min/3min/5min response
```

**数据条件：很好。**

------

### EV柔性降低 BESS 容量

使用：

```text
EMSx 70 industrial sites 15min
+
ACN 15min EV pool
```

**数据条件：非常好。**

这是目前我最推荐优先做的系统级方向之一。

------

### dynamic BESS reserve

EMSx 特别合适。

因为它不仅有真实历史 load/PV，还直接提供**历史预测值**。([Zenodo](https://zenodo.org/records/5510400?utm_source=chatgpt.com))

这意味着我们不需要：

> 自己人为造 forecast error。

可以直接获得：

```text
load forecast error
PV forecast error
```

然后研究：

```text
误差大
→ 多留BESS reserve

误差小
→ 放开BESS
```

**这使 dynamic reserve 的数据可行性从我上一轮评的 B-/C+，直接上升到 A-/B+。**

这是一个重要的新判断。

------

# 十七、所以我现在建议真正下载顺序

不要到处抓几十套数据。

**第一批只补两个。**

### 数据集 A：EMSx

目的：

> **工业园15min系统级核心 benchmark。**

先下载 metadata + 6～10 个代表 site。

如果格式、时间跨度、缺失率合适，再全 70。

### 数据集 B：1min load+PV building

目的：

> **快速动态控制 benchmark。**

用于 1/3/5min BESS+EV 接力。

然后再考虑 LBNL 6-building dataset 作为 external validation。

------

## 这会让我们的数据体系变成

```text
                     ┌─ ACN raw
                     │  REAL EV
                     │
              ┌──────┴──────┐
              │             │
        1min dynamic     15min energy
              │             │
              │             │
1min real load+PV       EMSx 70工业站
              │             │
              └──────┬──────┘
                     │
              HYBRID SYSTEM BENCH
                     │
          ┌──────────┼──────────┐
          │          │          │
      快慢接力   BESS sizing  dynamic reserve
```

这比继续依赖 XiTongJueCe 的合成园区背景强一个数量级。

**尤其是 EMSx，我认为应该直接纳入当前项目的数据资产。它几乎就是我们现在缺失的“工业园 load/PV + forecast + BESS benchmark 外壳”，而 ACN 正好补上它缺失的真实 EV 充电响应层。**