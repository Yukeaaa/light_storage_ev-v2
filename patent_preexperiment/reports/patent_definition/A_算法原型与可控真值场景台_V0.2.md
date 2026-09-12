# A 算法原型与可控真值场景台 V0.2（pre-freeze 修订）

- 日期：2026-09-12
- 状态：**A-EV V0.2 PRE-FREEZE = CLOSED（软件侧）**
- 前序：`A_算法原型与可控真值场景台_V0.1.md`（V0.1 主体）；本版按 2026-09-12 外部评审（9 项 pre-freeze 要求 + 复核 blocker）完成修订并经复核确认。
- 提交：`98d20d0`（V0.2 评审 9 项落实）→ 本版（锁闭环 blocker + S9 + 治理收尾）。
- **口径声明（不变）**：本场景台全部产出为**合成场景机制验证，非效果结论**；阈值数值仍为**候选值**（产生规则已冻结，设备相关数值待 HIL commissioning 落定加锁）。**A-M3–M6 = UNVALIDATED、Round 5 = NOT STARTED、core-patent = NO-GO 均不因本报告改变**。

---

## 1. 评审 9 项落实对照（2026-09-12 评审 → 代码）

| # | 评审要求 | 落实位置 | 测试 |
|---|---|---|---|
| 1 | signed deviation 全链统一（`e = P_req − P_meas`） | `types.py::Deviation`（`signed`/`gap_direction`/`delivered_in_req_dir`），贯穿归因→缺口（`station_gap` 同向累加/异向相抵）→能力更新（要求方向×该方向交付水平，不再一律 `abs()`）→回写 | `test_signed_deviation_over_execution_needs_down_compensation`、`test_signed_deviation_opposite_execution_is_not_invisible` |
| 2 | `local_limit_dir` 未知不作正向证据 | `LimitDir` 拆 `UNKNOWN`/`BOTH`（不复用 0）；归因中 UNKNOWN → UNCERTAIN | `test_unknown_limit_dir_is_never_positive_evidence`、`test_both_direction_limit_counts_as_positive_evidence` |
| 3 | RESID 拆 full / steady 双指标 | `metrics.py`：`RESID_full`（事件开始→结束，含归因确认延迟全部成本）+ `RESID_steady`（预注册 `residual_window_offset_s` 之后）；PCC 残差同拆 | 评价集结果（见 §4） |
| 4 | `response_delay_s` 真实生效或删除 | `scenario.py` plant：纯延迟（输出保持）→ 一阶响应 | `test_response_delay_holds_output_before_first_order_response` |
| 5 | 阈值"产生规则"先冻结 | `thresholds.py` + 配置 `thresholds_provenance`：偏差带 = max(计量分辨率， k·σ, α·额定)（k=3.0、α=0.02 已在看结果前冻结；per-resource：R0/R1=2.0、R2=1.2）；响应窗 = p95+裕量（p95 待 commissioning） | `test_threshold_rule_is_per_resource` |
| 6 | commissioning 与正式评价分离 | 三场景集严格分离；标定集只测阶跃响应/噪声、不产效果指标；formal 阶段拒绝再跑标定 | `test_commissioning_scenarios_are_separated` |
| 7 | 主承接策略改确定性 | `contribution`（最大可承接贡献 + rid 字典序 tie-break）；weighted 仅敏感性、不进主结论 | 配置 `carrier.strategy` |
| 8 | 加 A-no-state / A-no-writeback 消融 | `baselines.py`：分别隔离【c】持久能力状态与【e】执行反馈回写 | `test_ablation_no_state_is_memoryless`、`test_ablation_no_writeback_loses_cascade`、§5 S9 |
| 9 | 稳健性矩阵预注册 | 配置预注册：方向×幅值(10/20/30%额定)×资源×repeats=5×seed=101 顺序随机化 + extra_coverage（时戳错位/模式切换/保护） | `test_robustness_matrix_respects_preregistration` |

文案修正：「四类非能力原因」已全仓清零，统一为「**四种原因，其中三种为非能力原因**」（`INJECTED_NON_CAPABILITY` 仅 COMM/TRANSIENT/EXTERNAL 三类）。

## 2. 本版新增（评审复核 blocker）：锁 → resolved thresholds → formal 强制闭环

### 2.1 评审指出的缺口

V0.2 首版"冻结机制的各零件都有，但最后一公里没闭环"：锁文件只写 `suggested_thresholds` 而正式算法仍读配置；`thresholds_locked` 手工置 true 不会触发验锁；`config_hash` 未排除治理位（切 formal 即使哈希失效）。

### 2.2 现单向链（已实现）

```text
HIL commissioning 原始结果（标定集，与评价集无交集）
        ↓  按已冻结规则计算
resolved thresholds（逐资源 band + 响应窗 + persistence_n + confirm_n）
        ↓  --freeze
V1.0 lock（.lock.json）
  - resolved_thresholds（formal 唯一阈值来源）
  - rules（thresholds_provenance 快照）
  - config_hash + calibration_data_hash + locked_at + phase_at_lock
        ↓  phase=formal 启动（每次运行强制）
① thresholds_locked=true ②锁存在 ③config_hash 匹配 ④resolved 齐备且覆盖全部资源
        ↓  任一不满足 → LockError 拒绝运行（无标量回落）
```

关键实现：

- **`resolve_thresholds()` 是阈值唯一入口**（`runner.py`）：`phase != formal` → 按预注册规则构造（允许标量回落，仅供合成回归/单测）；`phase == formal` → 只认锁内 resolved thresholds，四类硬失败（缺锁/哈希不匹配/resolved 缺失/未加锁）一律 `LockError`。runner 与 `experiments/a_ev/run.py` 两个入口 + `run_all` 内部三处一致（防御纵深）。
- **`config_hash` 剔除治理位**（`experiment.phase` / `thresholds_locked` / `locked_at` / `config_hash` / `lock`）：冻结在标定阶段完成、之后只切治理位不使锁失效；实质内容（场景/规则/算法参数）任一改动即哈希失配 → 拒绝。
- **`freeze()` 硬校验**：缺 `thresholds_provenance` 或标定未得到 p95 → 拒绝冻结；formal 阶段拒绝重新 `--freeze`、拒绝再跑标定集。
- 阈值注入贯通：`AEVPipeline` / `_StaticPolicy` 构造器与 `evaluate()` 均接受注入的 `Thresholds`，formal 运行时全部策略与指标使用**同一把锁**的数值。

### 2.3 测试

`test_config_hash_ignores_governance_flags`、`test_freeze_writes_resolved_thresholds_from_calibration`、`test_formal_uses_lock_resolved_thresholds`（证明 formal 真用锁值：R2 带 1.2 ≠ 标量 2.0）、`test_formal_refuses_missing_stale_or_tampered_lock`（四类拒绝）、`test_formal_main_entry_refuses_unlocked_run`（入口级）。

## 3. 本版新增：S9 跨事务复用（权 7 ≠ 权 1【c】/【e】的可运行区分）

**设计**（评审意见，原草稿补丁方案的正式实现）：

- **T1**（t=30–80）：R0 被持续限值（要求 +20、限制在基值 30）→ 归因确认 → R0 `up_bound` 100→30 → 缺口由 R1 承接 → T1 结束（缺口消失，corrections/事务级排除清空），但**物理限值未解除**（`clamp_persist`）且无恢复试探 → 持久能力知识保持。
- **T2**（t=110–150）：R1 出现新的独立限值制造上向缺口（+20）；R0 是唯一其他可上向承接资源。
  - 正确 A：R0 headroom = 30−30 = 0 → 不向 R0 派发，缺口如实保留 → **无二次不可执行命令**；
  - A-no-state：按额定能力估计 R0 headroom = 70 → 派发 20 kW → R0 实际无法执行 → **二次不可执行命令**。

**结果**（评价集，合成机制自检、非效果结论）：

| 策略 | S9 bad_cmd_rate | 说明 |
|---|---|---|
| A | **0.0000** | 持久能力知识阻止了向已知受限资源的重复派发 |
| A_no_state | **0.2391** | 无持久知识 → 二次不可执行命令（隔离【c】的价值） |

汇总层面 `A_no_state` 的 BADCMD 由 0 升至 0.02（加入 S9 后），完整 A 保持 0。

**答审价值**：权 7「本轮事务中的承接排除 ≠ 设备持久控制参与资格」从文本区别升级为可运行实验区别——事务级状态随缺口消失清空（`carriers/excluded` 中段为空），设备持久能力知识跨事务保持（R0 边界在 T2 内仍为 30）。

## 4. 三场景集留档（本次重跑，config_hash = 2b53a3f5…）

### evaluation（10 场景 × 6 策略）

| 策略 | EMUR | RESID_full | RESID_steady | BADCMD | cascade | 恢复时延 |
|---|---|---|---|---|---|---|
| A | 0.00 | 8.98 | 5.04 | 0.00 | 1 | 15.0 s |
| A_no_state（空真） | 0.00 | 8.98 | 5.04 | 0.02 | 2 | n/a |
| A_no_writeback | 0.00 | 8.98 | 5.04 | 0.06 | 0 | 15.0 s |
| B0_no_gate | **1.00** | 3.57 | 5.04 | 0.04 | 0 | 15.0 s |
| B1_static_derate | 0.00 | 18.75 | 18.42 | 0.00 | 0 | n/a |
| B2_error_rolling（空真） | 0.00 | 18.75 | 18.42 | 0.00 | 0 | n/a |

两窗口口径的效果（评审预期）：B0 的 RESID_full 低于 A（无归因门 → 无确认延迟成本），但 EMUR=1.00（全部为错误更新）；A 慢一步确认，换来的状态知识正确。**双指标同时汇报，不让 A 在每个指标上"赢"，只让它的代价可见、收益可归因。**

### robustness（48 条件 × 4 策略）

方向 up/down × 幅值 10/20/30% × 资源（up: R0/R1；down: R2）× 5 次重复 + 3 个 extra_coverage（时戳错位/模式切换/保护）= 48 条件，seed=101 顺序随机化。EMUR 信号集中在 3 个非能力原因的 extra_coverage 条件（A=0 vs B0 全错），幅值/方向/资源维度无机制失效。

### commissioning（标定，不评价）

p95 阶跃响应 12.0 s（R0/R1/R2）、实测噪声 σ ≈ 0.196–0.230 kW → 按预注册规则自动算出建议阈值（响应窗 12+3=15 s；带 2.0/2.0/1.2）。**此数值仍属候选**：HIL 真机标定后由 `--freeze` 重算并加锁。

## 5. 质量门

- pytest 全过（`tests/test_a_ev.py` 40 项，含本次 +7）；
- a_ev 包 ruff 0 错、mypy strict 11 文件 0 错；
- 三场景集结果文件与当前配置 `config_hash` 一致（可追溯）。

## 6. Open items 与下一步

```text
A-EV V0.2 PRE-FREEZE = CLOSED（软件侧）
  ↓
HIL adapter / commissioning（前置条件核对：HIL 可得性 / 人工 Pmax 接口 / 时钟同步 / 采集分辨率 / 真实站合作方）
  ↓
HIL calibration data（标定集运行）
  ↓
V1.0 thresholds lock（--freeze 落数值 + hash；此后不得依结果调整）
  ↓
formal A-EV（evaluation + robustness 正式跑）
```

- 本版无未决 blocker；S9 已实现并进入正式评价集。
- **任何 synthetic 数值不得进入申请文本**；结果若达"真实部署问题 + 效果证据"标准，另行提交 R5 intake gate 评估。
