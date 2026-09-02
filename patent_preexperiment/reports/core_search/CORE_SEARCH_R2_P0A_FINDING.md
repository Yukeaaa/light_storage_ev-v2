# CORE_SEARCH_R2_P0A_FINDING — 下调"回弹"的因果纠正

> **FROZEN FINDING / R2-A CLOSED**
>
> 状态：**FROZEN FINDING**（Round 2 第一份正式发现）
> 结论：**R2-A（rebound-aware sustained curtailment）CLOSED — premise falsified**
> 依据：对 P0-A binding down 事件重建 t+1..t+5 pilot 轨迹后的因果审计
> 冻结配置：`configs/core_search_r2.yaml`（rule_version=core_search_r2，2026-09-02）
>
> **本发现比原 P0-A 的 GO 更重要**：它把因果对象从"车辆回弹"纠正为"pilot 自身回升"。

---

## 1. 因果纠正

原 P0-A 观察：

```text
down response_fraction:  r_1m ≈ 1.145,  r_3m ≈ 0.648,  r_5m ≈ 0.585
```

原先被解释为"车辆在持续 pilot 下发生回弹"（瞬态下降 → 部分恢复 → 较低稳态）。

重建 pilot 轨迹后发现，1/3/5min 的 actual 回升主要是 **pilot 自己被重新抬高**：

| 观察窗 | pilot 相对 pilot_after 的中位 | 已回升 >1A 比例 |
|---|---|---|
| t+1 | +1.92A | 52.9% |
| t+3 | +4.98A | 61.4% |
| t+5 | +5.14A | 62.1% |

而在真正满足"pilot 持续压低"的事件里：

| 事件集 | n | retention_5m median | p25 / p75 | 强回弹(<0.5)占比 |
|---|---|---|---|---|
| 全部 binding down | 4699 | 0.808 | 0.009 / 1.133 | 42.8% |
| pilot-stable(<1A) | 204 | **1.000** | 0.992 / 1.004 | **0.5%** |
| pilot-stable(<2A) | 364 | **1.000** | 0.986 / 1.008 | **0.3%** |

```text
retention_5m = (actual_before − actual_5m) / (actual_before − actual_1m)
```

## 2. 正式结论（收敛措辞）

> **现有数据不能支持将 observed power recovery 解释为车辆侧回弹机制；pilot 后续变化来自
> 外部充电控制轨迹，其生成逻辑在 ACN 数据中不可观测，因此不作为当前核心专利机制继续研究。**

（不写"pilot 回弹属于基础设施行为、不可专利"——因为 pilot 为什么重新升高我们并不知道，
未来若获得 EMS/充电桩调度逻辑，它本身可能构成另一类系统控制问题；只是当前数据无法证明。）

## 3. P0-A 状态修正（不是改 FAIL，是改解释）

原：P0-A GO = 下调存在"瞬态→回弹→稳态"的车辆动态。

修正为：

```text
Binding down events:
车辆对真正持续的 pilot 下压表现为快速且高度持续的响应。
原 1/3/5min 总体 response_fraction 下降主要受后续 pilot 重新抬升影响，
不能解释为车辆自身的功率回弹。
```

资产名称由 `REAL RESPONSE ASSET — transient→partial recovery` 改为：

> **`REAL RESPONSE ASSET — asymmetric controllability`**

```text
DOWN: pilot 真正 binding 且持续 → actual 快速、持续跟随（retention≈1.0, under80≈0%）
UP:   pilot 提高 → actual 通常不随之增加（r_5m≈0）
```

这是事实资产，不代表已找到核心专利。

## 4. 方法学教训（已同步升级进 CORE_SEARCH_MASTER_PLAN 通用规则）

> **凡利用自然控制事件，从 t 时刻控制变化推断 t+h 的设备响应，必须同步审计整个 (t,t+h]
> 区间内控制输入轨迹；若控制输入再次发生实质变化，则不得把 t+h 输出变化单独归因于
> t 时刻控制事件。**

适用：EV pilot / BESS command / PCC setpoint / PV curtailment / EMS allocation。

## 5. robustness appendix（non-gating，不重新打开 R2-A）

`step_magnitude × pilot-stable retention_5m`（产物 `r2_p0b0/step_magnitude_robustness.csv`）：

| step_magnitude_bin | n | retention_5m median | p25 | p75 |
|---|---|---|---|---|
| small | 125 | 1.000 | 0.992 | 1.005 |
| medium | 60 | 0.999 | 0.986 | 1.004 |
| large | 19 | 1.000 | 0.999 | 1.000 |

结论：retention≈1.0 在全部阶跃幅度档一致，无小阶跃假象。**R2-A 保持 CLOSED。**

## 6. Round 2 状态快照

```text
R2-A rebound-aware control      CLOSED (premise falsified)
R2-B response-reliability       CLOSED (R2-P0-B0 under80=0.0%, p10=1.0)
R2-C service-loss-aware         ACTIVE (R2-C DATA GATE = GO)
```
