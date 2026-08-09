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

## 8. 结果（TBD — test 冻结后填入）

### 8.1 Caltech 主门（逐 split）

| split | M1 CI 下界 | M2 能量占比 | M3 消除 | M4 月数 | all_pass |
|---|---|---|---|---|---|
| train | TBD | TBD | TBD | TBD | TBD |
| validation | TBD | TBD | TBD | TBD | TBD |
| test | TBD | TBD | TBD | TBD | TBD |

### 8.2 JPL current-only 跨池佐证门（逐 split）

| split | X1 能量占比 | X2 月数 | X3 唯一性 | all_pass |
|---|---|---|---|---|
| train | TBD | TBD | TBD | TBD |
| validation | TBD | TBD | TBD | TBD |
| test | TBD | TBD | TBD | TBD |

### 8.3 evaluable-day 覆盖

| 轨 | split | n_operating | n_evaluable | coverage |
|---|---|---|---|---|
| E3-M | train | TBD | TBD | TBD |
| E3-M | validation | TBD | TBD | TBD |
| E3-M | test | TBD | TBD | TBD |
| E3-X | train | TBD | TBD | TBD |
| E3-X | validation | TBD | TBD | TBD |
| E3-X | test | TBD | TBD | TBD |

### 8.4 正式判定（test split）

| 字段 | 值 |
|---|---|
| primary | TBD |
| main_review_required | TBD |
| cross_pool_review_required | TBD |
| exit_code | TBD |
| provenance (code_sha) | TBD |
| provenance (worktree_clean) | TBD |

### 8.5 concentration diagnostic（仅 review evidence，非门）

| 轨 | split | top_month_share | top_day_share |
|---|---|---|---|
| E3-M | train | TBD | TBD |
| E3-M | validation | TBD | TBD |
| E3-M | test | TBD | TBD |
| E3-X | train | TBD | TBD |
| E3-X | validation | TBD | TBD |
| E3-X | test | TBD | TBD |

## 9. 术语纪律

- 只称"预算差值 / 并发候选修正窗口"；不称"可回收能力 / 命令失败 / 拒绝 / 可吸收余量"。
- R1-E3 仍是候选预算修正窗口审计；E2 可执行功率区间未获准启动，本报告不提前主张 E2→重分配链条。
