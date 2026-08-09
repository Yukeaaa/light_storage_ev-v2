# R1 最终收敛审计（§10.2 扩展审计）

> 审查结论33/34 准入。本审计**不是新验证实验**，而是对已冻结 E1/E3 formal test 的
> post-hoc 解释 + 支持域假设生成。预注册：`configs/r1_expansion_audit.yaml`。
>
> **纪律**：test 已暴露，§10.2 只能解释失败、定位支持域、产生下一阶段假设；
> 不能用 post-hoc 切片把 R1"重新算成 PASS"；不训练 classifier 宣称已验证 support rule；
> JPL PASS 不能抵消 Caltech FAIL。真正的新 support-domain gate 以后需新独立数据验证。

## 引用冻结源

| 项 | 值 |
|---|---|
| E3 code baseline | `c1436f43e0feba8ac072beac0cb03c851eda2c05` |
| E3 evidence commit | `310cbdb` |
| E3 pretest SHA256 | `0aeb340f4cba80324ebc2d463433de16efffd1e55e48694e5da2e1f9942ab56e` |
| E1 evidence commit | `44fa88c` |
| 停止线 | `e0_full.yaml#k1_replication_stop_lines`（不改）|

## 执行顺序

```
batch_1: A1 + A2 → gate_review_1（先审一次）
batch_2: A3 + A4
batch_3: A5
final:   最终 R1 Gate Review → A / B / C
```

---

## A1. Population Bridge：155 是怎么来的

**问题**：Caltech temporal test main ≈ 10,528 sessions → L1_strict_matched test = 155。
是数据匹配层选择效应，还是后期运营域本身真的不同？

**输出**：month × sample_layer / month × match_status / month × field_mode /
station × retained/dropped / temporal-test → strict-L1 retention rate（每月）/
155 sessions 月份站点组成 / E1 core-eligible / E3 valid-cycle-eligible 在 155 上再损失多少。

### A1 结果

**Caltech temporal-test main 10,528 → L1_strict_matched test 155（retention 1.47%）。**

收缩主因是 **strict-match 要求**（API×static matched），不是后期运营域变化本身：
10,528 = 155 L1_strict_matched + 10,373 L0_static_extension(static_only)。

155 sessions 组成：
| 月份 | n | field_mode |
|---|---|---|
| 2020-05 | 9 | measured_pilot |
| 2020-06 | 35 | measured_pilot |
| 2020-07 | 35 | measured_pilot |
| 2020-08 | 7 | measured_pilot |
| 2020-11 | 69 | measured_pilot(68) + current_only(1) |

- 154 measured_pilot + 1 current_only；全落在 2020 下半年。
- top stations：2-39-81-4550(23) / 2-39-139-28(22) / 2-39-125-21(14) / 2-39-131-30(13)。
- E1 core-eligible 在 155 上再收缩到 40 会话（E1 frozen summary：core 母体 40）；
  E3 valid-cycle-eligible 在 155 上得 63 opp cycles（A2）。

**解读**：155 是真实后期 matched 域，但母体极小（1.47% retention）；E1/E3 失败的"样本小"
背景是 strict-match 选择效应 + 后期时间窗口共同作用。这不是"数据被不当删除"，
而是 strict matched 会话在后期本身就稀疏。A2 需判断失败是否落在 155 内的更窄子集。

输出文件：`results/raw/E3F_expansion/a1_*.csv` + `a1_population_bridge.json`

---

## A2. E1 + E3 Frozen-test Decomposition

**问题**：E1 11 事件全在 2020-06 + E3 5 机会月但 79.5% 集中——是否指向同一狭窄运行状态？

**切片**：month / station / day / field_mode / concurrency_bucket / connected_elapsed_bucket
（只切片已冻结结果，不重跑、不调参、不改事件/candidate 定义）

### A2 结果

**E1 与 E3 在 test 域失败的原因不同，时段不重合。**

#### E1 核心 11 事件

| 月份 | n_events | gap_energy_kwh |
|---|---|---|
| 2020-06 | 11 | 3.224 |

- **100% 集中在 2020-06**，10/11 在单桩 `2-39-79-382`，1/11 在 `2-39-89-25`。
- 这是 pilot-actual response difference 的极端单月单桩集中。

#### E3 Caltech test opp（A2 主基线）

| 月份 | n_opp_cycles | opp_energy_kwh | energy_share |
|---|---|---|---|
| 2020-05 | 3 | 0.320 | 2.5% |
| 2020-06 | 8 | 0.686 | 5.3% |
| 2020-07 | 13 | 1.440 | 11.1% |
| 2020-08 | 3 | 0.199 | 1.5% |
| **2020-11** | **36** | **10.268** | **79.5%** |

- opp energy **79.5% 集中在 2020-11**（36 周期 / 10.27 kWh）。
- 但 M2 daily energy share median = 0.0：63 opp cycles 分布在多个 day，多数 day 的
  candidate energy 仍为 0 或极小，中位数为 0（evaluable-day K1 exact 口径真实零）。

#### E1/E3 重叠

- E1 核心月份 = {2020-06}；E3 opp 月份 = {2020-05,06,07,08,11}；shared = {2020-06}。
- **但 E1 gap energy 100% 在 2020-06，E3 opp energy 仅 5.3% 在 2020-06**——两者主峰不重合。
- E1 是 pilot-actual response 在 2020-06 单桩（2-39-79-382）；
  E3 是 A2 历史基线在 2020-11 仍残留预算差值但日中位 energy share=0。

**解读**：E1 和 E3 两项独立失败发生在同一 155-会话 test 域的**不同时段**，
共同背景是 L1 strict matched test 母体极小（155）。这强烈支持"support-domain 限制"
而非"broad 机制不存在"——但也表明 155 域内机会/response 都高度时域集中，
不适合支撑广义主动预算修正。A3-A5 需进一步判断这种集中是否可由在线可观测变量预测。

输出文件：`results/raw/E3F_expansion/a2_*.csv` + `a2_overlap.json`

---

## A3. 强简单基线压力审计

**问题**：A2/A3 elimination 77%（test）是孤立值，还是后期/某类场景普遍逼近或超过 80%？

**禁止**：不改 80% 止损线；不因 test=77% 新造 78%/75% 等新线。

### A3 结果（TBD）

TBD

---

## A4. 跨域定位

**问题**：为什么 Caltech test FAIL 而 JPL current-only test PASS？

**纪律**：Caltech measured-pilot main ≠ JPL current-only（分开报告，不平均）；
office001 仅 descriptive external-only，不参与调规则。

### A4 结果（TBD）

TBD

---

## A5. Support-domain 候选假设

**问题**：哪些 EVSE-online-observable 条件与 PASS/FAIL 域相关？

**方法**：固定分桶 / 单变量或少量预定义组合，比较各桶 E1 evidence strength /
E3 opportunity strength / baseline elimination。

**禁止**：不训练 classifier；不宣称 support rule 已验证；只产下一阶段假设。

### A5 结果（TBD）

TBD

---

## 最终 R1 决策（预冻结 A/B/C，审查结论33）

| 选项 | 含义 |
|---|---|
| **A. Narrow GO / D1-P** | 机会真实存在但明显域依赖；扩展审计能找到由 EVSE 在线可观测变量描述的合理 support-domain 假设；支持域内保留 bounded correction，域外必须 protective fallback。后续仍需新独立数据验证 support rule。 |
| **B. Protective-only GO** | 主动候选修正跨域不稳定，或简单基线已解决绝大部分问题；但 recent actual/current-history protective boundary 在 JPL 等域表现稳定。放弃主动 redistribution/广义 executable correction，专利中心缩到 protective execution boundary + fallback。 |
| **C. NO-GO** | 扩展后仍显示机会高度稀疏/高度集中、简单 A2/A3 基线基本解决问题，同时无法提出一个仅依赖在线可观测变量且有工程合理性的 support-domain 假设；此时停止 D1-R/D1-P 继续投入。 |

### 最终判定（TBD）

TBD
