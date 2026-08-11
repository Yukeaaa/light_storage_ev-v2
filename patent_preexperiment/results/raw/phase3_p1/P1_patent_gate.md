# P1 Patent Gate — 正式判定：NO-GO（机制反证，非样本不足）

> 日期：2026-08-11
> 依据：P1 formal test 单次冻结 exposure（`results/raw/phase3_p1/p1_test_summary.json` /
> `p1_test_sentinel.json` / `p1_manifest.json`），Review 65 授权、Review 63/64 状态机封口后执行。
> 本记录是 **Patent Gate 2 prior-art stress test 的检索前基线**；凡本记录冻结的排除项，
> 检索与后续 claim 撰写不得再以"看到 prior art 后绕开"的方式反向引入。

## 1. Exposure 与 provenance（once-only）

```text
code_sha                    d99a0c648980739e2a293b355189430dd3e204b8
worktree_clean              true
train_edges_sha256          650342d9d79fa934b0662b1b935d38484562c65f5be6377266ab616adc480eb8
sentinel.status             completed
sentinel.exposed_sha        d99a0c648980739e2a293b355189430dd3e204b8
once_only                   true
```

- 正式 rerun：**PERMANENTLY PROHIBITED**（sentinel 已存在，任何 status 均视为 consumed）。
- 本次为单一 office001 formal exposure；test outcome 此前零曝光。

## 2. Formal test 冻结结果（原样，未做任何 post-hoc 分析）

```text
test:
  n_sessions                215
  n_cycles                  15,954
  n_e1_core_events          70
  n_e1_event_cycles         70
  n_evaluable_cycles        15,685
  n_s3_cycles               269

S1/S2:
  n_s1 / n_s2               6,312 / 9,373
  n_e1_s1 / n_e1_s2         31 / 38
  rate_s1 / rate_s2         0.004911 / 0.004054
  rate_diff                 -0.000857
  rate_ratio                0.8254870716505542
  ratio_kind                finite

bootstrap:
  unit                      day
  seed                      20240810
  ci95                      [-0.005446, 0.003212]

quartile_direction（预注册次指标）:
  direction                 Q4>Q1
  low_label / high_label    Q1 / Q4
  rate_low / rate_high      0.000682360968952576 / 0.0025390625
  high_gt_low               true

verdict:
  verdict                   No-Go
  reason                    rate_S2=0.004054 <= rate_S1=0.004911（主方向未复现且反号）
```

## 3. 判定含义（冻结，不改写）

1. **主判据 No-Go**：冻结定义下"高 recent actual variance → 更高 E1 response-evidence
   density"在 office001 独立 formal test **未复现，且主方向反号**；day-cluster bootstrap
   95% CI `[-0.005446, 0.003212]` 含 0。
2. **Q4>Q1 不得救主判据**：quartile 方向是预注册次指标；禁止在结果后把 q50 换成 q75、
   或把 Q4/Q1 升格为主规则（post-hoc rescue 禁止，与实验阶段禁止 rescue tuning 同则）。
3. **C-007 = external formal replication FAIL**：此前 A5 的
   "higher recent actual variance → higher E1 evidence density" 只能保留为
   **Caltech exploratory observation**，不得作为跨站点一般规律，也不得支撑独立权利要求。
4. **recent_var 状态判定器 No-Go**：不得再声称"利用 recent actual variance 高低可把
   响应支持程度可靠分为 S1/S2，并据此提高/降低 EMS 控制权限"。
5. **P1 不是 Total No-Go**：P1 未验证"信息可用性/历史充分性 → 边界生成方式 → 约束等级 →
   保护降级 → 响应恢复"这条保护性架构；该架构是 **Patent Gate 2** 的检索对象。

## 4. 项目状态表（冻结）

```text
问题定义                     CLOSED
Broad active D1              NO-GO（E1/E3 formal、A4 overlap、A5 opportunity 均未支撑）
recent_var state center      NO-GO（P1 formal 反证）
Protective architecture      CONDITIONAL（未被 P1 否掉，待 Gate 2）
C-007 external replication   FAIL
C-001~C-004                 现象基础仍成立
C-005/C-006                  D，不得宣称 PV/BESS benefit
C-008/C-009/C-010            D，未验证
C-011 / C-012                C
P-001                        原"response evidence state → boundary mode"需改写/降级
P-002                        boundary → control constraint / permission，仍 D
P-003                        不得再作为一般规律（recent_var 锚点失效）
P-004                        active bounded correction，继续 D，仅弱从属
P1                           CLOSED / NO-GO
D2/D3 fusion                 SURVIVES AS CANDIDATE
P2                           HOLD
P3                           BLOCKED
Formal P1 rerun              PERMANENTLY PROHIBITED
Next gate                    Patent Gate 2 prior-art stress test
```

## 5. 剩余发明核（Claim Surgery v1 冻结，见 `claim_tree.md`）

> **一种根据车辆充电相关信息的可获得程度及实际响应历史的充分程度，选择不同短时功率
> 边界生成方式，并基于所选边界确定功率调整约束等级；在响应信息或历史不足时进入保护性
> 控制模式，并根据后续实际充电响应恢复更高功率控制权限的方法。**

组合关系（最值得保护的对象）：

```text
信息条件 → 边界生成模式 → 功率调整约束等级 → 保护性降级 → 实际响应驱动恢复
```

## 6. 排除项（Gate 2 检索与后续撰写一律不得重新引入）

- recent_var 高低作为核心状态规则 / variance-defined S1/S2 作为 CLAIM 1 核心；
- broad active redistribution（"检测少充了多少 → 把差值给别人"）任何宽泛表述；
- PV/BESS benefit（C-005/C-006 仍 D 级）；
- 为绕 prior art 临时添加的复杂度（risk score、双时间尺度模型、confidence weighting、
  fuzzy state、classifier）——不得用"制造复杂度"掩盖核心组合缺失。
