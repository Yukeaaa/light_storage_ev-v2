"""D2 真实 EV 数据验证：M2 上限 + baselines + 指标（review §14-18）。

回答 review §14 的问题：“上述规则在真实 ACN 车辆响应上是否比简单办法更合理？”

四个控制器（review §15）：
- B0_no_increase: allowed_up = 0（最保守）
- B1_pilot_only:  allowed_up = max(P_pilot - P_actual, 0)（把 pilot 当能力的错误）
- B2_rolling_q95: allowed_up = max(Q95_history - P_actual, 0)（★ 最强简单 baseline）
- C_candidate_m2: allowed_up = max(max(P_actual, min(P_pilot, Q95_history)) - P_actual, 0)

P_support（review §15）：max(P_actual_5min - P_actual_before, 0)
  = 真实自然事件中观察到的实际增加量；非车辆理论最大能力。
禁止外推（review §22）：candidate 允许量 <= P_support 视为未超出；超出部分 = Over。
"""
