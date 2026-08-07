# E0F raw-duplicate gate amendment（草案，待正式评审签署）

依据：审查结论11 §"raw-duplicate gate 最终怎么解"。本文件只做**口径澄清**，不放宽任何冻结阈值。
历史 STOP 不改写为 PASS（历史上确实触发过 STOP，应保留）。正式生效需下一轮评审签署。

## initial_stop

```yaml
initial_stop:
  dup_ts_within_file:
    triggered: true
    files: 10684
```

## resolution（建议签署值）

```yaml
resolution:
  status: resolved
  decision: raw_timestamp_multiplicity_allowed_with_controls
  evidence_sha: "code_sha=90f485c/151cbdf；evidence commit=b6eb6ce/c67b5c3（复核以最新 baseline code_sha 为准）"
```

## 正式数据契约（评审结论11 原文口径）

原始时序允许存在同一记录时间戳的多条观测，必须完整保留并登记；
同时间戳不同值的观测不得任意删除，进入冻结的确定性分钟聚合。
逐字节完全相同的重复原始行不得修改源文件，在派生层按照冻结的 exact-duplicate collapse
规则处理，并保留 raw_duplicate_count/质量标记。
D0 uniqueness 约束施加于 canonical session_id × timestamp_utc(1min) 数据集。
只有在 exact-duplicate collapse 对冻结 K1 gate 结论不产生实质变化后，原始重复 STOP 才可
标记为 resolved。

## 证据链（E0F-01.1 + E0F-01.2）

### 1. 重复分类（机器可验证，e0_full_dup_ts_classification.csv）

- 含重复时间戳文件：10,684；逐字节相同行 663 / 234 文件，全部在 jpl（caltech 0、office001 0）。
- 663 中 661 行为 0.0 空闲 + 2 行非零（均 jpl_other，31.7A / 19.0A）。
- 按冻结月份窗口：caltech_main_window 0 / jpl_boundary_window 0 / jpl_current_only_window 109
  （全 0.0 空闲）/ jpl_other 554 / office_external 0。
- 同一时间戳不同观测值 30,226 行：保留进入确定性分钟聚合，不作"亚秒采样"断言。

### 2. 派生层 actual_power_kw 影响（审查结论11 P0，e0_full_dup_collapse_impact.json）

原始 CSV power 列为空时"power 零影响"不成立；同一差异在派生层
`derive_power`（measured→computed→estimated，JPL rated 192.7）重新评估：

| role | 受影响分钟 | max_abs_diff(kW) | p95(kW) | mean(kW) | 累计绝对能量差(kWh) |
|---|---|---|---|---|---|
| jpl_current_only_window | 71 | 0.475 | 0.0 | 0.000102 | 0.0477 |
| jpl_other | 340 | 0.338 | 0.0 | 0.000096 | 0.1395 |
| overall | 411 | 0.475 | 0.0 | 0.000097 | 0.1872 |

### 3. K1 current-only keep vs collapse 敏感性（审查结论11 P0，e0_full_dup_current_only_sensitivity.json）

54 个受影响文件 / 28,161 分钟，同一冻结 E3-Lite 管线（K1.2-A/C A2_prev_actual 主基线，
预算差值=候选窗口，无吸收假设）：

| 指标 | keep | collapse |
|---|---|---|
| low_power_state 占比（P_on_kw=0.5） | 0.6531 | 0.6531 |
| A2 周期加权候选率 | 0.01980 | 0.01980 |
| A2 日等权候选率 | 0.01211 | 0.01211 |
| 日 cluster bootstrap 95%CI | [0.0029, 0.0227] | [0.0029, 0.0227] |
| 日候选能量占比中位数 | 0.0 | 0.0 |
| 候选窗口翻转 | — | 0 / 3131 |
| 活跃周期翻转 | — | 0 |

门结论：E3 门在 keep 与 collapse 两口径下**同判不满足**（日率 CI 下界 0.0029 < 0.01、
日能量占比中位数 0.0 < 0.005），`gate_flipped=False`。

## 结论

exact-duplicate 在派生层 collapse 对冻结 K1 gate 结论**不产生实质变化**（K1-M 主集与
K1-X 边界无逐字节重复；current-only 的候选率/能量/翻转全部一致或门未翻转）。
据此提议正式签署本 amendment，关闭 #12 并解锁 #13（E0F-02）。待下一轮评审正式签署生效。
