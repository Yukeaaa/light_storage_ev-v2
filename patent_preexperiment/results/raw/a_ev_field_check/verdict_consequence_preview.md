# 字段结论 → 准入门后果速查（预演）

| 情形 | 整体结论 | NOT_VERIFIABLE 机制数 | 不可验证机制 | 推导字段数 |
|---|---|---|---|---|
| S0 现状（预登记口径，yaml 原样） | **CONDITIONAL** | 0 | — | 1 |
| S1 全部 DIRECT（含 accepted 实测外露） | **ADMITTED** | 0 | — | 0 |
| S2 accepted=DERIVED，材料齐全 | **CONDITIONAL** | 0 | — | 1 |
| S3 accepted=MISSING（推导材料取不到） | **CONDITIONAL** | 4 | M1 上报限值区分；M6 写回；Reported 包络；commissioning 响应窗 | 0 |
| S4 override_source/reason=MISSING | **CONDITIONAL** | 1 | M1 外部约束/保护/模式判据 | 1 |
| S5 独立 PCC 表计 MISSING | **CONDITIONAL** | 2 | PCC 主指标；模块6 PCC 残差通道 | 1 |
| S6 requested_setpoint MISSING（核心字段） | **REJECTED** | 3 | M1 执行偏差；M2 能力学习；M3 站级缺口 | 0 |
| S7 p_meas MISSING（核心字段） | **REJECTED** | 4 | M1 执行偏差；M2 能力学习；M6 写回；commissioning 噪声标定 | 0 |
| S8 时钟偏差 1.2s > 预算 0.5s | **REJECTED** | 1 | 时序判据与 commissioning 标定（统一时钟前提） | 1 |
| S9 控制权非单一（存在隐形上游） | **REJECTED** | 1 | 错误归因防线（控制权仲裁） | 1 |
