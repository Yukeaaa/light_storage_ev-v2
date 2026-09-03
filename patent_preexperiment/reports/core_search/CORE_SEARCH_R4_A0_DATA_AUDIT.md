# CORE_SEARCH_R4_A0_DATA_AUDIT：Iontech/Aachen BESS 字段与语义审计

> 后续更新：R4-A0b 已用 RWTH Aachen 官方 M5BAT 数据集（DOI 10.18154/RWTH-2025-06555）消除
> R4-A 的官方源 DATA_PENDING；本报告仅保留为原 Iontech/Aachen 本地聚合源扫描记录。当前 R4-A
> 状态以 `reports/core_search/CORE_SEARCH_R4_A0b_RWTH_OFFICIAL_AUDIT.md` 为准：
> DATA_SOURCE_RESOLVED / LEVEL B / tracking-capability only。

> 生成时间（UTC）：2026-09-03T09:32:54Z
> 配置：configs/core_search_r4a0.yaml（rule_version=core_search_r4a0_v1，冻结）
> 纪律：只审计 README/metadata/raw schema；不建 pipeline，不把 actual<schedule 直接称 physical derating。

## 1. 本地数据发现

| 指标 | 值 |
|---|---|
| local files found | 0 |
| data level | **DATA_PENDING** |
| level meaning | local Iontech/Aachen files not found or metadata insufficient |
| time semantics | NOT_AUDITABLE_WITHOUT_METADATA |

## 2. 字段存在性

| 字段 | present | matched keywords |
|---|---|---|
| actual_bess_power | False |  |
| soc | False |  |
| command_setpoint | False |  |
| dispatch_schedule | False |  |
| temperature | False |  |
| charge_discharge_limit | False |  |
| alarms_status | False |  |
| grid_interaction | False |  |

## 3. 时间语义

- 本地未发现可审计的 Iontech/Aachen metadata/raw files；timestamp timezone、sampling interval、command 生效语义、schedule 重调规则均不可审计。

## 4. 结论

- **DATA_PENDING**：未取得最小必要元数据/原始 schema；R4-A 不进入机制门。

## 5. 产物

- `data_registry/iontech_aachen_registry.json`
