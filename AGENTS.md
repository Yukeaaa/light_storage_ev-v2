# AGENTS.md

光储充（光伏-储能-充电）专利选题**预实验**工程（重启版）。目标不是做出最强算法，而是按"问题是否真实 → 是否可观测 → 简单基线是否够用 → 闭环是否改善 → 能否形成专利证据链"的顺序，产出可审计的 Go/No-Go 证据。

## 权威协议（先读，按它实现）

- `docs/工商业园区光储充_专利方向确定详细预实验计划书_V2.0.md` 是唯一执行协议。实验编号 E0–E8、阈值网格、Go/条件Go/No-Go 门、输出目录与每个实验的最少文件、12 周计划、阶段门模板全在其中。不要另起炉灶或自创实验体系。
- 工程落地细节（目录结构、数据契约、配置/预注册模板、模块接口、实施里程碑、首批 E0 任务）见 `docs/预实验工程实施方案与实验设计_V1.0.md`，它是 V2.0 的工程化/研究化实施方案，不改变实验编号与门标准。
- 上一版预实验在 `D:\JobWorkspaces\light_storage_ev`（v1：合成数据 + 动态能力匹配/滚动优化方向），效果不好已放弃，教训记录在 V2.0 §1.2（行为预测/自适应/鲁棒调度同效或收益不稳）。v1 仅可作代码与工具链参考，**不要沿用其合成数据方法与结论口径**。
- 主候选 D1-R（基于充电响应状态识别的可执行功率区间生成 + 同池回收重分配）；D2-R/D3-R 只有在 D1 链条中显示独立控制价值才升级。E1 问题强度与 E3 重分配机会任一不成立，不进入复杂模型。

## 数据（在仓库外）

- 仓库 `data/` 只有 `readme.md`，数据实际在 `D:\Users\Micko\Documents\工作\华润集控\光储充\数据`（路径含中文和空格，脚本中必须加引号）。
- 主数据集 `ACN-data/acn_project/` 已构建完成、可直接用：
  - `manifests/static_api_mapping.csv`：关联主表（96,467 行），`match_status` = matched 40,644 / static_only 45,233 / api_only 10,590。严格会话验证只用 `matched`；static_only 仅用于响应机制扩展。
  - `gold/benchmark_5min|15min/`：115 个桩点的 5/15 分钟基准，只含 matched 会话，覆盖 4 个车库（CG1、Arroyo、Parking Lot、office001）。用于 E3 控制池审计与 E4 回放。
  - 原始时序 `ACN-data/ACN-Data-Static/`（2018-05 ~ 2020-12，85,877 个文件，约 4.49 亿行）；API 会话元数据在 `acn_full/`。
  - 质量细节、字段覆盖、复现命令见 `ACN-data/acn_project/README.md`；数据下载/令牌约定见 `ACN-data/AGENTS.md`（令牌只从环境变量 `ACN_API_TOKEN` 读取，绝不落盘；不运行 timeseries 模式）。
- 必须遵守的口径：
  - 功率优先级：实测 Power → Voltage×Current（computed）→ 额定电压×Current（estimated 并标记）。额定电压：jpl=192.7V（按 kWhDelivered 校准，240V 假设高估 17.7%）、caltech=240V、office001=240V。
  - 字段覆盖：pilot 仅 46,173/85,877 文件、state 57,654、power 60,292；**JPL 约 90% 文件只有 current** —— current-only 回退是必做项，pilot 不能作为全量必要输入。
  - 能量一致性：caltech/office001 中位偏差 <1%（高可信主集）；jpl 中位 -5.3%、p95 +49.9%（聚合可用，会话级必须离群过滤并做敏感性）。
  - 低覆盖/异常月份 2019-12、2020-02、2020-04、2020-12 及 2021 全年只作 stress/敏感性，不进主切分（切分规则见 V2.0 §6.4）。
- UCSD 数据在 `UCSD-Microgrid-Database/`（BatteryStorage / ChargePointEV / PVGenerator / BuildingLoadWithEV 等），供 E7 站级嵌入；`UrbanEV/` 另作参考。

## 实验治理红线（勿违反）

- 预注册：阈值按 V2.0 §4.3 网格（1 分钟主粒度，P_on / δ_r / δ_p / T_event / 初始与尾段排除 / pilot 阶跃）在训练/验证集确定；测试集冻结后只跑一次，禁止在测试集上逐图调参。失败后新增方案必须新版本 + 新测试协议。
- 切分：站点时间顺序 60/20/20；Office001 只做外部验证，禁止用其结果改阈值。样本层 L0–L3 按 V2.0 §2.3 定义。
- 禁止在线特征：未来 disconnect / 最终 kWhDelivered / future doneChargingTime / 真实 SOC / 真实剩余需求 / 准确未来离场 / BMS 限功率 / PCS 拒绝原因。这些只能作离线标签或评价。
- 术语纪律：pilot 与 actual 的差异只能称"导引/允许电流与实际响应差异"，不得称"命令失败/拒绝"；只有自然 pilot 正阶跃验证过增量响应的才能谈"可吸收余量"；只用观察值称"预算差值"而非"可回收能力"；未通过 E4.1 验证的响应仿真器不得输出闭环收益结论。
- 统计：同会话/池/日/预算下配对比较；会话/日级 cluster bootstrap 95%CI，不把分钟点当独立样本；绝对量与相对量同报；必须报最差站点/月份/会话；每实验至少抽取 20 个失败案例。D1-R 主指标顺序：高估/未执行功率电量 → 站级预算跟踪残差 → 交付影响 → 动作与运行时间。

## 执行顺序与现状

- 顺序：E0 数据冻结 → E1 问题强度 → E2 可执行响应区间 → E3 重分配机会 → E4 闭环回放 → E5/E6（条件）→ E7 UCSD → E8 专利决策。E0.1–E0.5（数据注册表+哈希、1 分钟会话表、控制池表、split 注册表、普通控制器/分配器基线单测）全部通过才进 E1；基线单测失败时暂停所有候选比较。
- 当前仓库只有协议文档与 data 说明，代码未开始。首批工作：按 V2.0 §15 搭 `patent_preexperiment/`（configs / data_registry / datasets / src / experiments / results / figures / reports / tests），实现 E0。

## 环境与工具链

- 仓库根有 `venv/`（Python 3.12.7），但目前只有 pip，无任何包——首次开发需先装依赖。
- 尚无 pyproject.toml。若沿用 v1 约定（参考 `D:\JobWorkspaces\light_storage_ev\pyproject.toml`）：Python ≥3.11、src 布局、pytest（testpaths=tests, pythonpath=src）、ruff（line-length=100, select E/F/I/UP/B）、mypy strict；依赖 pandas/pyarrow/pyomo/highspy/PyYAML。
- acn_project 的构建脚本（`ACN-data/*.py`）依赖 `ACN-data\.venv` 里的 pandas/pyarrow/acnportal，复现基准时用那个环境。
