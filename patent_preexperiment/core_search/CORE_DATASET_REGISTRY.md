# CORE_DATASET_REGISTRY：核心专利筛选阶段 — 数据资产注册表

> **本文件是 CORE-PATENT SEARCH 阶段的唯一数据资产登记**。后续所有研究必须先查本表，
> 不允许任何工程师凭印象说"这个数据应该有"。依据 `review/数据体系.md` +
> `review/园区load、pv相关数据集.md` 整合冻结。
>
> 五分类：`REAL_CORE` / `DERIVED_REAL` / `REAL_EXTERNAL` / `ENGINEERING` / `SYNTHETIC`。
> 每条记录字段：`source / resolution / coverage / leakage_risk / online_availability /
> candidate_directions`。

---

## 1. 数据资产现状总结

> **当前数据资产明显是"EV 充电侧强，园区能源侧弱；短时真实响应强，长时需求/设备健康弱"。**
> 因此最适合继续挖的核心专利，关键机制应建立在 ACN 真实 EV 时序/自然控制响应上，
> 再把 PV、园区负荷、BESS、PCC 作为系统传播层。
> 反过来，变压器热老化、BESS SOH/V2G、DC 快充 BMS 能力等方向，目前数据支撑明显不足。

---

## 2. REAL_CORE（已有原始真实数据）

| 资产 | source | resolution | coverage | leakage_risk | online_availability | candidate_directions |
|---|---|---|---|---|---|---|
| **ACN-Data-Static 时序** | 本地 `ACN-data/ACN-Data-Static/` | 1min 原始 | 85,877 文件 / 4.49 亿行 / 2018-05~2020-12 | 低（原始观测） | 已下载 | P0-A / P0-B / CORE-A / CORE-B |
| └ Charging Current | ACN Static | 1min | 85,877 文件（全覆盖） | — | — | 全方向（功率换算基础） |
| └ Pilot Signal | ACN Static | 1min | 46,173 文件 | — | — | P0-A / CORE-A（pilot step） |
| └ Voltage | ACN Static | 1min | 32,161 文件 | — | — | 功率 computed 换算 |
| └ Power | ACN Static | 1min | 60,292 文件 | — | — | P0-A / P0-B（实测优先） |
| └ Charging State | ACN Static | 1min | 57,654 文件 | — | — | session phase 分层 |
| └ Cumulative Energy | ACN Static | 1min | 56,150 文件 | — | — | 能量一致性校验（离线） |
| **ACN API 会话元数据** | 本地 `ACN-data/acn_full/` | 会话级 | 51,234 sessions | **高**（含 disconnect/doneCharging/kWhDelivered，只能离线评价，禁止在线） | 已下载 | EV 服务约束 / 尾段排除 / 标签 |

### 2.1 三站特性

| 站 | 数据质量 | 适合 | 注意 |
|---|---|---|---|
| **Caltech** | 最好 | pilot→actual 响应 / 自然 pilot step / 上调下调响应时间 / session 内响应规律 / 真实功率 / EV 柔性 | 主场景 |
| **JPL** | 量大但大量 current-only | 桩侧信息缺失/异构信息环境下的控制 | 功率换算/会话级能量质量需谨慎；额定电压 192.7V（240V 假设高估 17.7%） |
| **Office001** | 样本小但质量好 | 小型办公场站外部验证/敏感性集 | **仅外部验证，禁止用其结果改阈值** |

### 2.2 功率口径（冻结）

优先级：实测 Power → Voltage×Current（computed）→ 额定电压×Current（estimated 并标记）。
额定电压：jpl=192.7V / caltech=240V / office001=240V。

### 2.3 EV 数据支持程度

| EV 变量 | 有无 | 强度 |
|---|---|---|
| 实际电流 / 实际功率 / pilot / 自然 pilot 上下调 / 1·3·5min 响应 / 连接断开 / 最终 delivered / 多车并发 / session 历史 | 有 | **强** |
| true SOC / BMS max power / 电池温度 / 真实 EMS command / V2G discharge / 车辆内部限功率原因 | **无** | — |

→ 这张表决定 V2G / BESS 寿命 / DC 快充 BMS / 精确 SOC 需求预测 = **NO-GO**（数据不支持）。

---

## 3. DERIVED_REAL（已从原始数据加工）

| 资产 | source | resolution | coverage | leakage_risk | online_availability | candidate_directions |
|---|---|---|---|---|---|---|
| **1min session table** | ACN Static 派生 | 1min | E0-Full 构建（分区） | 低（时间切分后） | `datasets/session_response_1min` | P0-A / CORE-A |
| **5min control pool** | ACN Static 派生 | 5min | 115 桩 gold benchmark | 低 | `datasets/pool_state_5min` | P0-B / CORE-A |
| **15min control pool** | ACN Static 派生 | 15min | 115 桩 gold benchmark | 低 | `datasets/pool_state_15min` | P0-B / CORE-B / CORE-C |
| **positive pilot-step library** | ACN Static 派生 | 事件级 | train+val 11,702 事件 / 4,418 sessions / 62 stations / 18 months；test 6,643 可评价 | 低 | E7-FAST D0 产物 | P0-A / CORE-A（上调响应） |
| **negative pilot-step library** | ACN Static 派生 | 事件级 | 20,725 负向事件（**尚未充分挖掘**） | 低 | E7-FAST D0 产物 | P0-A（binding decrease）/ CORE-A（下调响应） |
| **M2 评价事件集** | ACN Static 派生 | 事件级 | train+val 10,893 / test 6,643 | 低 | E7-FAST D2 产物 | **所有新 EV flexibility 方法的 strongest simple baseline 数据集** |
| **split registry** | E0-Full 冻结 | 会话级 | 站点内 60/20/20 | — | `data_registry/e0_full_split_registry.parquet` | 全方向（切分复用） |
| **static_api_mapping** | ACN Static+API 关联 | 行级 | 96,467 行（matched 40,644 / static_only 45,233 / api_only 10,590） | — | `ACN-data/acn_project/manifests/` | 严格会话验证只用 matched |

### 3.1 M2 baseline 库（直接复用，不重新定义 baseline）

```text
B0 = no-up
B1 = pilot-only
B2 = rolling-Q95        ★ strongest simple baseline
M2 = pilot + Q95        (已验证 EV 侧机制 VALID，系统价值 CLOSED)
```

### 3.2 负向 pilot-step 金矿（尚未充分开发）

20,725 负向事件此前只做粗统计。**binding negative event**（`pilot_after < actual_before`）
才真正意味着新 pilot 已低于车辆原吸收功率。P0-A 需重新建立 binding/non-binding 分类。

---

## 4. REAL_EXTERNAL（待补，本阶段第一批数据补齐）

| 资产 | source | resolution | coverage | leakage_risk | online_availability | candidate_directions |
|---|---|---|---|---|---|---|
| **EMSx 工业站 load/PV/forecast** | Schneider Electric / Zenodo | 15min | 70 站（先下 6–10 代表站） | 低 | Zenodo public | **CORE-B / CORE-C / 需量控制** |
| **1min 建筑 load+PV** | Zenodo（Building C） | 1min | 2019 年 | 低 | Zenodo public | **CORE-A（快慢接力）** |
| **LBNL/IEA 6 真实建筑** | LBNL Annex 81 | 1–15min | 6 建筑（数周~两月） | 低 | LBNL public | L3 外部复现（第二批） |

### 4.1 EMSx 边界（必须提前说清楚）

- EMSx 描述为 70 个工业站点历史 load/PV，但**公开包含一个统一历史 PV profile，按站点缩放**。
- **不得**表述成"70 个完全独立工业园的 70 套独立现场 PV 实测"。
- 正确表述：**70 个工业站点的真实/现实工业微网负荷背景，以及 benchmark 所使用的历史 PV 生产曲线及其站点尺度化**。
- 注册表里 PV 和 load **分别记录来源**，不粗暴都打成同等级"70 站现场实测"。
- EMSx 配套储能容量/功率/效率参数 → 可作 BESS ENGINEERING 初始值。
- EMSx 有**真实历史 forecast**（15min~24h）→ CORE-C 不需人造 forecast error，数据可行性 A-/B+。

### 4.2 1min 建筑 load+PV（Building C）

字段：`L_Tot`（全楼总功率）/ 多路分项负荷 / 4 个 PV inverter / `PV_Tot` / 1min / 2019 年。
用途：EMSx 15min 不够研究 0–1/1–3/3–5min 接力，1min 建筑数据提供系统背景。

### 4.3 外部 load 红线

- 外部 load 最好**不含 EV**（避免与 ACN 叠加重复计算）。
- 若无法分离：优先选无明显 EV 负荷的工业/建筑站点；或明确标 external background load，
  ACN EV 作为额外新增 penetration；**不得声称是原现场真实总负荷**。
- 符号统一：`P_load = P_grid + P_PV + P_BESS_discharge − P_BESS_charge`。

### 4.4 hybrid replay（不假装共址）

ACN（美国，2018–2020）与 EMSx（不同国家/日期）直接叠加是 **hybrid replay**，不是共址。
正确表述：**从真实工业负荷/PV 数据集中选取园区能源背景，从 ACN 数据集中选取真实 EV 充电池，
在统一功率基值和时间分辨率下构建混合回放。**

匹配规则（冻结）：
1. 工作日↔工作日，周末↔周末
2. 保持当地时钟（08:00 ACN ↔ 08:00 EMSx）
3. 功率规模用 penetration ratio（`r_EV = P_EV_peak / P_base_peak`），不硬塞 ACN 原始 kW

---

## 5. ENGINEERING（工程模型/参数，非真实观测）

| 资产 | source | 用途 | candidate_directions |
|---|---|---|---|
| BESS 功率/容量/SOC/效率模型 | XiTongJueCe BESS 参数 + EMSx 配套参数 | BESS 物理模型初始值 | CORE-A / CORE-B / CORE-C |
| PCC 约束 | 工程场景 | PCC limit | 全方向 |
| 变压器额定约束 | 工程场景 | transformer limit | CORE-D（暂不做） |

### 5.1 BESS 主场景参数（第一轮冻结）

```text
P_BESS_max ratio: 0.1 / 0.25 / 0.5 × base-load peak
SOC: init 50% / min 10% / max 90%   （GO 后才做 20% / 80%）
eta_charge / eta_discharge: 0.95
capacity_hours: 0.5 / 1 / 2 / 4
```

---

## 6. SYNTHETIC（仅 stress，不作核心真实证据）

| 资产 | 用途 | 红线 |
|---|---|---|
| ComStock 商业建筑 load | 1000 建筑规模 stress test | 标 `CALIBRATED_SIMULATION`，不是 REAL_EXTERNAL |
| 人造极端压力场景 | stress /敏感性 | **不作主门** |
| EMS request generator | 简单规则 | 标 `SYNTHETIC_CONTROLLER` |

**核心结果至少来自**：REAL EV + REAL external load/PV + physical BESS。

---

## 7. MISSING（当前不拥有，按需补）

| 资产 | 状态 | 影响 |
|---|---|---|
| 真实工商业园区 1min/5min/15min 完整多月负荷 | **待补**（EMSx + 1min 建筑） | CORE-A/B/C 系统验证 |
| 真实园区 PV（与 ACN 同地同时） | **不拥有**（EMSx PV 是缩放 profile） | 写明 hybrid replay |
| 真实 BESS telemetry（SOC/PCS功率/BMS温度/SOH/调度命令/响应） | **MISSING** | BESS 寿命优化 NO-GO |
| 真实变压器热数据（top-oil/hotspot/ambient/thermal state/aging） | **MISSING** | 变压器热老化 NO-GO，只能标准物理模型 |
| 真实 SOC / BMS capability | **MISSING** | 精确 SOC 需求预测 NO-GO；M1 仅作从属实施例 |
| V2G 双向充电真实数据 | **MISSING** | V2G NO-GO |
| DC 快充 BMS 真实数据 | **MISSING** | DC 快充 BMS NO-GO |
| UCSD 真实同址 PV+load+BESS+EV | **未冻结审计** | 原 V2.0 E7 暂不作为已有核心数据 |

---

## 8. 候选研究方向 × 数据可行性矩阵

| 研究工作 | ACN 现有 | 园区现有 | 还缺什么 | 当前可行性 |
|---|---|---|---|---|
| **P0-A EV 1/3/5min 响应时间谱** | **完全支持** | 不需要 | 无 | **A，立即可做** |
| **binding negative-step 分析** | **完全支持** | 不需要 | 无 | **A** |
| **同 session 前后 step 响应稳定性** | **支持** | 不需要 | 无 | **A-** |
| **5min EV 群柔性规模** | **支持** | 不需要 | 无 | **A-** |
| **15min EV 群柔性规模** | **较支持** | 不需要 | 持续性定义 | **B+** |
| **EV+BESS 多时间尺度接力（CORE-A）** | EV 侧**强** | BESS 模型有 | 真实 1min load/PV | **B+**（补 1min 建筑后 A-） |
| **EV 柔性降低最小 BESS 功率（CORE-B）** | EV 侧**强** | BESS 模型有 | **真实 park load/PV** | **B+**（补 EMSx 后 A-） |
| **EV 柔性降低 BESS 容量** | 支持但更难 | BESS 模型有 | load/PV + 跨时段服务约束 | **B** |
| **动态 BESS reserve（CORE-C）** | EV 不确定性有 | BESS 有 | **真实 PV/load 预测误差** | **B-/C+**（补 EMSx forecast 后 A-/B+） |
| **需量峰值控制** | EV 有 | tariff/BESS 有 | **真实园区 load** | **B** |
| **动态变压器热裕量** | EV 有 | 参数参考有 | 真实 load + 环境/热参数 | **C+**（暂不做） |
| 30–60min VPP 柔性 | 不足 | — | SOC/真实需求/持续能力 | **C-/D** |
| BESS 寿命优化 | 很弱 | 工程退化模型 | SOH/温度/循环实测 | **D** |
| V2G | 不支持 | — | 双向充电真实数据 | **NO-GO** |
| DC 快充/BMS 能力 | 不支持 | GB/T 只有标准 | SOC/BMS/DC 快充真实数据 | **NO-GO** |

---

## 9. SYSTEM-BENCH 统一数据结构（冻结）

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

这张统一表所有热点方向复用。

---

## 10. 数据下载优先级（第一批只补两个）

### 数据集 A：EMSx（工业园 15min 系统级核心 benchmark）
先下 metadata + 6–10 代表站；格式/时间跨度/缺失率合适再全 70。

### 数据集 B：1min load+PV 建筑（快速动态控制 benchmark）
用于 1/3/5min BESS+EV 接力。

### 第二批（P0 过门后）
LBNL/IEA 6 真实建筑作 external validation。
NREL PVDAQ 仅在需要更多真实 PV 天气波动/PV ramp 时补，优先级不高。
