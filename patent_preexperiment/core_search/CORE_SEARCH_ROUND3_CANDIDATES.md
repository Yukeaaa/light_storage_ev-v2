# CORE_SEARCH_ROUND3_CANDIDATES — 问题级预注册

> **本文件只冻结"问题级"候选，不冻结算法。**
> 依据：`CORE_SEARCH_DECISION_02_ROUND2_CLOSE.md`（Round 2 关闭）
> 转向：发明中心从"EV 柔性选择"切到"PCC / BESS / load-PV uncertainty 下的能力保留与释放"。
> EV 降为"已知负荷特性"：真实 load trajectory + 下调可执行 + 上调不可依赖 + 真实 session 行为。

---

## 候选总览

| 候选 | 问题 | 数据 | 第一杀伤门 |
|---|---|---|---|
| R3-A 动态 BESS 备用释放/恢复 | 固定 20–30% SOC/功率备用是否长期过度保守 | EMSx actual+forecast | 同风险水平下可释放备用经常 ≥15–20% |
| R3-B 方向分离储能备用 | 为何给充电侧/放电侧留对称备用 | EMSx load/PV forecast error | 非对称 reserve 明显减少被锁容量 |
| R3-C 需量窗口剩余预算控制 | 窗口前后段同一越限不等价 | 1min/15min 真实 load + tariff rule | 同 demand cap 下 BESS throughput/EV 削减 ↓15–20% |
| R3-D 动态变压器热裕量 | 固定额定 kW 是否浪费短时热容量 | load+ambient+标准热模型 | 同热点/老化约束下可承载负荷 ↑15–20% |

R3-A / R3-B 视为同一搜索族（动态备用）的两个机制版本，不一开始各搭一套系统。

---

## R3-A 动态 BESS 备用释放/恢复

- **问题**：固定留 20–30% SOC/功率备用是否长期过度保守？能否根据真实 load/PV forecast error 动态留备用？
- **系统收益**：BESS 可用容量 / 峰值功率 / PV 弃光 / demand peak / 同容量可承载负荷。
- **数据**：EMSx actual load + actual PV + 历史 forecast（15min~24h）。
- **strongest simple baseline**：固定 reserve = 10/20/30%（固定 Q95）。
- **最便宜 P0**：`R3-P0-A` 真实 forecast-error / reserve-opportunity 数据门。
- **kill condition**：若各时段 Q95 reserve 需求几乎不变（任何时段都差不多）→ 关闭。

---

## R3-B 方向分离储能备用

- **问题**：放电侧风险（load 上偏）与充电侧风险（PV 上偏）为何留对称备用？
  能否分别计算 P_dis_reserve / P_ch_reserve，及 SOC 上下双向能量余量（E_upper / E_lower headroom）？
- **系统收益**：同样 PCC reliability 下，BESS 可调能量增加 20%+（晴天中午留"能充进去"的上部空间，
  晚高峰留"能放出来"的下部空间，避免固定 30–70% 锁死大量无谓容量）。
- **数据**：EMSx load/PV forecast error 的正负误差分布。
- **strongest simple baseline**：固定对称 reserve（SOC 30–70%）。
- **最便宜 P0**：复用 R3-P0-A 的 net-load forecast error，先看正/负误差是否明显非对称。
- **kill condition**：正负误差对称且随状态变化小 → 非对称无增量。

---

## R3-C 需量窗口剩余预算控制

- **问题**：15min 需量考核中，窗口第 1 分钟和第 14 分钟的同一功率越限不等价。
  能否按"窗口剩余能量预算"决定是否必须立即动作？
  （约束是窗口总能量 E_window ≤ P_cap × 15min，已耗能量决定剩余允许平均功率。）
- **系统收益**：减少无谓 BESS 动作 → BESS throughput ↓、EV 削减 ↓、action count ↓。
- **数据**：1min/15min 真实 load + tariff/demand rule（不需预测准，不需 EV 大柔性，不需 BMS/SOC）。
- **strongest simple baseline**：`P_PCC > threshold → BESS discharge`。
- **最便宜 P0**：真实 load 上计算"窗口前段 vs 后段"越限的 BESS 动作次数/能量差异。
- **kill condition**：窗口预算控制相对 threshold 规则的动作/能量无明显下降（<15%）。

---

## R3-D 动态变压器热裕量（第二梯队）

- **问题**：固定额定 kW 限制是否浪费短时热容量？能否按热状态决定何时允许短时超额。
- **系统收益**：同热点/老化约束下可承载负荷 ↑、减少削减。
- **数据**：真实 load + ambient + IEEE/IEC 式工程热模型（无 top-oil/hotspot telemetry，
  证据链较弱）。
- **strongest simple baseline**：固定 transformer rating limit。
- **最便宜 P0**：标准热模型 + 真实 load/ambient，看短时热裕量分布。
- **kill condition**：短时热裕量不足以产生 ≥15–20% 可承载增量。
- **优先级**：第二梯队；R3-A/C 都死才进入。

---

## EV 的角色（降级后）

```text
不扔 ACN，但不再作为发明中心。
EV 提供：
- 真实 EV load trajectory
- 下调可执行性（pilot-stable 下 retention≈1.0）
- 上调不可依赖
- 真实 connection/session 行为
系统层只用一个保守 EV fallback：
真正发生 PCC 风险时 EV 作可靠下调资源，但不作为主要备用容量来源。
```

---

## 启动顺序

```text
Decision #2（已完成）
    ↓
获取/审计 EMSx
    ↓
R3-P0-A：真实 load/PV forecast error + 动态 reserve opportunity
    ↓
有肉？ ──NO──▶ 看 R3-C 需量窗口
   YES
    ↓
R3-A/B 做深 → system bench
```

下一步：EMSx 数据获取与审计，然后 R3-P0-A。
