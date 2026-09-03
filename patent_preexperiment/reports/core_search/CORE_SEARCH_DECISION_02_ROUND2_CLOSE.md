# CORE_SEARCH_DECISION_02 — Round 2 关闭与 Round 3 转向

> **FROZEN DECISION — CORE SEARCH ROUND 2 CLOSED**
>
> 状态：**FROZEN DECISION**（CORE-SEARCH Round 2 正式封口）
> 依据：R2-A（CLOSED）+ R2-B0（CLOSED）+ R2-C2a（STOP）三段负证据链
> 证据锚点：
> - `CORE_SEARCH_R2_P0A_FINDING.md`（R2-A CLOSED）
> - `CORE_SEARCH_R2_P0B0.md`（R2-B CLOSED）
> - `CORE_SEARCH_R2_C2A_GATE.md`（R2-C STOP）
>
> **Round 2 不是"暂时没找到算法"，而是得到了一条完整的负证据链。**

---

## 1. Round 2 负证据链（冻结）

```text
R2-A（回弹感知控制）：
所谓车辆回弹 → 实际主要是 pilot 再变化
→ 机制前提被证伪 → CLOSED

R2-B（响应可靠性选择）：
pilot 持续下压后 → 车辆几乎完整执行
→ 没有值得预测的欠交付异质性（under80≈0%）→ CLOSED

R2-C（服务损失感知分配）：
服务风险确实有方差（完成比 IQR 0.394）
→ 但用户自报 minutesAvailable / reported_service_slack
   已是强且充分的简单信号（AUC 0.705）
→ 更复杂在线特征无增量，甚至更差（ΔAUC=-0.026）→ STOP
```

---

## 2. 冻结四项处置

1. **R2-C2b 不执行**：R2-C2a STOP 已关闭分配回放，不进入六臂 allocation。
2. **不救 R2-C**：不通过换模型（RF/XGBoost/NN）、加特征、加未来信息、
   调 has_slack 阈值、删除 B4 baseline、或绕道 R2-C2b allocation 来救。
3. **事实资产保留**：
   - `REAL RESPONSE ASSET — asymmetric controllability`：EV 下调高度可执行
     （pilot-stable 下 retention≈1.0、under80≈0%），上调基本不可执行（r_5m≈0）。
   - `reported_service_slack = minutesAvailable − kWhRequested/rated_power×60`
     作为工程可用规则保留。
4. **关闭搜索空间**：除非出现新的数据类型或新的物理问题，不再把
   "EV 响应预测 / 车辆选择 / 服务排序" 作为核心专利搜索空间。

---

## 3. 禁止救援（红线，冻结）

```text
ROUND 2 CLOSED：

禁止：
- 对 R2-C 换 RF/XGBoost/NN 后重新声称核心候选
- 增加未来信息（disconnect/doneCharging/kWhDelivered 作在线特征）
- 调 has_slack=15min 阈值找正结果
- 删除 B4 reported-service-slack baseline
- 继续设计 R2-C2b allocation 来绕过 C2a STOP
- 把 AUC 0.705 的简单用户申报规则包装为核心发明

允许：
- 作为工程模块复用 reported_service_slack
- 作为后续其他系统方向的从属控制优先级
- 保留 EV 下调可执行/上调不可执行的事实证据，作系统层的"已知负荷特性"
```

---

## 4. Round 3 转向（发明中心改变）

从"哪辆 EV 怎么调"切换到：

> **园区在面对负荷/PV 不确定性、PCC 约束和储能有限功率/能量时，如何更有效地决定
> BESS 什么时候必须保留能力、什么时候可以释放能力。**

系统收益直接落在：BESS 可用容量 / 峰值功率 / throughput / PCC 越限 / PV 弃光 /
demand peak / 同设备容量可承载负荷——**不要求 EV 有几百 kW 柔性**。

ACN 不扔，但 EV 降为"已知负荷特性"（真实 EV load trajectory + 下调可执行 + 上调不可依赖），
发明中心改为 PCC / BESS / load-PV uncertainty。

---

## 5. Round 3 候选（问题级，详见 CORE_SEARCH_ROUND3_CANDIDATES.md）

| 候选 | 问题 | 第一杀伤门 |
|---|---|---|
| R3-A 动态 BESS 备用释放/恢复 | 固定 20–30% 备用是否长期过度保守 | 同风险水平下可释放备用是否经常 ≥15–20% |
| R3-B 方向分离储能备用 | 为何给充电侧/放电侧留对称备用 | 非对称 reserve 是否明显减少被锁容量 |
| R3-C 需量窗口剩余预算控制 | 窗口前后段同一越限不等价 | 同 demand cap 下 BESS throughput / EV 削减 ↓15–20% |
| R3-D 动态变压器热裕量 | 固定额定 kW 是否浪费短时热容量 | 同热点/老化约束下可承载负荷 ↑15–20% |

R3-A/R3-B 视为同一搜索族的两个机制版本，先不各自搭系统。

---

## 6. 下一步

> 获取/审计 EMSx（真实 load/PV + 历史 forecast）→ `R3-P0-A` 真实 forecast-error /
> reserve-opportunity 数据门 → 有肉才进入 R3-A/B 系统层，否则看 R3-C。

Round 3 只预注册到"问题级"，不冻结算法。
