# P1 Step 0 — office001 数据可行性审计

- protocol：Phase3_v1.0.2
- scope：P1 Step 0 feasibility audit（train+validation only，test E1 未读取）

## 判定

- **feasibility_verdict：`feasible`**
- P1 primary data feasible → 进入 P1 code-only implementation

## Population audit（不入门）

- matched 会话总数：1300
- stress 会话（异常月，仅敏感性）：226
- train+validation 会话：859
- 注：matched 会话数仅作 population audit，不参与 Go/No-Go（v1.0.1②）

## 覆盖率

- measured_pilot 会话覆盖：100.0%（冻结线 ≥50%；pass=True）
- 站点数：8；月份数：10
- 月份：2019-03, 2019-04, 2019-05, 2019-06, 2019-07, 2019-08, 2019-09, 2019-10, 2019-11, 2020-01
- 加载分钟行数：298,801

## 字段模式分布（train+validation 会话级）

- measured_pilot：859

## Pretest E1（train+validation，同一套冻结 E1 定义）

- 阈值：{'P_on_kw': 0.5, 'delta_r': 0.25, 'delta_p_kw': 0.5, 'T_event_min': 5, 'initial_exclusion_min': 5, 'tail_exclusion_min': 10}
- **n_pretest_e1_events：140**（go ≥50 / conditional ≥20）
- n_e1_event_sessions：74

## Test 隔离声明

- test E1 event count：None（未读取）
- test minute rows loaded：0
- test 会话行在 E1 计算前物理剔除；test 的 E1 label/count 未读取（v1.0.1①）
