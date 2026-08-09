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

人口收缩直接发生在 sample-layer/match-status 层：10,528 = 155 L1_strict_matched +
10,373 L0_static_extension(static_only)。**仅凭 A1 无法判定运营域是否同时发生变化。**

**完整 funnel**：

| stage | n | unit |
|---|---|---|
| temporal_test_main | 10,528 | session |
| l1_strict_matched | 155 | session |
| valid_cycles | 4,920 | cycle |
| candidate_cycles_A2 | 63 | cycle |

candidate/valid cycle rate = 63/4,920 = 1.28%。

155 sessions 仅分布在 2020-05、06、07、08、11 五个月：
| 月份 | n | field_mode |
|---|---|---|
| 2020-05 | 9 | measured_pilot |
| 2020-06 | 35 | measured_pilot(34) + current_only(1) |
| 2020-07 | 35 | measured_pilot |
| 2020-08 | 7 | measured_pilot |
| 2020-11 | 69 | measured_pilot |

- 154 measured_pilot + 1 current_only（current_only 在 2020-06，非 11）。
- top stations：2-39-81-4550(23) / 2-39-139-28(22) / 2-39-125-21(14) / 2-39-131-30(13)。
- E1 core-eligible 在 155 上再收缩到 40 会话；E3 valid cycles 4,920 → A2 candidate 63。

**解读**：155 是真实后期 matched 域，但母体极小（1.47% retention）；收缩主因是 strict-match
要求（API×static matched availability），不是数据被不当删除。**结果与 support-domain limitation
假设一致，并增强了继续检查该假设的必要性；尚不足以证明存在可由在线可观测量识别的 support domain。**

输出文件：`results/raw/E3F_expansion/a1_*.csv` + `a1_population_bridge.csv` + `a1_population_bridge.json`

---

## A2. E1 + E3 Frozen-test Decomposition

**问题**：E1 11 事件全在 2020-06 + E3 5 机会月但 79.5% 集中——是否指向同一狭窄运行状态？

**切片**：month / station / day / field_mode / concurrency_bucket / connected_elapsed_bucket
（只切片已冻结结果，不重跑、不调参、不改事件/candidate 定义）

### A2 结果

**E1 与 E3 主导集中时段不同，但存在部分时间/站点/会话重叠。**

#### E1 核心 11 事件

| 月份 | n_events | gap_energy_kwh |
|---|---|---|
| 2020-06 | 11 | 3.224 |

- **100% 集中在 2020-06**，10/11 在单桩 `2-39-79-382`，1/11 在 `2-39-89-25`。

#### E3 Caltech test opp（A2 主基线）

| 月份 | n_opp_cycles | opp_energy_kwh | energy_share |
|---|---|---|---|
| 2020-05 | 3 | 0.320 | 2.5% |
| 2020-06 | 8 | 0.686 | 5.3% |
| 2020-07 | 13 | 1.440 | 11.1% |
| 2020-08 | 3 | 0.199 | 1.5% |
| **2020-11** | **36** | **10.268** | **79.5%** |

- opp energy **79.5% 集中在 2020-11**（36 周期 / 10.27 kWh）。
- M2 daily energy share median = 0.0：63 opp cycles 分布在多 day，多数 day candidate energy
  为 0 或极小，中位数为 0（evaluable-day K1 exact 口径真实零）。

#### E1/E3 overlap（month + station + session）

| 维度 | E1 核心 | E3 opp | shared |
|---|---|---|---|
| months | {2020-06} | {2020-05,06,07,08,11} | {2020-06} |
| stations | {2-39-79-382, 2-39-89-25} | 含 2-39-79-382, 2-39-89-25 | **{2-39-79-382, 2-39-89-25}** |
| sessions | 11 core sessions | E3 opp cycle 时段 sessions | **1 shared session**（`2_39_79_382_2020-06-08`）|

- E1 核心桩 `2-39-79-382` **确实贡献 E3 opportunity**（in_e3_opp=True）。
- E1 核心与 E3 opp 共享 **1 个 session**（2020-06-08 的会话同时出现在 E1 核心事件和 E3 opp 周期时段）。

**解读**：E1 核心事件主导峰在 2020-06（gap energy 100%），E3 opp energy 主导峰在 2020-11
（79.5%）；两者主导集中时段不同，但存在部分时间重叠（shared 2020-06）、共享站点（2-39-79-382）、
甚至 1 个 shared session。**目前不能声称统计独立或成因独立。** 结果与 support-domain
limitation 假设一致，并增强了继续检查该假设的必要性；**尚不足以证明存在可由在线可观测变量
识别的 support domain**（那是 A4/A5 的任务）。

输出文件：`results/raw/E3F_expansion/a2_e1_decomposition.csv` + `a2_e3_decomposition.csv`
+ `a2_overlap.json` + `a2_e3_opp_by_{month,day,concurrency,elapsed}.csv`

---

## A3. 强简单基线压力审计

**问题**：A2/A3 elimination 77%（test）是孤立值，还是后期/某类场景普遍逼近或超过 80%？

**禁止**：不改 80% 止损线；不因 test=77% 新造 78%/75% 等新线。

### A3 结果

**问题**：A2/A3 elimination 77%（test）是孤立值，还是后期/某类场景普遍逼近或超过 80%？

**结论**：test 域 A2/A3 elimination 确实从 train/val 的 ~52-54%/~22-26% 大幅上升到
77%/63%，但 **未越过冻结的 80% STOP_COMPLEX_MODEL 线**。test 的上升伴随 top_month_share
从 train 15% → val 25% → **test 79.5%**，说明基线压力上升与机会高度集中同步。
JPL 无 A0 参照（current-only 无 pilot），但 top_month_share 也从 train 13% → test 47%。

#### Caltech (E3-M)

| split | n_valid | n_cand_A2 | elim_A2_vs_A0 | elim_A3_vs_A0 | top_month_share |
|---|---|---|---|---|---|
| train | 79,816 | 16,898 | 54.1% | 25.7% | 15.1% |
| validation | 33,003 | 6,557 | 51.9% | 21.7% | 24.7% |
| **test** | **4,920** | **63** | **77.0%** | **63.1%** | **79.5%** |

#### JPL current-only (E3-X)

| split | n_valid | n_cand_A2 | top_month_share |
|---|---|---|---|
| train | 56,429 | 22,196 | 13.1% |
| validation | 21,340 | 7,698 | 31.7% |
| test | 12,722 | 3,532 | 47.2% |

- A2 candidate rate（cand/valid）：caltech train 21.2% → test **1.28%**；
  jpl train 39.3% → test 27.8%（JPL 衰退温和）。
- station exposure（仅 caltech，diagnostic 不可加总 energy）：输出 `a3_caltech_*_station_exposure.csv`。

**解读**：复杂 executable-interval 模型价值空间在 test 域确实大幅收缩（A2 elimination 77%
逼近 80% 止损线，A3 elimination 63%），但尚未越过冻结线。test 域同时存在极端集中
（79.5% opp energy 在单月）。这不改变"broad active D1-R 不应恢复"的判断，但为
A4 support-domain 检查提供了基线压力背景。

输出文件：`results/raw/E3F_expansion/a3_*_by_month.csv` + `a3_*_station_exposure.csv`
+ `a3_baseline_pressure.json`

---

## A4. 跨域定位

**问题**：为什么 Caltech test FAIL 而 JPL current-only test PASS？

**纪律**：Caltech measured-pilot main ≠ JPL current-only（分开报告，不平均）；
office001 仅 descriptive external-only，不参与调规则。

### A4 结果

**设计**：同 n_active bucket 内 candidate=True vs candidate=False 对照（不把 candidate
定义的结构条件误当 support predictor）；在线可观测量 n_active / median_elapsed /
median_actual_kw / std_actual_kw / pilot_coverage / pilot_actual_ratio；
train/val/test 方向一致性检查（仅 consistent 的才值得进 A5）。

#### 方向一致（train/val/test 同 bucket 同 observable）的在线可观测量

**Caltech**：

| concurrency bucket | consistent observables |
|---|---|
| 4-7 | n_active: true>false；median_elapsed: true<false |
| 8-15 | median_elapsed: true>false；median_actual_kw: true<false；pilot_actual_ratio: true>false |
| 16+ | n_active: true>false；median_actual_kw: true<false；std_actual_kw: true<false；pilot_actual_ratio: true>false |

**JPL current-only**：

| concurrency bucket | consistent observables |
|---|---|
| 4-7 | n_active: true>false；std_actual_kw: true>false |
| 8-15 | median_elapsed: true>false；median_actual_kw: true<false；std_actual_kw: true>false |
| 16+ | n_active: true>false |

#### 关键发现

1. **median_actual_kw: true<false** 在 caltech 8-15/16+ 和 jpl 8-15 **跨域一致**：
   candidate=True 的周期 median actual power **低于** candidate=False。
   方向合理：低 actual → budget gap (slack) 大 → candidate 成立。
   这是 candidate 定义的自然推论（slack = budget - actual），但跨域一致值得记录。

2. **median_elapsed: true<false** 在 caltech 8-15 + jpl 8-15 一致：
   candidate=True 的周期 connected-elapsed 更短（早期充电阶段）。

3. **pilot_actual_ratio: true>false** 在 caltech 8-15/16+ 一致但 JPL 无此变量
   （current-only 无 pilot）→ 仅 measured-pilot 域可用。

4. **bucket=1（n_active=1）全 nan**：candidate 定义要求 n_active≥2，bucket=1 无
   candidate=True → 无法对照（符合预期，验证对照组设计正确）。

5. **bucket=2-3 无 consistent**：63 个 test candidate cycles 全在 2-3，但 train/val/test
   方向在此 bucket 不一致 → **2-3 并发本身不能直接当 support-domain predictor**。

**解读**：存在少量跨域方向一致的在线可观测量（median_actual_kw、median_elapsed），
但它们大多直接源于 candidate 定义（slack = budget - actual → 低 actual → candidate）。
**目前不足以构成独立的 support-domain hypothesis**——需要 A5 进一步检查这些变量在
"train 强 + val 强 + test 也与失败域不同"的条件下是否仍有选择性。
test 只产假设，不训练 classifier，不宣称已验证。

输出文件：`results/raw/E3F_expansion/a4_*_bucket_comparison.csv`
+ `a4_cross_domain.json`

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
