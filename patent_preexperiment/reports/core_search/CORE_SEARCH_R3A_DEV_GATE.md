# CORE_SEARCH_R3A_DEV_GATE：动态 BESS 备用系统层（DEV）

> 生成时间（UTC）：2026-09-03T02:29:04Z
> 配置：configs/core_search_r3a.yaml（rule_version=core_search_r3a，冻结）

## 1. 目的

> 相同 PCC/缺额风险(0.95 coverage)下，谁锁定的 BESS 能量更少。

## 2. 各臂 locked_reserve_kwh_at_95（跨站中位）

| arm | locked_kwh_at_95 | coverage(原始) |
|---|---|---|
| B0 | 111874.9 | 0.940 |
| B1 | 88136.3 | 0.951 |
| B2 | 111097.1 | 0.939 |
| C | 93238.9 | 0.899 |

## 3. 各站各臂 locked_kwh_at_95

| site | B0 | B1 | B2 | C |
|---|---|---|---|---|
| 3 | 17874.4 | 14340.4 | 17881.4 | 16364.7 |
| 8 | 50721.3 | 41143.9 | 50841.3 | 43971.8 |
| 10 | 173028.4 | 135128.6 | 171352.9 | 142506.0 |
| 70 | 764394.0 | 666100.7 | 769205.9 | 704242.3 |

## 4. 门判定

### 判定：**STOP**

- strongest baseline：B1（locked 88136.3）
- C locked：93238.9
- C 相对 strongest 下降：-5.8%

- C 相对 strongest 下降 ≤10% → R3-A STOP，不消费 holdout。

## 5. 纪律

- DEV 4 站只作 mechanism set，最终 CORE GO 必须在 6 holdout 站复现。
- 不把 fixed Q95(B0) 作为唯一 baseline；最强 baseline = B1/B2。
