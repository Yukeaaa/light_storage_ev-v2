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
| caltech_main_window | 805 | 0 | 0 | 0 | 2098 |
| caltech_other | 9203 | 0 | 0 | 0 | 26181 |
| jpl_boundary_window | 3 | 0 | 0 | 0 | 3 |
| jpl_current_only_window | 159 | 109 | 109 | 0 | 312 |
| jpl_other | 502 | 554 | 552 | 2 | 1605 |
| office_external | 12 | 0 | 0 | 0 | 27 |

## exact-duplicate 保留 vs 派生层 collapse 的 1-min 影响量（审查结论10 建议3）

- 范围：只扫描 identical_dup_rows>0 的文件；派生层 1-min 聚合：current/power/pilot 取均值、energy 取分钟末值；actual_power_kw 按冻结功率优先级在派生层评估；输入未修改：True
- jpl_current_only_window：54 文件，其中 39 个受影响；受影响分钟数 current=71 power=0 pilot=0 energy=0；最大绝对差 current=2.466666667 power=0.0
- jpl_other：180 文件，其中 127 个受影响；受影响分钟数 current=340 power=0 pilot=0 energy=0；最大绝对差 current=1.752222222 power=0.0

派生层 actual_power_kw 影响量（审查结论11 P0：JPL current-only 经 rated 192.7×current/1000 传播）：
- 规则：派生层 actual_power_kw（derive_power 冻结优先级 measured→computed→estimated，JPL current-only=rated 192.7×current/1000）；keep vs collapse 1-min 均值绝对差
- jpl_current_only_window：71 受影响分钟，max=0.475327kW p95=0.0kW mean=0.000102kW，累计绝对能量差 0.047718kWh
- jpl_other：340 受影响分钟，max=0.337653kW p95=0.0kW mean=9.6e-05kW，累计绝对能量差 0.139488kWh
- 总体：411 受影响分钟，max=0.475327kW p95=0.0kW mean=9.7e-05kW，累计绝对能量差 0.187206kWh

## current-only exact-duplicate 的 E3 门敏感性（审查结论11 P0）

- 范围：current-only 冻结月份窗口（jpl_current_only_window）内 exact-duplicate 文件，keep vs collapse 各跑冻结 E3-Lite 管线（K1.2-A/C A2_prev_actual 主基线，预算差值=候选窗口，无吸收假设）；P_on_kw=0.5；冻结月份 ['2018-11', '2019-03', '2019-04', '2019-05', '2019-08', '2019-10']；文件 54
- low_power_state keep：0.6531（28161 分钟）
- low_power_state collapse：0.6531（28161 分钟）
- A2 keep：cycle_rate=0.01980 day_rate=0.012107949624590431 ci95=[0.0028879072996720054, 0.022678842163677215] n_days=39；日能量占比中位数=0.0
- A2 collapse：cycle_rate=0.01980 day_rate=0.012107949624590431 ci95=[0.0028879072996720054, 0.022678842163677215] n_days=39；日能量占比中位数=0.0
- 翻转：候选窗口 0/3131，活跃周期 0
- 门：rate keep=False / collapse=False；share keep=False / collapse=False；门翻转：False

## 完整 JPL current-only 母体 keep-vs-collapse 敏感性（审查结论12 P0，E0F-01.3）

- 范围：冻结完整 JPL current-only 分钟母体（lite_session_minute.parquet JPL 部分）keep vs collapse（仅替换含 exact-duplicate 的母体成员会话）；输入未修改：True
- 冻结基线参考：n_cycles=36736，A2=0.392612，日率=0.362369，CI=[0.32995762618758384, 0.395798678130819]，能量占比=0.038928678037374986，gate=PASS
- 母体 membership：frozen_sessions=9023，affected=54，affected_in_pop=54，affected_not_in_pop=0，untouched=8969
- Keep：n_cycles=36736 A2=0.392612 日率=0.3623694692507855 CI=[0.32995762618758384, 0.395798678130819] 能量占比中位=0.038929
- Keep 复现冻结基线：True
- Collapse：n_cycles=36736 A2=0.392612 日率=0.3623694692507855 CI=[0.32995762618758384, 0.395798678130819] 能量占比中位=0.038929
- 一致性：population_identity=True，nonaffected_unchanged=True，no_extra_minutes=True，site_garage=True，nonaffected_apk_zero_diff=True
- 翻转：候选 0/36683，eligible_cycle=0，活跃 0
- 门：keep_gate=True collapse_gate=True gate_flipped=False
- 验收：{'keep_reproduces_frozen_baseline': True, 'population_identity_preserved': True, 'nonaffected_sessions_unchanged': True, 'keep_gate': True, 'collapse_gate': True, 'gate_flipped': False}

## 站点 raw→canonical 映射（审查结论10 P1，E0F-02 前冻结）

- raw_sites：{'caltech': 56680, 'jpl': 27723, 'office_01': 1474}；canonical_sites：{'caltech': 56680, 'jpl': 27723, 'office001': 1474}；未映射：[]；mapping_ok：True

## 停止线判定

- manifest_count：PASS（{'ok': True, 'actual': 85877, 'expected': 85877}）
- read_failure_rate：PASS（{'ok': True, 'actual': 0.0001, 'rule': 'read_fail+gzip_fail <= 1%'}）
- dup_ts_within_file：FAIL（{'ok': False, 'actual': 10684, 'rule': '文件内重复时间戳 == 0', 'note': "对 stop_lines 冻结条件'同一会话存在无法解释的重叠记录'的实现解释"}）
- severe_gap_rate：PASS（{'ok': True, 'actual': 0.01886, 'rule': '严重缺口文件占比 <= 5%'}）
- energy_drift：PASS（{'ok': True, 'detail': {'caltech': 0.0036, 'office001': 0.0058}, 'rule': 'caltech/office001 中位偏差 < 1%'}）

## 总体：STOP