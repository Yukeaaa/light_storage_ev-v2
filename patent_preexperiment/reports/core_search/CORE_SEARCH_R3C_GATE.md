# CORE_SEARCH_R3C_GATE：需量窗口预算控制系统层

> 生成时间（UTC）：2026-09-03T03:35:21Z
> 配置：configs/core_search_r3c.yaml（rule_version=core_search_r3c，冻结）

## 1. 场景

- Pcap (train Q90)：283.8 kW
- BESS：Pmax 172.1 kW / Emax 15.7 kWh

## 2. 各臂结果（validation 段）

| arm | throughput_kwh | peak_kw | actions | violation_kwh | violation_count |
|---|---|---|---|---|---|
| B0 | 1115.2 | 106.8 | 4806 | 4875.3 | 687 |
| B1 | 1017.4 | 106.8 | 4354 | 4834.6 | 656 |
| B2 | 1017.4 | 106.8 | 4354 | 4834.6 | 656 |
| C | 966.5 | 172.1 | 1232 | 4851.7 | 692 |

## 3. 门判定

### 判定：**STOP**

- strongest baseline：B1
- C 相对 strongest throughput 下降：5.0%
- violation 不劣化：True
