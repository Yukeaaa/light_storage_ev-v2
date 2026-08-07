# E0-Full 输入数据审计（E0F-01）

- 审计范围：input_quality_only_no_split_no_field_registry
- 文件总数：85877，数据行：448,817,084
- read_ok：85877 / fail 0；gzip_ok：85868 / fail 9
- 短文件：4192；文件内重复时间戳文件：10684；
  倒序文件：0；严重缺口文件：1620
- manifest_sha256：f1a5fd036ed6901bf5b89af9e935b99b071b32b67812f7dff1810f76506bd17a

## 字段覆盖

| 字段 | 文件数 | 比例 |
|---|---|---|
| current | 85877 | 100.00% |
| pilot | 46173 | 53.77% |
| voltage | 32161 | 37.45% |
| state | 57654 | 67.14% |
| energy | 56150 | 65.38% |
| power | 60292 | 70.21% |
| short_files | 4192 | 4.88% |

## 站点功率可用性（measured/computed/estimated 判定）

| site | files | measured_power | voltage×current | current_only(est) | pilot | state |
|---|---|---|---|---|---|---|
| caltech | 56680 | 55961 | 27837 | 28843 | 41842 | 53323 |
| jpl | 27723 | 2857 | 2852 | 24871 | 2857 | 2857 |
| office_01 | 1474 | 1474 | 1472 | 2 | 1474 | 1474 |

## 能量一致性（中位相对偏差）

- caltech：median=0.0036 p95=0.0157（14812 会话）
- jpl：median=0.0574 p95=0.5681（24497 会话）
- office001：median=0.0058 p95=0.0073（1300 会话）

## connectionTime 审计（只审计不切分）

- matched 40644：api_metadata=40644，first_observation_fallback=0，anomaly=0
- 规则：matched：API connectionTime 可解析且不矛盾 → api_metadata；缺失/无法解析 → first_observation_fallback；可解析但与首条观测矛盾 → 仅登记 anomaly，禁止自动替换

## 重复时间戳分类（对冻结 stop-line 的证据补充）

- 含重复时间戳文件：10684；同秒不同值（亚秒采样，可解释）：30226 行；逐字节相同行（可疑重叠）：663 行（分布于 234 个文件）
- 规则：逐字节相同行 → 可疑重叠；同秒不同值 → 亚秒采样（可解释）

## 停止线判定

- manifest_count：PASS（{'ok': True, 'actual': 85877, 'expected': 85877}）
- read_failure_rate：PASS（{'ok': True, 'actual': 0.0001, 'rule': 'read_fail+gzip_fail <= 1%'}）
- dup_ts_within_file：FAIL（{'ok': False, 'actual': 10684, 'rule': '文件内重复时间戳 == 0'}）
- severe_gap_rate：PASS（{'ok': True, 'actual': 0.01886, 'rule': '严重缺口文件占比 <= 5%'}）
- energy_drift：PASS（{'ok': True, 'detail': {'caltech': 0.0036, 'office001': 0.0058}, 'rule': 'caltech/office001 中位偏差 < 1%'}）

## 总体：STOP