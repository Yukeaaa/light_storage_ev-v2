# CORE_P0_B：EV 群真实短时柔性规模

> 生成时间（UTC）：2026-09-02T13:16:50Z
> 配置：`D:\JobWorkspaces\light_storage_ev-v2\patent_preexperiment\configs\core_search_v1.yaml`（rule_version=core_search_v1，冻结）
> 依据：review/CORE-PATENT SEARCH：系统级核心专利筛选阶段.md §六
> 数据来源：datasets/pool_state_5min/pool_state_5min.parquet（ACN 真实 5min 控制池）
> 下调校准：P0-A binding down 5min response_fraction median = 0.5853

## 1. 目的

> EV 是否真的足以改变 BESS 尺寸/运行？判断柔性功率与 100–200kW BESS 是否同量级。

## 2. 柔性口径

- F0 乐观上调：pilot headroom = max(P_pilot_total − P_actual_total, 0)
- F3 conservative 上调：0（没有足够证据不允许增加）
- 下调（可靠）：P_actual × r_down，r_down = 0.5853
- 说明：F1 rolling-Q95 / F2 M2 需会话级历史，本版（量纲门）不展开；15min 池当前缺失，仅 5min。

## 3. 各独立控制池量纲汇总

| site | garage | periods | pilot_coverage_mean | ev_peak_kw | ev_p95_kw | ev_p50_kw | flex_up_f0_peak_kw | flex_down_reliable_peak_kw | flex_down_reliable_p95_kw | flex_down_reliable_p50_kw | flex_to_ev_peak_ratio |
|---|---|---|---|---|---|---|---|---|---|---|---|
| caltech | California_Garage_01 | 132087 | 0.996 | 107.4 | 48.9 | 6.7 | 123.6 | 62.9 | 28.6 | 3.9 | 0.585 |
| jpl | Arroyo_Garage_01 | 113214 | 0.073 | 148.9 | 131.4 | 15.0 | 39.2 | 87.1 | 76.9 | 8.8 | 0.585 |
| office001 | Parking_Lot_01 | 47821 | 1.000 | 40.3 | 16.9 | 4.6 | 22.6 | 23.6 | 9.9 | 2.7 | 0.585 |

> 每个 site 对应一个独立 garage 控制池，池之间不可加总。

## 4. 按小时（p95）

| hour | periods | ev_p95_kw | down_reliable_p95_kw |
|---|---|---|---|
| 0 | 16133 | 48.4 | 28.3 |
| 1 | 14878 | 33.0 | 19.3 |
| 2 | 13695 | 21.0 | 12.3 |
| 3 | 12437 | 17.4 | 10.2 |
| 4 | 10870 | 17.1 | 10.0 |
| 5 | 9562 | 14.0 | 8.2 |
| 6 | 8636 | 11.7 | 6.9 |
| 7 | 7746 | 10.5 | 6.2 |
| 8 | 6783 | 9.4 | 5.5 |
| 9 | 5855 | 7.0 | 4.1 |
| 10 | 5473 | 7.0 | 4.1 |
| 11 | 5736 | 6.9 | 4.1 |
| 12 | 7547 | 15.8 | 9.3 |
| 13 | 9887 | 56.3 | 33.0 |
| 14 | 11342 | 136.6 | 79.9 |
| 15 | 13392 | 138.9 | 81.3 |
| 16 | 15181 | 137.1 | 80.2 |
| 17 | 16248 | 129.7 | 75.9 |
| 18 | 16743 | 116.0 | 67.9 |
| 19 | 16985 | 100.4 | 58.8 |
| 20 | 17082 | 86.0 | 50.3 |
| 21 | 17112 | 71.1 | 41.6 |
| 22 | 16938 | 61.2 | 35.8 |
| 23 | 16861 | 56.7 | 33.2 |

## 5. 按并发活动会话数（p95）

| concurrency_bin | periods | ev_p95_kw | down_reliable_p95_kw |
|---|---|---|---|
| 1 | 81622 | 6.6 | 3.9 |
| 2-5 | 103104 | 17.0 | 10.0 |
| 6-10 | 23723 | 34.4 | 20.1 |
| 11-20 | 24782 | 57.8 | 33.9 |
| >20 | 59891 | 136.5 | 79.9 |

## 6. 门判定

### 判定：**NO-GO**

> 可靠下调柔性峰值 87.1 kW < 100 kW，且乐观上调柔性峰值 123.6 kW（上调响应未经 P0-A 验证，见 P0-A up r_5m≈0），EV 柔性量纲不足以替代/显著改变 100–200kW BESS

| 指标 | 值 | 阈值 |
|---|---|---|
| EV 峰值功率（最大池） | 148.9 kW | — |
| EV p95 功率（最大池） | 131.4 kW | — |
| 乐观上调柔性峰值 F0 | 123.6 kW | — |
| 可靠下调柔性峰值 | 87.1 kW | >=100 |
| 可靠下调柔性 p95 | 76.9 kW | — |
| 柔性/EV 峰值比 | 0.585 | — |
| BESS 量级比较 | 100–200 kW | — |

## 7. Decision #1 含义

- EV 柔性量纲不足 → CORE-B（最小 BESS sizing）/CORE-C（动态 reserve）不启动。
- CORE-A（BESS-EV 快慢接力）依赖时间动态而非量纲，可单独评估，
  但其 BESS 节省上限受 EV 柔性峰值约束，需谨慎。

## 8. 产物文件

- `results/raw/core_search/p0_b/flex_pool_5min.parquet`（逐周期柔性）
- `results/raw/core_search/p0_b/flexibility_distribution.csv`（分池量纲）
- `results/raw/core_search/p0_b/flexibility_by_hour.csv`（按小时）
- `results/raw/core_search/p0_b/flexibility_by_concurrency.csv`（按并发）

> 注：flex_pool_15min.parquet 因 15min 池缺失未产出。
