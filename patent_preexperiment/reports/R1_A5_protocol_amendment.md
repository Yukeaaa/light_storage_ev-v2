# A5 Protocol Amendment v1.1（审查结论44/45 战略纠偏 + 协议收口）

> 本文件是对 `configs/r1_expansion_audit.yaml` A5 部分的**解释性恢复**，不是新增变量/阈值。
> 原预注册 A5 明确冻结了五类 fixed buckets 并允许"单变量或少量预定义组合"；
> 审查结论44 纠偏：撤回 Review 43 "elapsed×concurrency 唯一 primary"限制，
> 恢复完整五类 buckets，分 opportunity/evidence 两层解释。
> 审查结论45 v1.1：区分已有固定 bins 与需 outcome-blind train-only 冻结的变量；
> pilot_actual_ratio 明确为 lagged/pre-action；Final Gate 改两级 verdict；
> Layer 2 措辞降级；output schema + 组合限制冻结。
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

### Layer 2: Evidence/support domain（决定采用哪种 boundary proxy / control permission）

变量：`recent_variance_bucket` + `pilot_actual_ratio_bucket`（lagged/pre-action 实现，见 §8）

结合 A4 已有（不新调 threshold）：
`field_mode / pilot availability / history_coverage / severe_gap history / response_persistence`

问题（审查结论45 P1 降级）：哪些在线证据模式支持采用 response/history-derived
boundary proxy，哪些情况下应降级到 protective/conservative fallback？

不假定 C-008（短时可执行功率区间可生成）已证明——E2 未跑。
当前证据等级：C-008/C-009/C-010 均 D/未证明。

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

- 五类 buckets（原预注册变量名，§8 区分已有固定 bins 与需 train-only 冻结的变量）：
  `recent_actual_quantile` / `n_active_bucket` / `elapsed_connected_bucket` /
  `pilot_actual_ratio_bucket` / `recent_variance_bucket`
- 禁止：新增变量、搜索阈值、训练 classifier、宣称 support rule 已验证
- 禁止：用 JPL PASS 抵消 Caltech FAIL
- 禁止：因 post-hoc slice 漂亮就调 cutpoint
- 禁止：五变量全组合/笛卡尔积（见 §10 组合限制）
- test 只产假设
- 输出：`a5_support_domain_hypothesis.csv`（§9 冻结 schema）

## 7. Final R1 Gate 两级 verdict（审查结论45 P0-3 纠正）

**Stage 1 — D1 verdict**（A/B/C 原义不变）：

```text
A = support-aware bounded correction candidate
B = protective-only D1 candidate
C_D1 = D1 insufficient
```

**Stage 2 — architecture/patent route review**（不另做实验，只用 A1–A5 evidence）：

检查 D2/D3 融合候选是否成立（§5 模式切换）。

**项目最终 verdict**：

```text
A + D2/D3 modules → 窄 GO + 融合架构
B + D2/D3 modules → protective GO + 融合架构
D2/D3 fusion independent candidate → 转入 D2/D3 专利结构审查
Overall NO-GO → 仅当 D1 insufficient AND D2/D3 fusion also insufficient
```

**禁止**：先判 C（整个 No-Go）再 rescue D2/D3（post-hoc rescue）。
必须先判 C_D1（D1 不足），再判 D2/D3，最后才给项目最终 verdict。

## 8. Bucket 边界冻结规则（审查结论45 P0-1）

### Pre-existing fixed edges（A1/A2 frozen evidence 中已使用，早于 A5 决策）

```text
n_active_bucket:
  1 / 2-3 / 4-7 / 8-15 / 16+

connected_elapsed_bucket:
  <30 / 30-59 / 60-119 / 120-239 / 240+
```

### Pre-registered variables, edges not previously numerically frozen

```text
recent_actual_quantile
recent_variance
pilot_actual_ratio（lagged/pre-action，见 §8b）
```

后三者必须现在冻结一个**与 outcome 完全无关的 deterministic binning rule**：

> **仅使用 frozen train distribution 建 ECDF/quantile bins（quartile: 25/50/75/100），
> 边界由 train feature distribution 决定，不看 candidate label、E1/E3 outcome、
> validation/test。**

执行：
```text
train 得到 edges → 写入 manifest → validation/test 只 apply → 禁止重新拟合
```

这些仍只能叫 **post-hoc hypothesis-generation bins**，
不叫"独立验证阈值"或"工程 support threshold"。

### §8b: pilot_actual_ratio 执行语义（审查结论45 P0-2）

原 A5 名称 `pilot_actual_ratio_bucket` 在执行语义上解析为
**A4 已冻结实现的 pre-action `median_lagged_pilot_actual_ratio`**（pilot_lag1 / actual_lag1）。

**禁止恢复 current-cycle ratio。**

定位为 **measured-pilot evidence diagnostic**，参与 Layer 2，
但**不得单变量赋予控制权限**（不写"ratio 超阈值→允许 active correction"）。

JPL current-only 无 pilot → `NA + reason: no_pilot_in_current_only_domain`，
不换另一指标补洞。

## 9. Output schema（审查结论45，冻结表结构防止写代码时改口径）

`a5_support_domain_hypothesis.csv` 列：

```text
layer                 # opportunity / evidence
pool                  # caltech / jpl
split                 # train / validation / test
field_mode            # measured_pilot / current_only / NA
variable              # n_active / elapsed / recent_actual_q90 / recent_var / lagged_pilot_actual_ratio
bucket                # 如 "2-3" / "60-119" / "Q1" 等
bucket_rule_source    # pre_existing / train_quartile_ecdf / NA
n_evaluable           # 该 bucket 可评估 cycle 数
n_e1_events           # 该 bucket E1 core events（若适用）
e1_evidence_rate      # n_e1_events / n_evaluable
n_e3_valid_cycles     # E3 valid cycles
n_e3_candidates       # E3 A2 candidate cycles
e3_candidate_rate     # n_e3_candidates / n_e3_valid_cycles
daily_candidate_energy_share
a2_elimination
a3_elimination
direction_vs_reference # 该 bucket vs 同变量其他 bucket 的方向
interpretation_scope   # hypothesis / diagnostic / insufficient
```

某指标对某 pool 不可计算 → `NA + reason`，不换指标补洞。

## 10. 组合限制（审查结论45，防止过窄纠偏成过宽）

五个单变量固定审计**全部做**。

交互项**只允许协议预先写死的极少数结构组合**：

```text
n_active × connected_elapsed
```

代表明确的 opportunity state（并发 × 充电阶段），不是为了找效果随意组合。

Layer 2 不做 `variance × ratio × field_mode` 笛卡尔积。

## 11. 原预注册引用

本 amendment 不修改 `configs/r1_expansion_audit.yaml`。
A5 原预注册五变量名不变；§8 冻结的 binning rule 是对原"fixed buckets"的
必要补充解释（原文件只冻结了变量名，未冻结全部数值边界）。
