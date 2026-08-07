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

## 重复时间戳分类（对冻结 stop-line 的证据补充，审查结论10 P0-2）

- 含重复时间戳文件：10684；同一记录时间戳、不同观测值：30226 行（保留进入确定性分钟聚合，机制未被当前数据证明）；逐字节相同行：663 行（含 661 行 0.0 空闲 + 2 行非零，分布于 234 个文件）
- 规则：逐字节相同行 → 可疑重叠（保留不删，派生层按冻结规则 collapse）；同一记录时间戳不同观测值 → 保留进入确定性分钟聚合；采样机制未被当前数据证明

| role | files | identical_dup_rows | zero_idle | nonzero | same_ts_distinct |
|---|---|---|---|---|---|
| caltech_main_frozen | 805 | 0 | 0 | 0 | 2098 |
| caltech_other | 9203 | 0 | 0 | 0 | 26181 |
| jpl_boundary_2020 | 3 | 0 | 0 | 0 | 3 |
| jpl_current_only | 159 | 109 | 109 | 0 | 312 |
| jpl_other | 502 | 554 | 552 | 2 | 1605 |
| office_external | 12 | 0 | 0 | 0 | 27 |

## exact-duplicate 保留 vs 派生层 collapse 的 1-min 影响量（审查结论10 建议3）

- 范围：只扫描 identical_dup_rows>0 的文件；派生层 1-min 聚合：current/power/pilot 取均值、energy 取分钟末值；输入未修改：True
- jpl_current_only：54 文件，其中 39 个受影响；受影响分钟数 current=71 power=0 pilot=0 energy=0；最大绝对差 current=2.466666667 power=0.0
- jpl_other：180 文件，其中 127 个受影响；受影响分钟数 current=340 power=0 pilot=0 energy=0；最大绝对差 current=1.752222222 power=0.0

## 站点 raw→canonical 映射（审查结论10 P1，E0F-02 前冻结）

- raw_sites：{'caltech': 56680, 'jpl': 27723, 'office_01': 1474}；canonical_sites：{'caltech': 56680, 'jpl': 27723, 'office001': 1474}；未映射：[]；mapping_ok：True

## 停止线判定

- manifest_count：PASS（{'ok': True, 'actual': 85877, 'expected': 85877}）
- read_failure_rate：PASS（{'ok': True, 'actual': 0.0001, 'rule': 'read_fail+gzip_fail <= 1%'}）
- dup_ts_within_file：FAIL（{'ok': False, 'actual': 10684, 'rule': '文件内重复时间戳 == 0', 'note': "对 stop_lines 冻结条件'同一会话存在无法解释的重叠记录'的实现解释"}）
- severe_gap_rate：PASS（{'ok': True, 'actual': 0.01886, 'rule': '严重缺口文件占比 <= 5%'}）
- energy_drift：PASS（{'ok': True, 'detail': {'caltech': 0.0036, 'office001': 0.0058}, 'rule': 'caltech/office001 中位偏差 < 1%'}）

## 总体：STOP