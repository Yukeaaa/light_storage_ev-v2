# A5 Protocol Amendment（审查结论44 战略纠偏）

> 本文件是对 `configs/r1_expansion_audit.yaml` A5 部分的**解释性恢复**，不是新增变量/阈值。
> 原预注册 A5 明确冻结了五类 fixed buckets 并允许"单变量或少量预定义组合"；
> 审查结论44 纠偏：撤回 Review 43 "elapsed×concurrency 唯一 primary"限制，
> 恢复完整五类 buckets，分 opportunity/evidence 两层解释。
>
> **不新增变量、不搜索阈值、不训练 classifier。**

## 1. 为什么纠偏

Review 43 把 A5 缩成"elapsed×concurrency 为唯一 primary hypothesis"，
虽然克制，但在研究纪律上比执行原预注册更 post-hoc（看完 A4 结果再选主变量）。
同时把"support domain"和"opportunity domain"两个不同概念混在一起。

## 2. 两层解释框架

### Layer 1: Opportunity domain（什么时候有 residual opportunity）

变量：`n_active_bucket` + `elapsed_connected_bucket` + `recent_actual_quantile`

问题：什么运行状态下，A2/A3 之后还剩值得纠正的 residual opportunity？

elapsed 是重要变量，但只是其中之一——不是 invention center。

### Layer 2: Evidence/support domain（此刻证据是否足以赋予修正权限）

变量：`recent_variance_bucket` + `pilot_actual_ratio_bucket`

结合 A4 已有（不新调 threshold）：
`field_mode / pilot availability / history_coverage / severe_gap history / response_persistence`

问题：哪些情况下我们有足够在线证据去相信短时执行边界？

## 3. 专利逻辑（二维状态图）

```
在线观测
    ↓
证据支持度判断（Layer 2）
    +
运行机会判断（Layer 1）
    ↓
两者都满足 → 有限 bounded correction
有机会但证据不足 → protective boundary / history 回退
没有明显机会 → 不做主动修正
数据/历史不足 → persistence / quantile / conservative fallback
```

## 4. connected_elapsed 的定位

降级为 support/opportunity state vector 中的一个**分量**，
用于区分充电阶段和机会状态。不是独立权利要求中心。
未来专利写法：
- ❌ "当连接时长超过阈值时……"
- ✅ "根据当前及历史充电响应、连接阶段、并发状态及数据证据完整度确定当前车辆或控制池所处的执行支持状态……"

## 5. D2/D3 恢复为 final-gate 合法备选

原 V2.1 不只有 D1。D2-R"多源信息可信度分级→控制约束与回退"
和 D3-R"场站/字段模式适用度→模型/控制模式切换"在 D1 active route
不成立时，应作为融合候选检查：

```
pilot-rich → response-supported interval
current-only → history protective bound
history insufficient → conservative fallback
actual feedback → mode recovery/switch
```

Final R1 Gate 在宣布整个项目 No-Go 前，必须额外回答：
> 已有 A1–A5 是否足以形成"证据模式/字段模式→不同执行边界与控制权限"的 D2/D3 融合候选？

如果能够形成上述模式切换且有真实数据依据 → 进入专利结构审查，而不是立刻关闭。

## 6. A5 执行范围（严格锁死）

- 五类 fixed buckets（原预注册冻结，不改）：
  `recent_actual_quantile` / `n_active_bucket` / `elapsed_connected_bucket` /
  `pilot_actual_ratio_bucket` / `recent_variance_bucket`
- 禁止：新增变量、搜索阈值、训练 classifier、宣称 support rule 已验证
- 禁止：用 JPL PASS 抵消 Caltech FAIL
- 禁止：因 post-hoc slice 漂亮就调 cutpoint
- test 只产假设
- 输出：`a5_support_domain_hypothesis.csv`（原预注册契约）

## 7. 最终 R1 Gate 扩展（审查结论44）

原 A/B/C 不变，但 Final Gate 在判 A/B/C 后，若 D1 active route 不成立，
必须额外做 D2/D3 融合候选检查（不另开大型实验，只用已有 A1–A5 evidence）。
