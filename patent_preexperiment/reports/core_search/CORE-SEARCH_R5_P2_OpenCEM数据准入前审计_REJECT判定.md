# CORE-SEARCH R5-P2 OpenCEM 数据准入前审计（REJECT 判定）

> 审计时间（UTC）：2026-09-06T06:13:55Z
> 状态：准入前审计记录；非新 scouting 轮次；不改 R5 spec；不触发 Round 5；不写算法。
> 触发：外部线索提出 OpenCEM 为 P2 intake candidate（对应 R5 启动条件"出现新的、可能满足 data contract 的高质量同源数据源 → 直接 intake audit"）。本记录按 `CORE_SEARCH_R5_DATA_ACQUISITION_SPEC.md` §4 intake gate 顺序执行，所有结论基于仓库/数据库一手证据，不采信 README 转述。
> 数据：OpenCEM v1.0.0（Zenodo DOI 10.5281/zenodo.21436223，CC BY 4.0；GitHub OpenCEM-platform/opencem-dataset）。

## 1. 结论（先行）

```text
OpenCEM = REAL DATA / 迄今最强的公开 P2 schema seed
P2 intake = STOP at event-existence gate（requirement/limit 端无真实变化）
R5 eligibility = FAIL（single-source）
Round 5 = NOT STARTED（不变）
```

OpenCEM 是公开源里第一个把 P2 合同六端字段**全部以真实时间序列形式存在**的数据集（schema gate 命名层 PASS）。但实证查询显示 limit 端（`ongridactivepowerset` 等）**恒为 0/恒定**，`remotectrlstatus` 全期无变化——公开数据时间线上未观察到可识别的外部有功命令/curtailment 激活事件。P2 的核心证据要求是约束/可用性变化与实际能力的可观测差异；没有变化的 limit 不能提供该证据。OpenCEM 不能触发 Round 5，P2 intake 仍为空。

## 2. 数据源事实（一手核实）

| 项 | 值 |
|---|---|
| 系统 | 香港中文大学（深圳）校园真实 PV+BESS 微网（非仿真）：2 台 SPI4880V150-500P 混合逆变器（额定 8 kW），2×(26×480 W) PV ≈ 12.5 kWp，2×200 Ah/51.2 V ≈ 10 kWh 电池，Modbus/RS485 采集 |
| 时间跨度 | 2025-07-12 13:31:35 → 2026-07-13 05:13:53 UTC（约 12 个月，含逐日缺口） |
| 采样 | 快照式，约 12–25 s（analog_measurements 均值 19.6 s，inv1；settings ≈24.7 s、status ≈25.6 s、fault_history ≈26.9 s） |
| 版本 | Zenodo v1.0.0（2026-07-19），配套 column dictionary、validation report、provenance；论文 arXiv:2604.05429 / DOI 10.1145/3679240.3734678 |
| 完整性 | sqlite.zst SHA256 `8e38f982…4b27517` 与官方 SHA256SUMS 一致；sqlite integrity_check ok；解压 4.44 GB |
| 结构 | 8 表：analog_measurements(82 列)、settings(176)、status(20)、fault_history(34)、specs(36)、statistics(52)、totals(37)、context(5)；全部带 read_ts（fractional Unix UTC）+ inverter |
| 行数 | analog 2,989,759 / settings 2,284,775 / status 2,240,052 / fault_history 2,129,517 / specs 1,333,174 |

核验方式：GitHub 仓库 CSV 表头（82 列）+ Zenodo support 包 column_dictionary.csv + 完整 SQLite 直接查询。注意：**settings/status/fault_history/specs 四表只在 Zenodo SQLite 发布**，外部转述"82 字段"低估了发布物。

**时间对齐：** 同一快照管线，各表起止一致、可按 read_ts+inverter 精确连接；存在逐日缺口（如 2026-03-15 inv1 的 settings 无数据而 analog 有 6,817 行）。

## 3. Schema gate 对照 P2 合同（`CORE_SEARCH_R5_DATA_ACQUISITION_SPEC.md` §2）

| 合同字段组 | OpenCEM 候选 | schema 层 | 实证 |
|---|---|---|---|
| identity/time | `read_ts`(UTC) + `inverter`(1/2)；specs 表（机型/序列/硬件与 BMS 版本） | PASS | PASS |
| requirement/limit | settings 表：`ongridactivepowerset`(W)、`ongridreactivepowerset`、`maxlinepower`(W)、`maxchgcurrset`/`chgcurrbypvset`/`chgcurrbylineset`/`chgfullcurrset`(A)、`powerturboen` 等 | 字段存在 | **FAIL：恒定/无真实变化；公开时间线未观察到外部命令激活事件**（见 §4） |
| execution（AC 实际） | analog 表：`outw_a/b/c`、`outsumw/outsumva`、`generatedpowerp/s/q_a/b/c`、`gridpowerw_a/b/c`、`linepowerw_a` | PASS | PASS |
| physical availability（DC/PV 输入） | `pv1volt/pv1curr/pv1power`（pv2/pv3 结构性空）、`battvolt/battcurr/battsoc/battchgpower` | PASS | PASS |
| state/status | status 表：`deroperationstate/derconnectstate/deralarmstatus/derinverterstate/derbattstate/remotectrlstatus`、`sysalarmflag`、`outstatus/chgstatus`；fault_history 表 | 字段存在 | 部分真实变化（告警/输出状态/故障），der* 单值未解码 |
| metadata | specs 表 + README 额定值 | PASS | PASS |

注：`battreserve/pvreserve/otherreserve/grid_reserve` 为 JSON 数组的原始多寄存器 payload，字典明言 "element semantics are component-specific"——**不能在语义解码前当 fault/limit 语义引用**（R4-A1S 时区伪强的同型风险）。

## 4. Event-existence gate：FAIL（决定性）

对 settings 全部 174 个业务列（除 read_ts/inverter）做 distinct 值全扫描：

- `ongridactivepowerset`：**distinct=1，恒 0**（2,225,971 行非空全为 0）。有功设定从未启用。
- `ongridreactivepowerset`：**恒 0**。
- `maxchgcurrset`≡80 A、`chgcurrbypvset`≡80 A、`chgcurrbylineset`≡15 A、`chgfullcurrset`≡3 A、`powerturboen`≡0：**全年恒定**。
- `maxlinepower` ∈ {5600, 6200} W：inv1 内 106,333 个变点。其 P2 active-power-limit 生效语义无法独立复核，且取值切换与已检查的候选物理状态（同时刻 `battvolt`，47.7–57.5 V 横跨两值）无明确对应；因此**不接受为可信的 P2 requirement/limit 事件轨迹**——只判定不可用，不判定其为数据伪象（厂家寄存器语义未解码，见 §5）。
- 全表仅 10/174 列有任何变化：时钟（presenttime）、保留数组、若干一次性二值配置（outpriority/chgpriority/batteodvolt/battfullsoc/battpackrateah 等）。**无任何运营上变化的功率设定/限值/curtailment 命令。**
- `remotectrlstatus` 全期无变化，且 `ongridactivepowerset` 全期为 0：公开时间线中未观察到可识别的外部有功命令/curtailment 激活事件，无法建立变化的 external-requirement 因果端。语义未解码前，不把"没观察到"升级为"架构上不存在"（不排除本地控制器/未记录接口/未发布命令表）。

结论：因果链第一环（external requirement / explicit limit）在 OpenCEM 的运行史里没有真实变化事件，后续 effect gate 无从谈起。

## 5. Semantics gate：NOT PASS

- `deroperationstate/derconnectstate/deralarmstatus/derinverterstate/derbattstate/remotectrlstatus` 全部单值 + NULL：状态字无变化且未解释。
- `sysalarmflag` 11 种取值模式（`[0,…]` 基线、`[0,0,0,16,…]`×280,056 行、`[8,0,…]`×82,774 行等，非零告警约 36 万行）、`outstatus` 3 态、`chgstatus` 4 态：**真实告警/运行状态变化存在**，但 8 元数组的位/槽语义厂家寄存器字典不在发布物内。
- fault_history 为环形缓冲：rec00/01 常驻（~2.5k 种 payload、非空 2,123,635 行），旧槽位大多为空（~92% NULL）→ **真实但稀疏的故障事件**；`*_time` 列已由发布方校准解码，payload 元素语义 "component-specific" 未解码。
- 独立复核需要 SPI4880V150-500P 协议/寄存器文档；因 gate 3 已 FAIL，本审计不再推进。

## 6. 对照 R5 intake gate 五步

| 步骤 | 判定 |
|---|---|
| 1 Schema gate | PASS（命名层；公开源中首个 P2 六组字段全有的源） |
| 2 Semantics gate | NOT PASS（寄存器数组未解码，需厂家协议文档；因 3 已 FAIL 不再推进） |
| 3 Event-existence gate | **FAIL**（requirement/limit 端无真实变化；公开时间线未观察到外部命令激活事件，§4） |
| 4 Effect gate | 未到达 |
| 5 R5 seven-criteria | FAIL（single-source；因果链首端无真实变体） |

## 7. 冻结判定与允许用途

```text
OpenCEM family = P2 INTAKE REJECT / CAUSAL-EVIDENCE NOT AVAILABLE

allowed:
- 未来 P2 语义工作的 real-data validation seed（真实状态字/故障编码/快照对齐结构）
- execution/availability/state 端的真实遥测基准（~20 s 级，12 个月）
- PV 天空图像 + 测量 + 文本上下文的多模态参考；benchmark/calibration

not allowed:
- 作为 P2 requirement/limit 证据（恒 0；公开时间线未观察到约束变化/外部命令激活事件）
- 作为 problem-existence / 因果设备状态 / 闭环系统收益证据
- 在未解码寄存器语义前引用 fault/alarm 数组结论
- 拼接其他源凑 P2 因果链（同 R5 不相加规则）
```

Notes：

- 规模 caveat：2×8 kW 实验级混合逆变器，即便 limit 端有变化，operational magnitude 亦面临 R4-C 式风险（事件存在但量级不足不做救援）。
- 重开条件：发布含外部命令 setpoint/curtailment 轨迹的新版本，或运营方确认存在并记录了可变限值通道。

## 8. 复位与后续

- P2 intake 重新变回"等同源实测链"等待状态；`CORE_SEARCH_R5_DATA_ACQUISITION_SPEC.md` 不改（本审计是针对具体源的 gate 执行，不是合同变更）。
- **MCUT 2026（DOI 10.5281/zenodo.21212713）**：30.03 kWp PV + 100 kW/200 kWh VSG 孤岛微网，明确含 saturation–curtailment–recovery 事件、1 min PV/ESS/pyranometer + 5 s 频率/ESS 遥测、106 天离网统计；Zenodo 文件 **restricted**（元数据公开、文件需授权）。记录为高相关受限备选，**本轮不采取行动**——它的事件口径天然含"约束变化"端，比 OpenCEM 更贴近合同，后续是否申请授权属项目级 external action。
- 面向运营方/OEM 的 acquisition 提问保持不变：显式 active-power limit / curtailment 命令的**带时间戳轨迹**是 P2 的第一稀缺字段；OpenCEM 案例证明"字段名存在但恒 0"即可判 FAIL，接触新源时先查该字段的 distinct 值与变化点数。
- 复现：核验查询与全部数字来自本地解压 SQLite（临时目录），关键 SQL 已内嵌于 §2/§4；重下载按 §2 DOI + SHA256。
