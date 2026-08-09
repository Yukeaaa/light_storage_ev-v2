# R1-E3 Gate（候选预算修正窗口 / 机会审计）

> 审查结论28/29 定稿。本报告方法/门/决策矩阵在正式 test 暴露前冻结；结果区域 TBD，
> 待 `--formal-test` 执行后填入（test 只跑一次，冻结后只读）。
>
> 预注册配置：`configs/r1_e3.yaml`（独立，不修改已被 D0 冻结的 `e0_full.yaml`；
> 停止线/种子引用 `e0_full.yaml#k1_replication_stop_lines.e3` / `#seeds`）。

## 1. 人口（双轨，审查结论28 定稿）

| 轨 | 定义 | site/garage | 期望计数 (total/train/val/test) |
|---|---|---|---|
| E3-M Caltech 主门 | `L1_strict_matched ∧ role==main ∧ split∈{train,val,test}` | caltech / California_Garage_01 | 13,477 / 9,426 / 3,896 / 155 |
| E3-X JPL current-only 跨池佐证 | `L1_strict_matched ∧ role==current_only_fallback ∧ field_mode==current_only ∧ split∈{train,val,test}` | jpl / Arroyo_Garage_01 | 20,925 / 13,908 / 5,026 / 1,991 |

- E3-X 必须额外要求 `field_mode==current_only`：同 role 内含 163 个 measured_pilot（全在 test；另 42 个在 stress 不进主切分），不能把整个 role 当 current-only 池。
- 两轨都用 E0F-02 已冻结的站点内 60/20/20 时间切分；整会话不跨 split。

## 2. 方法（沿用 K1 E3-Lite 冻结管线）

- 连续时间历史：每会话补齐 5min 网格，组内 `(session, run)` `shift(1)/rolling`；5min 网格断档冷启动。
- 指标 A = 并发候选修正窗口（`n_slack≥1 ∧ n_active≥2`，预算差值，**无吸收假设**）。
- 主门基线 = `A2_prev_actual`（候选量最低的预注册可执行简单基线），两池一致。
- 代理集：caltech `[A0_avg, A2, A3]`；jpl current-only `[A2, A3]`（A1/A4 非门所需不进 R1）。
- 精确配对 `eligible_mask`（会话×周期层代理交集，所有代理同一会话集合）。
- meta 只合 cycle 纯函数字段（month/day）；候选表 `[site,garage,cycle]` 唯一（month_conn fan-out 债务已关闭）。

## 3. 门结构（逐 split）

### E3-M Caltech 主门

| 门 | 阈值 | 说明 |
|---|---|---|
| M1 | A2 日等权候选率 CI 下界 ≥ 1% | 日 cluster bootstrap 95%CI |
| M2 | 日候选能量占比中位 ≥ 0.5% | evaluable-day 口径（见 §5） |
| M3 | A2/A3 消除 ≤ 80% | 超限 = 复杂模型止损，优先级②单独判定 |
| M4 | `n_months_with_opp ≥ 2` | hard gate；`top_month/top_day` 仅 diagnostic，不造 outlier cutoff |

### E3-X JPL current-only 跨池佐证门

| 门 | 阈值 | 说明 |
|---|---|---|
| X1 | 日候选能量占比中位 ≥ 0.5% | evaluable-day 口径 |
| X2 | `n_months_with_opp ≥ 2` | 非单月 |
| X3 | `n_dup_cycles == 0` | 候选表唯一性 |

不作率 CI 新硬门槛（JPL 仅跨池佐证）。

### Cross-pool 门

caltech 能量占比 ∧ jpl 能量占比各自 ≥ 0.5%。

## 4. 正式判定优先级（test split）

| 优先级 | 条件 | 判定 |
|---|---|---|
| ① | 数据/唯一性/provenance FAIL | HARD STOP（runner 抛异常） |
| ② | A2/A3 消除 > 80% | STOP_COMPLEX_MODEL |
| ③ | Caltech test 主门 FAIL | FORMAL_FAIL_MAIN（JPL 不得 rescue） |
| ④ | Caltech PASS 但 cross-pool FAIL | FORMAL_FAIL_CROSS_POOL |
| ⑤ | 全部满足 | E3_PASS |

### review_required（审查结论29 NB-1）

- `main_review_required`：Caltech train/val PASS 而 test 主门 FAIL。
- `cross_pool_review_required`：双轨 train/val + cross-pool 全 PASS 而 test FAIL。
- JPL train 已 FAIL → `cross_pool_review_required` 不触发（不误标标准情况二）。

## 5. evaluable-day 口径（审查结论30 P0-2；与 K1 e3_lite exact 同源）

- evaluable day = candidate table 里出现的 day（至少有 1 个 valid/eligible paired cycle；含 `candidate=False` 行）。
- **evaluable + 当日全 `candidate=False` → share=0 是真实零效果，进入 median**（case A）。
- 一天连一个 valid paired cycle 都没有 → non-evaluable，**不以 0 进入 median**（case B；non-evaluable ≠ real zero，与 E0 evaluable 汇总层原则一致）。
- 报告：`n_operating_days` / `n_evaluable_days` / `n_non_evaluable_days` / `evaluable_day_coverage`。
- 与 K1 E3-Lite `e3_lite/run.py` daily energy section exact 同源（`cd.groupby(["pool","day"])[col].sum()`，`cd` 含 `candidate=False` 行）。

## 6. runner 治理（审查结论29 P0-1/P0-2/P0-3）

```
--pretest              train+validation → results/work/E3F_pretest/（禁加载 test）
--formal-test          验证 pretest manifest
  --expected-code-sha <最终 code-only SHA>
  [--require-clean]    默认 true
                       → clean/SHA hard gate
                       → 写 started sentinel（读取任何 test outcome 之前）
                       → Caltech test + JPL test 一次
                       → results/raw/E3F/
                       → seal completed
--read-frozen          只读冻结门（不重算/写盘）
```

- once-only 状态机：absent → started → completed；`started` 后即使崩溃也不自动获第二次 test。
- clean/SHA hard gate：`code_sha != unknown ∧ == expected ∧ worktree_clean`。

## 7. fail-case 规则（审查结论29 NB-3）

- 组合：top positive candidate windows + high-concurrency no-candidate / baseline-missed。
- 目标 ≥ 20；若整个 split valid cycles < 20 → `insufficient_failure_cases=true`（进 review）。

## 8. 结果（frozen formal test；evidence-only commit `310cbdb`，审查结论33 冻结）

> formal test 已永久封存（`state=completed`，`formal_test_exposure=c1436f4…`）；
> 重跑被 `assert_formal_test_not_started_or_exposed` 硬拒。
> train/validation 从 frozen pretest manifest 嵌入（未重算），
> `pretest_summary_sha256=0aeb340f4cba80324ebc2d463433de16efffd1e55e48694e5da2e1f9942ab56e`。

### 8.1 Caltech 主门（逐 split）

| split | M1 CI 下界 | M2 能量占比 | M3 消除 | M4 月数 | all_pass |
|---|---|---|---|---|---|
| train | 0.2018 | 0.0413 | 0.5407 | 10 | True |
| validation | 0.1680 | 0.0378 | 0.5190 | 6 | True |
| test | **0.0052** | **0.0** | 0.7701 | 5 | **False** |

### 8.2 JPL current-only 跨池佐证门（逐 split）

| split | X1 能量占比 | X2 月数 | X3 唯一性 | all_pass |
|---|---|---|---|---|
| train | 0.0378 | 10 | 0 | True |
| validation | 0.0372 | 5 | 0 | True |
| test | 0.0270 | 4 | 0 | True |

### 8.3 evaluable-day 覆盖

| 轨 | split | n_operating | n_evaluable | coverage |
|---|---|---|---|---|
| E3-M | train | 298 | 297 | 0.9966 |
| E3-M | validation | 157 | 161 | 1.0255 |
| E3-M | test | 59 | 60 | 1.0169 |
| E3-X | train | 299 | 300 | 1.0033 |
| E3-X | validation | 107 | 107 | 1.0 |
| E3-X | test | 72 | 76 | 1.0556 |

> **caveat（审查结论32/33）**：`evaluable_day_coverage` 可 >1，因为 numerator
> （有 valid paired cycle 的日期）与 denominator（EV 能量>0 的日期）定义不同；
> "存在 valid cycles 但当日总能量=0"的日期计 evaluable 不计 operating。
> 这是当前诊断字段的命名/denominator debt，**不是概率意义上的覆盖率**，
> 不污染 M2（零能量日不可能产生正 candidate energy）。冻结 evidence 数值不改。

### 8.4 正式判定（test split）

| 字段 | 值 |
|---|---|
| primary | **FORMAL_FAIL_MAIN** |
| main_review_required | True |
| cross_pool_review_required | True |
| exit_code | 1（fail-closed） |
| provenance (code_sha) | `c1436f43e0feba8ac072beac0cb03c851eda2c05` |
| provenance (pre_run worktree_clean) | True |
| formal_test_exposure | `c1436f4…` |
| pretest_summary_sha256 | `0aeb340f4cba80324ebc2d463433de16efffd1e55e48694e5da2e1f9942ab56e` |

**判定理由**：Caltech test 主门失败（M1 CI 下界 0.0052<0.01、M2 能量占比 0.0<0.5%，
JPL 不得 rescue）；train/val PASS 而 test FAIL → 情况二 main/cross-pool review。

**关键解读（审查结论33）**：M2=0 不是单纯"155 会话样本小"可解释——candidate energy
非负，日中位数为 0 意味着至少约一半 evaluable days 的 A2 candidate energy 为 0；
配合 top_month_share=0.795，表明 Caltech 后期 hard-test 域出现明显的时域/支持域失配。
M3=0.7701 虽未越 80% 止损线，但已从 train/val 的 ~52-54% 上升至 test 的 77%，
复杂模型价值空间在 test 域已逼近预注册止损边界。

### 8.5 concentration diagnostic（仅 review evidence，非门）

| 轨 | split | top_month_share | top_day_share |
|---|---|---|---|
| E3-M | train | 0.1511 | 0.0120 |
| E3-M | validation | 0.2469 | 0.0152 |
| E3-M | test | **0.7952** | 0.2740 |
| E3-X | train | 0.1311 | 0.0090 |
| E3-X | validation | 0.3172 | 0.0224 |
| E3-X | test | 0.4722 | 0.0485 |

### 8.6 cross-pool 门（逐 split）

| split | energy_share_each_pool_pass |
|---|---|
| train | True |
| validation | True |
| test | **False**（Caltech M2 拖累） |

### 8.7 fail_cases（AGENTS.md 每实验 ≥20）

| 轨 | split | n_fail_cases | insufficient_failure_cases |
|---|---|---|---|
| E3-M | train | 20 | False |
| E3-M | validation | 20 | False |
| E3-M | test | 20 | False |
| E3-X | train | 20 | False |
| E3-X | validation | 20 | False |
| E3-X | test | 20 | False |

## 9. 术语纪律

- 只称"预算差值 / 并发候选修正窗口"；不称"可回收能力 / 命令失败 / 拒绝 / 可吸收余量"。
- R1-E3 仍是候选预算修正窗口审计；E2 可执行功率区间未获准启动，本报告不提前主张 E2→重分配链条。

## 10. E3 decision log

| 审查结论 | 判定 | 关键 |
|---|---|---|
| 28 | 双轨人口/分层门定稿 | E3-M caltech main / E3-X jpl current_only；JPL 不得 rescue Caltech |
| 29 | code-only baseline 未批准（4 blocker） | once-only/evaluable-day/transaction/clean gate |
| 30 | pretest readiness FAIL（5 blocker） | pretest 读 test / evaluable-day 口径错 / manifest 不绑定 / CLI bypass |
| 31 | code-only baseline PASS | `c1436f4…` 冻结为最终 E3 code-only baseline；批准 pretest |
| 32 | pretest PASS；批准一次 formal test | pretest_summary_sha256=`0aeb340f…ab56e` 审阅绑定 |
| 33 | formal execution/governance PASS；scientific gate FORMAL_FAIL_MAIN；R1 仍 NOT PASS | M2=0 + top_month=0.795 非单纯样本小；M3=0.77 逼近止损；广义 D1-R 暂定 No-Go，D1-P 升首要 |

### 正式结论（审查结论33 冻结）

- **E3 formal test**：有效 FAIL，不豁免，永久冻结（禁止重跑）。
- **E3 evidence/governance**：PASS。
- **R1 整体**：仍 FAIL / NOT APPROVED，进入最后一次 narrowing review。
- **允许**：§10.2 扩展审计（population bridge / post-hoc decomposition / 强基线压力 / 跨域定位 / support-domain 候选变量诊断；只用 test 产假设，不用 test 优化 rule）。
- **禁止**：E1-Full、E2、E4、formal test rerun、阈值/人口后改。
- **路线调整**：广义主动 D1-R 暂定 No-Go；D1-P（support-domain + protective fallback）升为首要候选。
- **最终 R1 决策预冻结**：A. Narrow GO / D1-P；B. Protective-only GO；C. NO-GO。
