# CORE_SEARCH_DECISION_04 — R3-C STOP（需量窗口预算控制关闭）

> **FROZEN DECISION — R3-C CLOSED**
>
> 依据：`CORE_SEARCH_R3C_GATE.md`（系统层 = STOP）
> 证据：Building C 真实 1min net-load，Pcap=train Q90=283.8kW，BESS Pmax=172.1kW/Emax=15.7kWh。

---

## 1. 核心判定

| 项目 | 判定 |
|---|---|
| R3-C 需量窗口预算控制 | **STOP** |
| Candidate C（latest-safe feasibility boundary） | 相对 strongest baseline 仅 **5.0%** 增量 |

## 2. 证据（validation 段，四臂共享 BESS）

| arm | throughput_kwh | peak_kw | actions | violation_kwh |
|---|---|---|---|---|
| B0 instantaneous | 1115.2 | 106.8 | 4806 | 4875.3 |
| **B1 remaining-budget** | **1017.4** | 106.8 | 4354 | 4834.6 |
| B2 persistence-forecast | 1017.4（≡B1） | 106.8 | 4354 | 4834.6 |
| C latest-safe boundary | 966.5 | **172.1** | 1232 | 4851.7 |

- **B1 ≡ B2**（persistence forecast 下二者代数等价，印证了"别把 B1/B2 当两个独立机制"）。
- B1/B2 相对 B0 已降 throughput **8.8%**（窗口预算语义本身的价值）。
- C 相对 B1/B2 仅再降 **5.0%**（engineering tweak），且 **peak 从 106.8 升到 172.1 kW**（defer 后集中放电的代价）。

## 3. 结论（回答 R3-C0 的关键问题）

> R3-C0 的 100% opportunity 主要是"瞬时阈值 baseline 太弱"。强基线 B1/B2 已经捕获
> 15min 窗口预算语义；BESS 可行性边界（C）在强基线之上只多出 5%，达不到 15–20% 核心增量，
> 反而以更高峰值功率为代价。动作次数下降（-72%）不构成系统 GO。

## 4. 禁止救援（红线，冻结）

```text
R3-C CLOSED：

禁止：
- 换 forecast（非 persistence）救 C
- 加 BESS P/E 约束变体 / 换 recharge 规则救 C
- 上 RF/XGBoost/NN
- 把"动作次数少 72%"包装为核心发明
- 拿 Q85/Q95 或工作日子集救活

保留：
- B1 remaining-budget 作为"已捕获窗口预算语义"的最强简单基线
- 供后续方向作 baseline / 从属机制
```

## 5. Round 3 状态

```text
R3-A 动态备用        STOP
R3-B 方向分离         HOLD / no evidence
R3-C 需量窗口预算控制   STOP
R3-D 变压器热裕量      唯一剩余候选（第二梯队）
```

## 6. 下一步

> 只剩 R3-D（动态变压器热裕量）：固定额定 kW 是否浪费短时热容量。
> 需真实 load + ambient + IEEE/IEC 工程热模型；证据链较弱。
> 若 R3-D 也死，Round 3 三条系统方向全部关闭，需回到问题级重新搜索。
