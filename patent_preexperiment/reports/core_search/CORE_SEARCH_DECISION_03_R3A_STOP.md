# CORE_SEARCH_DECISION_03 — R3-A STOP（动态备用关闭）

> **FROZEN DECISION — R3-A CLOSED**
>
> 依据：`CORE_SEARCH_R3A_DEV_GATE.md`（DEV gate = STOP）
> 证据：DEV 4 站（site 3/8/10/70），主口径 locked_reserve_kwh_at_95。

---

## 1. 核心判定

| 项目 | 判定 |
|---|---|
| R3-A 动态 BESS 备用 | **STOP** |
| R3-B 方向分离备用 | **HOLD / no evidence**（R3-P0-A 正负误差对称 ≈1.0） |
| R3-A holdout 站 [2,14,28,42,52,62] | **NOT CONSUMED**（未下载、未看结果） |

## 2. 证据

```text
B0 global Q95           locked 111,875 kWh
B1 hour-of-day Q95      locked  88,136 kWh   ← strongest simple baseline
B2 rolling Q95          locked 111,097 kWh
C  hour-base × regime   locked  93,239 kWh   ← -5.8% vs B1（更差）
```

- hour-of-day Q95（B1）已经把可预测的小时级 reserve 结构完整捕获（比 B0 降 21%）。
- Candidate 的 recent-regime 修正只加噪声不加信号：coverage 掉到 0.85–0.92，scale 回 0.95 后锁定量反而更大。
- 结论：同一小时在不同日期的 forecast-error 残差不可用最近 4h rolling std 预测；hour-Q95 之后剩不可预测噪声。

## 3. 禁止救援（红线，冻结）

```text
R3-A CLOSED：

禁止：
- 换 recent-regime 定义 / rolling window
- 加季节/工作日条件来救 Candidate（最多作 non-gating appendix）
- 上 RF/XGBoost/NN
- 消费 6 个 holdout 站
- 把 hour-of-day Q95 本身包装为核心发明

保留：
- hour-of-day Q95 作为"已捕获主要可预测结构"的最强简单基线
- 供后续方向（如 R3-C）作 baseline / 从属机制
```

## 4. Round 3 状态

```text
R3-A 动态备用        STOP
R3-B 方向分离         HOLD / no evidence
R3-C 需量窗口预算控制   NEXT（先 R3-C0 机会门）
R3-D 变压器热裕量      第二梯队
```

## 5. 下一步

> 转 R3-C，但先过 R3-C0 机会存在性门：真实 1min 负荷里，
> 有多少"瞬时超限但 15min 平均不超"的 false alarm 与"可延迟动作"的窗口。
> EMSx 是 15min，不能做窗口内伪 1min；用 Building C 真实 1min load+PV。
