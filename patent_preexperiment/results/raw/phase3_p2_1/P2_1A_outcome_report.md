# P2.1A A-gate Outcome Report

- experiment_id：P2_1A_v1_3
- protocol_version：phase3_p2_1_preregistration_v1.3
- 数据：E0 minutes JPL train current_only（matched）
- implementation_code_sha：ddfb6557118d36a6e7fd8bc5c99cc3bfdfe7406f
- formal_code_sha：c59559e87d251eb8aba8f049443e7891f17e97e7
- worktree_clean：True
- step0_summary_sha256：9e8bab7a9e72225d5105d8b6373798c7ec8f73ae52b255c085510a78caa2655f
- artifact_sha256_verified：True

## (2) Sufficiency

- eligible M3 segments：14227（要求 ≥ 100）
- trigger distinct sessions B0：13840（要求 ≥ 30）
- trigger distinct sessions B1：13873（要求 ≥ 30）
- trigger distinct sessions B2a：13855（要求 ≥ 30）
- trigger distinct sessions B2b：11530（要求 ≥ 30）
- trigger distinct sessions B3：13874（要求 ≥ 30）
- trigger distinct sessions B4：13846（要求 ≥ 30）

## (3) Trigger counts

- B0：14105 个 segment 触发
- B1：14215 个 segment 触发
- B2a：14195 个 segment 触发
- B2b：11671 个 segment 触发
- B3：14227 个 segment 触发
- B4：14113 个 segment 触发

## (4) Point estimates（gain / coverage / latency）

| method | gain | coverage | latency(cycle) | n_triggers |
|---|---|---|---|---|
| B0 | 0.907692 | 0.991425 | 7 | 14105 |
| B1 | 0.837918 | 0.999157 | 5 | 14215 |
| B2a | 0.875097 | 0.997751 | 5 | 14195 |
| B2b | 0.904635 | 0.820342 | 12 | 11671 |
| B3 | 0.656568 | 1 | 94 | 14227 |
| B4 | 0.888046 | 0.991987 | 7 | 14113 |

| Δ | point |
|---|---|
| Δ(B1)=gain(B0)−gain(B1) | 0.069775 |
| Δ(B3)=gain(B0)−gain(B3) | 0.251124 |
| Δ(B2)=gain(B0)−max(gain(B2a),gain(B2b)) | 0.003057 |
| gain(B0)−gain(B4)（null control sanity，正式条件 c3） | 0.019646 |

## (5) Bootstrap CI（session cluster，percentile 95%，N=2000）

- universe：全部 eligible session（n=13874），非『仅含 trigger 的 session』
| Δ | CI_lower | CI_upper |
|---|---|---|
| Δ(B1) | 0.06415 | 0.075163 |
| Δ(B3) | 0.242773 | 0.259714 |
| Δ(B2) | -0.003236 | 0.009249 |
- 无效 replicate：ΔB1=0，ΔB3=0，ΔB2=0（方法 0 trigger 的 replicate 不计入分位数）

## (6) A-gate Verdict（6 条件，C1 穷尽）

**verdict：`FAIL`**（PASS=6 条件全成立；FAIL=任一不成立）

- **c1_delta_b1**：`PASS`　{'ci_lower': 0.06414984399563337, 'ci_upper': 0.0751625758272777}
- **c2_delta_b3**：`PASS`　{'ci_lower': 0.2427731177836149, 'ci_upper': 0.2597140526106252}
- **c3_b4_dominance**：`PASS`　{'gain_b0': 0.9076923076923077, 'gain_b4': 0.8880464819669808, 'holds': True}
- **c4_coverage_ni**：`PASS`　{'coverage_b0': 0.9914247557461165, 'coverage_b1': 0.999156533352077, 'required': 0.7993252266816616, 'ni_factor': 0.8}
- **c5_latency_ni**：`PASS`　{'latency_b0': 7.0, 'latency_b1': 5.0, 'allowed': 8.0, 'add_cycles': 3}
- **c6_delta_b2**：`FAIL`　{'ci_lower': -0.0032361941091048423, 'ci_upper': 0.00924858345304635}

失败条件：

- c6_delta_b2

## (7) Formal diagnostics（不进 Gate；审计材料）

- timing distribution：D:/JobWorkspaces/light_storage_ev-v2/patent_preexperiment/results/raw/phase3_p2_1/p2_1a_timing_distribution.parquet（B0=14105，B1=14215） plot=D:/JobWorkspaces/light_storage_ev-v2/patent_preexperiment/results/raw/phase3_p2_1/p2_1a_timing_distribution.png
- station/month 分层：D:/JobWorkspaces/light_storage_ev-v2/patent_preexperiment/results/raw/phase3_p2_1/p2_1a_station_month.parquet（3120 strata）
- **worst B0 station/month**（gain 最低；tie→字典序）：1-1-191-806 / 2019-05（n=24，gain=0.625）
- failure cases（n_selected=20，n_available=1302，要求≥20）：D:/JobWorkspaces/light_storage_ev-v2/patent_preexperiment/results/raw/phase3_p2_1/p2_1a_failure_cases.parquet plot=D:/JobWorkspaces/light_storage_ev-v2/patent_preexperiment/results/raw/phase3_p2_1/p2_1a_failure_cases.png
  - 选择规则：B0 trigger & Y=0，按 (session_id, segment_id, timestamp_utc) 稳定排序取前 20/20，禁止人工挑图