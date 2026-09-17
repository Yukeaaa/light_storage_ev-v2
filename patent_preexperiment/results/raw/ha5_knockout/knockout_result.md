# H-A5 cheap-knockout —— 原始结果

## S1_single_withdrawal_symmetric

对称双服务、单次撤回。A 完全 firm 支撑且不可中断，B 完全 cond 支撑。用于暴露：目标函数对来源分解完全不敏感（承诺时刻退化）。

- 输入：C_firm=100 kW，C_cond=[100, 0, 100] kW
- 承诺时刻并列最优来源分解数 = **2901**

| 策略 | P1 | P2 | P3 |
|---|---|---|---|
| B5-proportional | [80, 80] | [50, 50] | [80, 80] |
| B5-identity_order | [80, 80] | [80, 20] | [80, 80] |
| B6-parametrized | [80, 80] | [80, 20] | [80, 80] |
| H-A5-state | [80, 80] | [80, 20] | [80, 80] |

- N_provenance_flip = 2
- E_wrong_invalidation = {'B5-proportional': 30, 'B5-identity_order': 0, 'B6-parametrized': 0, 'H-A5-state': 0} kWh
- N_commitment_reversal = {'B5-proportional': 2, 'B5-identity_order': 1, 'B6-parametrized': 1, 'H-A5-state': 1}
- T_recovery_inconsistency = {'B5-proportional': 0, 'B5-identity_order': 0, 'B6-parametrized': 0, 'H-A5-state': 0}
- 轨迹最大偏差 vs H-A5 = {'B5-proportional': 30, 'B5-identity_order': 0, 'B6-parametrized': 0, 'H-A5-state': 0}
- **与 H-A5 轨迹逐点相同者**：['B5-identity_order', 'B6-parametrized', 'H-A5-state']

## S2_split_funding_episode

三服务、**部分混合支撑**、两周期撤回 episode。B 的承诺跨两个保障等级（50 firm + 30 cond），C 全部 cond 支撑。检验：按 **来源混合** 作废 与 按 **服务身份/顺序** 作废 是否给出相同轨迹。

- 输入：C_firm=100 kW，C_cond=[100, 0, 0, 100] kW
- 承诺时刻并列最优来源分解数 = **51541**

| 策略 | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| B5-proportional | [50, 80, 20] | [33, 53, 13] | [33, 53, 13] | [50, 80, 20] |
| B5-identity_order | [50, 80, 20] | [50, 50, 0] | [50, 50, 0] | [50, 80, 20] |
| B6-parametrized | [50, 80, 20] | [50, 50, 0] | [50, 50, 0] | [50, 80, 20] |
| H-A5-state | [50, 80, 20] | [50, 50, 0] | [50, 50, 0] | [50, 80, 20] |

- N_provenance_flip = 0
- E_wrong_invalidation = {'B5-proportional': 34, 'B5-identity_order': 0, 'B6-parametrized': 0, 'H-A5-state': 0} kWh
- N_commitment_reversal = {'B5-proportional': 0, 'B5-identity_order': 0, 'B6-parametrized': 0, 'H-A5-state': 0}
- T_recovery_inconsistency = {'B5-proportional': 0, 'B5-identity_order': 0, 'B6-parametrized': 0, 'H-A5-state': 0}
- 轨迹最大偏差 vs H-A5 = {'B5-proportional': 17, 'B5-identity_order': 0, 'B6-parametrized': 0, 'H-A5-state': 0}
- **与 H-A5 轨迹逐点相同者**：['B5-identity_order', 'B6-parametrized', 'H-A5-state']
