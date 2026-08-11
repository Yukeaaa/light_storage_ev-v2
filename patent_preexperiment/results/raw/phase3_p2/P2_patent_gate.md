# P2 Patent Gate — 正式判定：SUCCESS / NARROW GO（P2 formal frozen outcome 判门，非重算）

> 日期：2026-08-11
> 依据：P2 formal test 单次冻结 exposure（`results/raw/phase3_p2/p2_test_summary.json` /
> `p2_test_sentinel.json` / `p2_manifest.json` / `p2_test_traces.parquet`）+ Step0 预暴露
> artifact（`p2_step0_summary.json` SHA256=`1c941845...`，已原样归档）。判门口径 = 冻结
> 协议 `phase3_p2_preregistration_v1.0.2 §6`（字段 6 Success/Conditional/No-Go），
> **不是** `exit_code`（见 §5）。
> 本记录是专利撰写层输入；本记录不是法律意见，正式申请前由专利代理师出具法律检索与权利要求意见。

## 1. Exposure 与 provenance（once-only）

```text
code_sha                    0bca5f2ae57f1eec9d3d39439676ebca1fe84079
worktree_clean              true
step0_summary_sha256        1c9418458fe90976fc78883f20903393fb09a352b2ac217a69ad59866b01843d
sentinel.status             completed
sentinel.exposed_sha        0bca5f2ae57f1eec9d3d39439676ebca1fe84079
once_only                   true
exit_code                   0（仅表示 step0_verdict==PROCEED，见 §5，不作为 formal verdict）
```

- 正式 rerun：**PERMANENTLY PROHIBITED**（sentinel 已存在，任何 status 均视为 consumed）。
- test 池只做 natural（replay 是 train-side 机制证据，非 test outcome）。
- 判定来源：**冻结结果判门**（对照 §6 映射，未重算、未逐图调参）。

## 2. Formal test 冻结结果（原样，未做任何 post-hoc 分析）

### 2.1 Step0 kill gates（JPL train natural + 固定 Caltech replay）

```text
K1（D1 信息类别 → boundary mode）    PASS（precedence 穷尽查表确定性）
K2（D2 权限等级 → accept/clip）      PASS（硬杀线通过）
K3（D3 响应驱动 natural recovery）   PASS（JPL train natural complete traces = 5,677）
step0_verdict                        PROCEED
```

### 2.2 jpl_test_current_only（主口径：约 90% 文件 current-only）

```text
sessions                  2,215
cycles                    899,889
mode_counts               M3_current_only 888,794 / M4_history_insufficient 11,095
M1 = 1.0                  D1 查表唯一性（全 cycle 唯一 info_mode/boundary_mode）
M2 = 1.0                  final_delta == clip(requested, L, U)，disposition 一致
m2_disp_ok = 1.0
m2_cov = 0.376743         37.7% 数值 cycle 的 clip 实际生效（requested != final）
M4 = 0.0                  PROTECTIVE cycle 中 final_delta>0 的比例 = 0（无 unsupported release）
n_diff_lock_prot = 359,971 LOCKED vs PROTECTIVE 动作不同的 cycle
n_diff_prot_normal = 72,067 PROTECTIVE vs NORMAL 动作不同的 cycle
release_violations = 0
boundary_unavailable = 20
M3 natural recovery：complete traces = 1,060（sessions = 1,060）
```

### 2.3 caltech_test_measured_pilot（M2 分支：pilot 实测）

```text
sessions（matched 严格子集）  154（registry 全量 10,527，其余 10,373 为 static_only/L0）
cycles                       32,714
mode_counts                  M2_pilot_actual 31,934 / M4_history_insufficient 780
M3 traces                    0（M2 分支无 current-only 段，符合预期，不计入 natural）
```

### 2.4 caltech_test_current_only（L0 传感器降级 stress）

```text
sessions                    1
cycles                      426
mode_counts                 M3_current_only 421 / M4_history_insufficient 5
M3 natural recovery         complete = 1（1 session）
```

### 2.5 test 池合计

```text
traces total               2,217
traces complete            1,061
```

## 3. 判门（字段 6 映射）→ **SUCCESS**

| §6 条件 | 冻结数值 | 判定 |
|---|---|---|
| K1/K2/K3 全过 | 全 PASS | ✓ |
| M1=1.0 / M2=1.0 / M4=0.0 | 1.0 / 1.0 / 0.0 | ✓ |
| M3 natural JPL ≥ 20 traces / ≥ 5 sessions | 1,060 / 1,060 | ✓（超门槛 ~50×） |
| before/after 动作集变化全部记录 | trace 记录 before/after allowed L/U | ✓ |
| 后续命令被新区间约束的实例 ≥ 1 且可观察 | complete trace 定义含 after_diff；jpl test n_diff_prot_normal=72,067 | ✓ |

**结论：P2 = SUCCESS → NARROW GO**（`phase3_p2_preregistration_v1.0.2 §6` 穷尽映射
"其余全过 → Success（NARROW GO 成立，进入 Claim v2 撰写）"）。

> 最担心的退化场景被排除：**不是**"只是 state 从 PROTECTIVE 改成 NORMAL、实际控制什么都没变"。
> NORMAL 与 PROTECTIVE 在 72,067 cycle 上产生不同的最终动作（同一外生 probe 下），且 1,060 条
> complete trace 的 after_diff 逐条记录；37.7% 的 candidate action 确实被 clip。

## 4. 判定含义（冻结，不改写）

### 4.1 什么被证明了（自然的部分）

```text
actual charging response
  ↓（历史不足）M4 LOCKED，不输出未支持区间
  ↓（历史足够）M3 history_protective_boundary（Q95, shift(1) 因果化）
  ↓ application_state = PROTECTIVE（仅允许收缩预算，禁止释放差值）
  ↓ actual 贴近边界（>= 0.95×boundary，连续 3 cycle）
  ↓ application_state = NORMAL（boundary_mode 不变，预算修正允许区间扩大）
  ↓ 后续预算修正按新区间执行（after_diff 可观察）
```

在 JPL **自然数据**中，该闭环在 1,060 个不同会话中完整出现；PROTECTIVE 段（9,744 cycle，
jpl test）**未出现**任何正向 unsupported release。**D3 不是为专利硬造出来的罕见状态。**

### 4.2 什么没有被证明（合成的部分，不得跨过）

```text
current_budget / requested_delta 是冻结的外生 controller-conformance probes
（ACN 数据无真实 EMS budget/request；v1.0.2 §7 禁止按 [L,U] 反推）。
```

因此 P2 证明的是：

> **如果 EMS 有一个待执行的预算修正请求，该 gate 可以依据自然车辆响应改变其允许范围，
> 且这种允许范围变化在大量真实会话中具有实际动作差异。**

P2 **没有**证明（明确边界）：

- 真实 JPL EMS 当时真的发出了这些 +1.5/+3kW 请求；
- 使用该 gate 后站级收益更好（闭环收益需 E4.1 响应仿真器验证，见术语纪律）；
- 站级预算跟踪残差改善（D1-R 主指标链后续才可评估）。

### 4.3 对专利 Claim 的影响（D1/D2/D3 状态升级）

```text
P-001（信息类别 → 边界生成方式）      D → C
P-002（边界 → 预算修正允许区间）      D → C（controller mechanism，非效果声明）
P-003（实际响应 → 权限恢复）          → C（STRONGLY SUPPORTED by natural traces）

Broad active D1                      NO-GO（维持）
recent_var state center              NO-GO（维持）
PV/BESS benefit / 站级收益           未验证（维持 D/禁止外推）
```

## 5. exit_code 口径纠正（冻结）

- `exit_code=0` **只**表示 `step0_verdict == PROCEED`（`p2_exit_code` 未参与 M1/M2/M3/M4
  或 Success 计算）。
- 因此**不得**写"exit_code=0 → formal PASS"。
- 正确表述：**formal frozen outcome 按 `phase3_p2_preregistration_v1.0.2 §6` 映射为
  Success**。这是对冻结结果的一次判门，不是重算实验。

## 6. 项目状态表（冻结）

```text
Broad active D1                          NO-GO
recent_var state center                  NO-GO
Patent Gate 2                            NARROW CONDITIONAL GO（prior-art 层）
P2 formal frozen outcome                 SUCCESS（§6 判门）
P2 route                                 NARROW GO
    └ D1 information-mode 分级选择        SUPPORTED, narrow（M1=1.0；K1 PASS）
    └ D2 budget-action gate              SUPPORTED as controller mechanism（K2/M2；clip 生效）
    └ D3 response recovery               STRONGLY SUPPORTED（natural 1,060 会话）
P2 rerun                                 PERMANENTLY PROHIBITED
P3                                       HOLD（不自动开，见 §7）
Next                                     Claim v2 撰写 + ACN element-by-element 对照
                                         （本记录 + claim_tree.md §6.x 更新）
```

## 7. 后续动作（不自动加码实验）

1. **Claim Surgery v2**：把 CLAIM 1 写成可执行设备动作链（preregistration §9 靶子），
   删除所有 P2 未验证的夸大措辞（站级收益、真实 EMS 请求、replay 作为 natural）；
2. **ACN element-by-element 对照**：对 US10926659 / US20200254896A1（同数据源最近邻）
   逐条映射 D1/D2/D3，确认区别落在"信息类别分级选择 + 预算修正动作权限 + 实测响应驱动恢复"；
3. **P3 保持 HOLD**：当前窄组合证据充分，不因 P2 成功自动增加实验；新增实验需新授权 + 新协议版本。

## 8. 证据链与归档

```text
results/raw/phase3_p2/p2_step0_summary.json   （预暴露 artifact，SHA=1c941845...，原样归档）
results/raw/phase3_p2/p2_step0_report.md      （同步归档）
results/raw/phase3_p2/p2_test_summary.json    （formal 冻结结果，含 K1/K2/K3 与关键数值副本）
results/raw/phase3_p2/p2_test_sentinel.json   （sentinel=completed，exposed_sha 记录）
results/raw/phase3_p2/p2_manifest.json        （once_only=true，step0 sha256 闭环）
results/raw/phase3_p2/p2_test_traces.parquet  （2,217 条 trace，1,061 complete）
```
