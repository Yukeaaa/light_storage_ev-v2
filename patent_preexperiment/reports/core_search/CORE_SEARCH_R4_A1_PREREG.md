# CORE_SEARCH_R4_A1_PREREG：RWTH M5BAT tracking-capability gate

> rule_version=core_search_r4a1_v1；冻结日期=2026-09-03。

## A1-0 时间语义冻结

- primary alignment：schedule timestamp UTC+1 -> UTC；measurement timestamp UTC+2 -> UTC。
- raw-label alignment 只作 sensitivity/diagnostic，不作为主 tracking 结论。
- 若 timezone-normalized interval coverage <95%，R4-A1 直接 STOP。

## A1a tracking magnitude gate

- primary：15min interval mean-power / energy tracking，不做逐秒 residual 主结论。
- active interval：|P_sched| >= 100 kW；idle 不进入主样本。
- primary metric：sign-aware equivalent shortfall energy / requested absolute energy。
- <10% STOP；10-15% weak；15-20% worth A1b；>=20% strong A1b。

## A1b 暂不执行

只有 A1a 过门后，才比较 SOC+direction+schedule-magnitude baseline 与 recent residual。