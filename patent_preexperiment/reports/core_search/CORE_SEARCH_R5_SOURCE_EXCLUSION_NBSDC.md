# CORE_SEARCH_R5_SOURCE_EXCLUSION_NBSDC

> 生成时间（UTC）：2026-09-06T02:57:04Z
> 状态：source exclusion / 补录筛查记录；非新 scouting 轮次；不改 R5 spec；不触发 Round 5。
> 性质：补录一个此前未被 R5-P0/P0b 覆盖的数据源，归类为 benchmark/calibration only，防止未来被当作实测因果证据重新引入。

## 1. Source Family

NBSDC（国家基础学科公共科学数据中心）下国家重点研发计划 2021YFB1600200（高速公路基础设施绿色能源自洽供给与高效利用系统关键技术）发布的数据集族：1.1 综合数据集（调度运行 + EV 充电负荷）、1.2 光伏工程设计、1.3 服务区典型场景负荷设备配置、1.4 评价指标、1.5 风光资源。

识别来源：外部参考清单 `265353/XiTongJueCe` 仓库 `高速服务区光储充一体化_研究数据集/14_开源数据集与代码仓库参考.md`（2026-09-06 评估）。该源此前不在 R5-P0/P0b 筛查范围内（决策链文档 grep "NBSDC" 0 命中），本记录为补录筛查，不构成新轮次。

同清单附带判定：`Adaptive-Microgrid-Management-for-EV-Charging-Stations` 的 "Texas real-world data" 实为 AFDC EVI-Pro Lite 场景生成，非逐桩实测遥测；仅可作代码/框架参考，不得作为实测证据引用。

## 2. 源文档口径（来自参考清单自身标注）

| subset | 内容 | 口径 |
|---|---|---|
| 1.1 | 光伏出力、负荷曲线、系统配置、EV 充电负荷、电池充放电计划 | EV charging load 两处明确标注"蒙特卡洛模拟生成"；BESS 为充放电"计划"（调度/计划输出，非实测执行）；normal/emergency 仅"包含正常/应急两种场景的调度策略"一句，无 outage 遥测、无设备状态、无 derating 原因 |
| 1.2 | 光伏容量设计、选型配置、微网设计 | PVsyst 仿真结果 |
| 1.3 | 服务区机电设备配置数量与功率 | 统计与测算，非实测 |
| 1.4 | 能源自洽率、供电可靠性、经济性等指标 | 评价指标框架 |
| 1.5 | 风光资源 | 空间插值方法生成 |

全系无任何子集被描述为现场实测；不满足 external requirement → current physical availability → device state → actual execution 的因果链闭合要求。

## 3. 为什么不能满足真实问题发现 / R5

1. 无实测因果链：R5 准入要求同资产、同时间线、四环因果链闭合；NBSDC 全系为生成/仿真/统计口径，C1（real telemetry）即不满足。
2. 循环论证风险：应急场景与调度策略出自同一设计管线；从中"发现固定 reserve/固定优先级失效"只能说明该设计模型在合成场景下的表现，不能升级为真实部署系统的问题存在性（E1 式问题强度证据不成立）。
3. v1 同构风险：在其上做"按负荷类别/EV 延迟性/PV 恢复性/SOC reserve 动态分配供能等级"属自适应/鲁棒调度族，与 V2.0 §1.2 已放弃的 v1 路线（合成数据 + 滚动优化/动态优先级，收益同效或不稳）同构。

## 4. Frozen Verdict

```text
NBSDC family = BENCHMARK / CALIBRATION ONLY
R5 eligibility = FAIL

allowed:
- scenario / benchmark
- stress or engineering-scale calibration
- acquisition-language reference

not allowed:
- real problem-existence evidence
- causal device-state evidence
- closed-loop system-benefit evidence
- split-source completion of R5 criteria
```

## 5. 允许用途（具体化）

- 1.1：光储充系统结构、正常/应急运行逻辑、变量命名参考。
- 1.3：高速服务区负荷工程量级与 stress calibration；仅进 stress/敏感性，不进任何主切分（同低覆盖月份规则）。
- acquisition-language reference：由该数据族反推的"真实服务区 EMS 日志应含字段"（grid-limited / outage / islanding / emergency-mode 标志、负荷分类/关键负荷标志、BESS SOC 与充放电功率、显式功率/能量限值、EMS mode/setpoint、保护/告警/切负荷动作、PCC 功率）可作为未来与运营方沟通的提问语言。这只是 acquisition hypothesis，不构成新的 R5 problem family；修改 acquisition spec 需单独 decision。

## 6. 最终状态

- R5-P0/P0b 结论与 `CORE_SEARCH_R5_DATA_ACQUISITION_SPEC.md` 均不变。
- Round 5 remains NOT STARTED；唯一推进路径仍是 targeted data acquisition（P2 PV/PCS 优先，P1 transformer 次之）的 P1/P2 同源实测数据。
