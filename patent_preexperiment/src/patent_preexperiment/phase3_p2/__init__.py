"""P2 — 信息模式驱动的 EV 功率预算约束与响应恢复状态机回放验证（v1.0.2）。

本包实现 `reports/patent_definition/phase3_p2_preregistration_v1.0.2.md` +
`configs/phase3_p2_action_schema.yaml`（同步冻结）。实现直接加载 schema 的机器可执行
`d1_lookup.precedence` / `state_machine` / `constraint_levels` / `recovery_trigger`，
禁止二次解释文字。任何冻结阈值改动须新版本 + 新测试协议。
"""
