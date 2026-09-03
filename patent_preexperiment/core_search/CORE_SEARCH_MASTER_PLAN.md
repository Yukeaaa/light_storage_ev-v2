# CORE-PATENT SEARCH：系统级核心专利筛选阶段 — 总计划

> **本文件是 CORE-PATENT SEARCH 阶段的权威执行计划**，由 `review/CORE-PATENT SEARCH：系统级核心专利筛选阶段.md`
> + `review/园区load、pv相关数据集.md` + `review/数据体系.md` 三份审查稿整合冻结。
> 下一阶段不再以"把某个 EV 子算法做深"为主线，而正式切换为：在现有真实 EV 数据基础上，
> 快速找到一个能带来**明显系统收益**、且能形成完整控制机制的核心专利方向。
>
> **三大原则**：真实数据先行、系统效果先行、强简单 baseline 先行。
>
> **最新状态（2026-09-03 R4-A0b）**：Round 4 双线数据门已完成；R4-C0 ACN EVSE
> infrastructure event audit = STOP 并正式关闭，不进入 R4-C1，不做子集/极端事件救援。R4-A0
> 原 Iontech/Aachen 本地聚合源为 DATA_PENDING；R4-A0b 已落地 RWTH Aachen 官方 M5BAT 数据集
> （DOI 10.18154/RWTH-2025-06555），判定 **DATA_SOURCE_RESOLVED / LEVEL B**。
> R4-A1 A1-0/A1a 已完成，但 A1S 纠错审计使用作者论文 Test 2 anchors 裁决：S0 raw-label
> execution alignment 为权威口径，S1 supplementary UTC+1/UTC+2 归一产生伪强 tracking 信号。
> `09419f3` A1a STRONG_A1B = SUSPENDED，A1b/system layer = BLOCKED。当前结论：
> **R4-A_TRACKING_HOLD / corrected A1a required / no system layer**；只允许 tracking-capability
> gate，不得称 BESS 物理降额，不启动 Round 5。
>
> **与 V2.0 协议的关系**：本阶段不改 V2.0 的实验编号（E0–E8）与门标准，而是新增一条
> "系统级核心专利筛选"工作流。V2.0 已完成的 EV 侧机制证据（P2 NARROW GO）作为本阶段的
> EV flexibility baseline 与反例证据复用，不删除、不复活。

---

## 0. 阶段定位与旧资产处置

### 0.1 旧 E7-FAST / M2 处置（冻结，不删除）

```text
E7-FAST / M2
--------------------------
D2 vehicle-side mechanism     VALID      (EV 侧机制成立)
core-patent status            NO-GO      (系统价值未达核心专利)
D3 system value               CLOSED     (train+val 0.01% FAIL)
D3 recovery                   CLOSED     (P2.1A formal FAIL)
24h rescue                    CLOSED
Q95 retuning                  CLOSED
ML rescue                     CLOSED
```

旧 `phase3_p2/`、`phase3_p2_1/`、`e7_fast/` 全部冻结，后续用途：
1. 新系统实验的 **EV flexibility baseline**（B2 rolling-Q95 / M2 pilot+Q95）；
2. 信息不足时的 fallback；
3. 证明"被动历史边界优化未必产生系统收益"的反例；
4. 后续新核心专利的可能从属模块。

### 0.2 本阶段不修改 frozen P2/P2.1 证据

`src/patent_preexperiment/{phase3_p2, phase3_p2_1, e7_fast}` 只读复用，新代码统一进
`src/patent_preexperiment/core_search/`。

---

## 1. 阶段总目标

回答：

> **在工商业园区光储充系统中，哪一种新的 EV/BESS/负荷/光伏协调机制，能够在真实 EV 行为
> 和真实园区能源背景下，稳定地产生足够大的系统级技术效果，并值得作为核心专利申请？**

"足够大"统一冻结为系统 KPI（不是预测误差）：

| 系统效果改善 | 判断 |
|---|---|
| <5% | **DEAD** |
| 5–10% | 工程小改进，不作为核心专利 |
| 10–15% | 观察 |
| 15–20% | 值得深入 |
| **>20%** | **强核心候选** |

优先系统 KPI：最小 BESS 功率需求 / 最小 BESS 能量需求 / BESS 实际吞吐 / BESS 峰值功率 /
PCC·变压器越限 / EV 被削减能量 / EV 最终交付 / PV 弃光 / 可承载 EV 渗透率 / 可用 BESS 备用容量。

---

## 2. 数据资产五分类（详见 `CORE_DATASET_REGISTRY.md`）

```text
REAL_CORE      ACN-Data-Static（85877 文件/4.49 亿行）+ ACN API 元数据
DERIVED_REAL   1/5/15min 会话表 + 控制池 + pilot-step 库 + M2 事件集 + split 注册表
REAL_EXTERNAL  EMSx 70 工业站 15min load/PV/forecast（待补）+ 1min 建筑 load/PV（待补）
               + LBNL/IEA 6 真实建筑（外部复现，第二批）
ENGINEERING    BESS 功率/容量/SOC/效率模型 + PCC + 变压器额定约束
SYNTHETIC      仅 stress test / penetration scaling / 参数敏感性，不作核心真实证据
```

数据资产红线：
- 外部 load 最好**不含 EV**（避免与 ACN 叠加重复计算）；若无法分离，明确标为 external
  background load，ACN EV 作为额外新增 penetration，不得声称是原现场真实总负荷。
- 符号统一：`P_load = P_grid + P_PV + P_BESS_discharge − P_BESS_charge`。
- PV 与 load 分别记录来源（EMSx 的 PV 是统一历史 profile 站点缩放，非 70 套独立实测）。
- 不假装共址：统一称 **hybrid system replay**。

---

## 3. Phase 1：数据补齐（与 P0-A/P0-B 并行，第 1–3 天）

### 3.1 EMSx（L1 工业系统主验证）

先下 6–10 个代表站（低/中/高负荷 × 低/中/高 PV × 不同工作日模式），不一开始全下 70 站。

产出：
```text
emsx_site_registry.csv
emsx_load_pv_15min.parquet
emsx_forecast_errors.parquet
EMSX_DATA_AUDIT.md
```
审计：时间跨度 / 缺失率 / 时间分辨率 / load·PV 单位 / forecast horizon / load 与 PV 定义 /
异常连续零值 / 不同站功率尺度。

### 3.2 1min 建筑 load+PV（L2 分钟级系统验证）

专门支撑 EV/BESS 快慢响应（EMSx 15min 不够研究 0–1/1–3/3–5min 接力）。

最低字段：`timestamp / load_kw / pv_kw`（最好有 weather / submeter）。
产出：`real_building_1min.parquet` + `REAL_BUILDING_1MIN_AUDIT.md`。

### 3.3 第二批外部复现（L3，P0 过门后）

LBNL/IEA Annex 81 的 6 个真实建筑（1–15min，load+PV 同址同步测量），作 cross-dataset
replication，防结果只在单一数据来源成立。ComStock 只能标 `CALIBRATED_SIMULATION`，不作核心真实证据。

---

## 4. Phase 2：两道零成本数据门（第 3–6 天，不需新园区数据）

这是整个新阶段最重要的一步。两门任一失败，后续多个方向直接杀掉。

### 4.1 P0-A：真实 EV 响应时间谱

目的：**EV 到底是不是一种具有可利用时间动态的柔性资源？**

不能再用全部 negative step 粗统计。严格区分：

- **binding decrease**：`pilot_after < actual_before − tolerance`（新桩侧允许值确实压到原实际功率以下）
- **non-binding decrease**：`pilot_after ≥ actual_before − tolerance`（actual 不下降也不说明 EV 不响应）

正向同理分类：`pilot_after > actual_before + tolerance` 且确有允许增加空间。

每事件计算：
```text
delta_command
delta_actual_1m / delta_actual_3m / delta_actual_5m
response_fraction_1m / response_fraction_3m / response_fraction_5m
```
下降响应分数：`r_1m = (P_before − P_1m) / (P_before − P_pilot_after)`（限制到合理区间只用于诊断，不掩盖异常）。

分层必须看：site / station / month / session phase / actual_before / step magnitude /
previous pilot state；同 session 多次 step 加 first→later 一致性。

**P0-A 输出**：
```text
results/raw/core_search/p0_a/
    binding_events.parquet
    response_1_3_5m_summary.csv
    station_response_summary.csv
    session_repeatability.csv
reports/core_search/CORE_P0_A_EV_RESPONSE.md
```

**P0-A 判断门**：
- **GO**（同时出现）：binding 事件数量充分；1/3/5min 响应明显不同；或车辆间响应幅度稳定异质性；
  或最近一次真实响应对下一次有明显信息价值。
- **NO-GO**：真正 binding 后绝大多数车辆在 1min 内几乎完全、确定性响应
  → "BESS 先接、EV 慢慢接力"方向直接降级。

### 4.2 P0-B：EV 群真实短时柔性规模

目的：**EV 是否真的足以改变 BESS 尺寸/运行。** 不用园区 load，直接对 ACN 真实 5/15min pool 做。

每控制周期计算：
```text
P_EV_actual
P_down_5m / P_up_5m
P_down_15m / P_up_15m
active_sessions / responsive_sessions
```
多档柔性口径：
- **F0 乐观**：pilot/rated headroom
- **F1 历史简单**：rolling-Q95
- **F2 已验证 M2**：pilot + historical actual
- **F3 conservative**：没有足够证据不允许增加
- 下降侧根据 P0-A 得到的 binding response 使用真实响应率

**量纲比较**（最重要）：
```text
EV总功率 / 柔性功率 / 柔性占EV功率比例
```
例：EV peak 400kW / reliable down flex 160kW / reliable up flex 90kW → EV 柔性与 100–200kW BESS
同量级，值得进系统层。若 EV peak 400kW / reliable flex 15kW → "用 EV 少配 BESS"量纲上即值得怀疑。

**P0-B 输出**：
```text
results/raw/core_search/p0_b/
    flex_pool_5min.parquet
    flex_pool_15min.parquet
    flexibility_distribution.csv
    flexibility_by_hour.csv
    flexibility_by_concurrency.csv
reports/core_search/CORE_P0_B_EV_FLEX_SCALE.md
```

### 4.3 Decision #1（第 6 天）

P0-A + P0-B 过门 → 启动 CORE-A/B/C；EV 柔性量纲不足 → 立即改路线，不烧时间搭大系统仿真。

---

## 5. Phase 3：SYSTEM-BENCH v1（第 6–9 天，P0 过门后）

薄回放层，不一开始造复杂平台。

- **15min 版**：真实工业 load/PV + ACN 真实 EV pool + BESS 物理模型 + PCC limit
- **1min 版**：真实建筑 load/PV + ACN 真实 EV response + BESS 物理模型

### 5.1 统一系统方程（最简单）

```
P_PCC = P_base + P_EV + P_BESS,ch − P_BESS,dis − P_PV
SOC_min ≤ SOC_t ≤ SOC_max
0 ≤ P_ch ≤ P_ch,max
0 ≤ P_dis ≤ P_dis,max
```
**能量守恒必须有单测**（防 D3 那种变量名对、实际控制语义不一致）。
`command / accepted / realized` 必须物理约束断言：`accepted ≤ requested`，从第一版就写。

### 5.2 hybrid replay 匹配规则（冻结）

- **时间**：工作日↔工作日；保持当地 clock-time（08:00 EV ↔ 08:00 load）
- **EV 渗透率**：`r_EV = P_EV_peak / P_base_peak`，冻结 10% / 20% / 30% / 40%，通过 scale ACN EV pool 做
  penetration sensitivity（真实 ACN 只提供 EV 形状和响应行为，倍率事前冻结）
- **不声称共址**：统一称 hybrid system replay

### 5.3 SYSTEM-BENCH v1 验收

至少跑通 **BESS-only** + **EV-simple** 两个 reference controller + 能量守恒单测。

---

## 6. Phase 4：A/B/C 三方向快速 P0（第 9–14 天）

不追求漂亮算法。每方向只需 `strongest simple baseline + 一个候选机制`，输出 `*_GATE.md`。
三方向共享 `system_bench` 模块（data loader / time alignment / EV pool / BESS / PCC / metrics /
scenario registry），每方向只实现 `policy.py / gate.py / report.py`。

### 6.1 CORE-A：EV+BESS 多时间尺度协同

核心问题：**BESS 是否可以只承担 EV 尚未响应的快速部分，而把持续功率逐步转移给 EV？**

数据：1min 真实建筑 load/PV + ACN 1/3/5min response。

| Arm | 说明 |
|---|---|
| A0 BESS-only | 所有 PCC 偏差都由 BESS |
| A1 instant-EV | 假定 EV 指令立即生效（理论乐观上界） |
| A2 fixed-delay handoff | 最简单固定响应时间接力 |
| A3 candidate | 用 P0-A 真实 1/3/5min 响应特性动态转移 |

主 KPI：PCC violation / BESS peak kW / BESS throughput kWh。
保护 KPI：EV curtailed energy / EV delivery loss / control action count。

**GO**：PCC 不恶化 且 BESS peak 或 throughput vs strongest simple baseline ↓≥15%；>20% 强候选。
只赢 BESS-only、打不过 fixed-delay → **No-Go**。

### 6.2 CORE-B：利用 EV 柔性降低最小 BESS 功率/容量（商业价值最高）

核心问题：**满足同样 PCC/EV 服务约束到底最少要多少储能？**（不是"给定 500kW BESS 怎么调"）

数据：EMSx 70 工业站 15min + ACN 15min EV pool。

BESS sizing search：
```text
Pmax: 0 / 50 / 100 / 150 / ... / 500 kW
能量: 0.5h / 1h / 2h / 4h
```
判断满足 `PCC violation ≤ threshold ∧ EV delivery ≥ threshold ∧ SOC feasible` 的最小 BESS。

| Arm | 说明 |
|---|---|
| B0 | EV 全部按原始轨迹/刚性负荷 |
| B1 | 简单峰值削 EV |
| B2 | 简单 rolling EV flexibility |
| Candidate | 使用 P0-B 真实柔性 + 系统协调 |

最有价值输出：`最小 BESS 功率 450→300kW` / `最小 BESS 能量 900→650kWh` /
`同 BESS 下 EV penetration 20%→35%`。

**GO**：最小 BESS P/E vs strongest baseline ↓≥15%；>20% 优先晋级核心专利候选。

### 6.3 CORE-C：动态 BESS reserve

核心问题：**是否有必要永远保留固定 SOC/功率备用？**

数据：EMSx 真实 forecast（不需人造 forecast error）。

| Arm | 说明 |
|---|---|
| Baseline | fixed reserve = 10% / 20% / 30% |
| Candidate | `reserve(t) = f(load forecast uncertainty, PV forecast uncertainty, EV flexibility uncertainty)` |

**第一版绝对不上 ML**，先用 rolling forecast error quantile。

KPI：同一可靠度（PCC violation rate）下比较 available BESS capacity / PV curtailment /
EV curtailment / BESS throughput。

**GO**：PCC 风险相同，平均被锁死 BESS reserve 减少 ≥20%；或同 reserve 资源 PCC violation 下降 >20%。

### 6.4 第二批候选暂不编码

- **CORE-D Transformer thermal headroom**：需 ambient / thermal model / transformer 参数，先不抢资源
- **CORE-E 短时 deliverable flexibility**：需 P0-A/P0-B 结果，可能从前三条自然生长
- **demand control**：作为系统 baseline/场景，不作为独立第一候选

---

## 7. 统一 scenario matrix（第一轮冻结，不无限扩展）

| 维度 | 冻结值 |
|---|---|
| 外部站点 | 6–10 个 EMSx representative sites |
| EV penetration | 10% / 20% / 30% / 40% |
| BESS power | 0.1 / 0.25 / 0.5 × base-load peak |
| SOC init | 50%（GO 后才做 20% / 80%） |
| 天气/工作日 | 自然数据，不做人工极端压力场景作主门 |

---

## 8. 统一输出指标（所有方向同一张表，才能直接 PK）

```text
site_id / date / policy
pcc_violation_kw / pcc_violation_kwh / max_pcc_kw
bess_peak_kw / bess_charge_kwh / bess_discharge_kwh / bess_throughput_kwh
ev_delivered_kwh / ev_curtailed_kwh
pv_curtailed_kwh
control_actions
```

---

## 9. Core Patent Score（P0 过后对三方向评分）

| 项 | 权重 |
|---|---|
| 系统 KPI 改善量 | **35** |
| 跨站稳定性 | **15** |
| 真实数据占比 | **15** |
| 技术链完整程度 | **10** |
| 相对简单 baseline 增量 | **10** |
| 工程可实施性 | **5** |
| 专利差异化空间 | **10** |
| **总计** | **100** |

**两票否决**：
1. 核心系统 KPI <10% → 无论总分多高，不进入核心专利
2. 收益主要来自极端 synthetic 参数 → 不进入

---

## 10. prior art 介入时机

- **P0 前**：只做 30–60 分钟快速扫，有没有单一文献几乎完全同链。有则注意，不阻止实验。
- **系统 P0 >15%**：马上做 targeted prior-art（检索**导致效果的具体控制链**，不是
  "EV+BESS / 光储充 / MPC"这种粗词）。不等全部开发完。
- **不再因"领域有人做过"就自杀方向**。

---

## 11. 时间安排（压缩到三周）

| 时段 | 任务 |
|---|---|
| 第 1–3 天 | Data Gate：EMSx 下载/审计 + 1min load/PV 下载/审计 + CORE_DATASET_REGISTRY + ACN 派生数据检查（不写系统控制器） |
| 第 3–6 天 | CORE-P0-A + P0-B + **Decision #1**（A/B/C 是否启动） |
| 第 6–9 天 | System Bench v1：load/PV+EV+BESS+PCC，能量守恒单测，BESS-only + EV-simple reference controller 跑通 |
| 第 9–14 天 | A/B/C 三方向快速 P0，输出 `CORE_A_GATE.md` / `CORE_B_GATE.md` / `CORE_C_GATE.md` |
| 第 14 天 | **第一轮核心方向决策会**：STRONG GO(>20%跨站) / CONDITIONAL GO(15–20%有机制) / STOP(<15%或仅极端场景)，最多留 1–2 条 |
| 第 15–19 天 | 最强方向做深：更多 EMSx 站 + external building dataset + parameter sensitivity + strongest baseline 扩展 + failure mode + control loop 完整化 |
| 第 19–21 天 | **核心专利评审**：问题真实？系统收益 >15–20%？跨站？打赢 strongest baseline？依赖真实数据？非普通模块拼接？能写清设备读取/计算/控制/变化？→ **PATENT DEFINITION GO** 或下一候选 |

---

## 12. 冻结纪律（提前写死，防重蹈 M2/D3 覆辙）

1. **最终门永远是系统 KPI**：predictor / boundary / classification metric 只是中间证据（M2 教训）。
2. **request / device capability / 能量必须有物理约束**：`command / accepted / realized` 必须明确区分，
   `accepted ≤ requested` 从第一版就写断言。
3. **strongest simple baseline 第一版就出现**，不许做完 candidate 才找 baseline。
4. **synthetic 只用于 stress**：核心结果至少来自 REAL EV + REAL external load/PV + physical BESS。
5. **不要求学术"惊艳"**：简单动态 reserve 规则能降 25% 被锁备用就值得深入，不必塞 RL。
6. **术语纪律**（AGENTS.md 红线，违规即退回）：
   - pilot 与 actual 差异只能称"导引/允许电流与实际响应差异"，不得称"命令失败/拒绝"；
   - 只用自然 pilot 正阶跃验证过增量响应的才谈"可吸收余量"；
   - 只用观察值称"预算差值"而非"可回收能力"；
   - 未通过 E4.1 验证的响应仿真器不得输出闭环收益结论。
7. **禁止在线特征**：future disconnect / 最终 kWhDelivered / future doneChargingTime / 真实 SOC /
   真实剩余需求 / 准确未来离场 / BMS 限功率 / PCS 拒绝原因 —— 只能作离线标签或评价。
8. **预注册**：阈值在训练/验证集确定；测试集冻结后只跑一次，禁止在测试集上逐图调参。
   失败后新增方案必须新版本 + 新测试协议。
9. **统计**：同会话/池/日/预算下配对比较；会话/日级 cluster bootstrap 95%CI，不把分钟点当独立样本；
   绝对量与相对量同报；必须报最差站点/月份/会话；每实验至少抽取 20 个失败案例。
10. **自然控制事件必须审计控制输入轨迹**（R2-P0A 发现的方法学规则）：凡利用自然控制事件，
   从 t 时刻控制变化推断 t+h 的设备响应，必须同步审计整个 `(t,t+h]` 区间内控制输入轨迹；
   若控制输入再次发生实质变化，则不得把 t+h 输出变化单独归因于 t 时刻控制事件。
   适用：EV pilot / BESS command / PCC setpoint / PV curtailment / EMS allocation。

---

## 13. 最终路线图

```text
                    已有 ACN REAL EV
                           │
               ┌───────────┴───────────┐
               │                       │
       P0-A 响应时间谱           P0-B EV柔性规模
       (零新增数据)              (零新增数据)
               │                       │
               └───────────┬───────────┘
                           │
                  柔性/响应是否有肉？
                           │
                    NO ────┴──── YES
                    │               │
                   STOP         补真实load/PV
                  换问题            │
                          ┌────────┴────────┐
                          │ EMSx 6-10站 15min │ + 1min建筑load/PV
                          └────────┬────────┘
                                  SYSTEM-BENCH v1
                          (能量守恒单测 + 2 reference controller)
                                    │
                ┌───────────────────┼───────────────────┐
                │                   │                   │
             CORE-A              CORE-B              CORE-C
          BESS-EV多时间尺度     最小BESS sizing      动态reserve
          接力(1min)           (15min,EMSx)        (EMSx真实forecast)
                │                   │                   │
                └───────────────────┼───────────────────┘
                          系统KPI统一强baseline PK
                                    │
                          <15%                 >15%
                            │                    │
                           STOP              做深1–2条
                                                 │
                                      多站/外部复现 + targeted prior art
                                                 │
                                          Claim tree → CORE PATENT GO/NO-GO
```

---

## 14. 首批并行任务（现在立刻做）

| 任务 | 数据 | 产出 | 门 |
|---|---|---|---|
| **A — P0-A** | ACN 派生（零新增） | `results/raw/core_search/p0_a/` + `CORE_P0_A_EV_RESPONSE.md` | binding 响应时间谱 GO/NO-GO |
| **B — P0-B** | ACN 派生（零新增） | `results/raw/core_search/p0_b/` + `CORE_P0_B_EV_FLEX_SCALE.md` | 柔性量纲门 GO/NO-GO |
| **C-1 — EMSx** | Zenodo（新下载） | `emsx_*` + `EMSX_DATA_AUDIT.md` | 6–10 站审计通过 |
| **C-2 — 1min 建筑** | Zenodo（新下载） | `real_building_1min.parquet` + `REAL_BUILDING_1MIN_AUDIT.md` | 1min load+PV 审计通过 |

这四个结果——**响应速度、响应幅度、短时柔性 kW、柔性占 EV 总功率比例**——会决定后面几十%
的工作是否值得继续。有肉则正式启动 A/B/C 三方向系统 PK；没有则立即换问题。
