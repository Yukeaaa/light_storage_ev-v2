# A-EV HIL 场地字段核对清单与真实字段映射表 V0.1

- **日期**：2026-09-18（线 2 第一步）
- **性质**：**现场核对工具**。把"现场到底能不能提供已预注册的数据链"变成可逐字段填写、可回填、可机器判定的核对表。
- **唯一准绳**：`src/patent_preexperiment/a_ev/hil_contract.py`（`CONTRACT_FIELDS`）+ `configs/a_ev_hil_contract.yaml` + `reports/patent_definition/A_HIL数据合同与准入门_V0.1.md` §2/§3。
  **本清单不新增字段、不改判定规则**——字段清单与判定规则属**预注册内容**，随 HIL 场景集冻结。
- **配套工具**：`experiments/a_ev/field_check_preview.py` → `results/raw/a_ev_field_check/`（结论 → 准入门后果速查，**预演、非现场判定**）。
- **本步不做**：**不写 BESS-PCS adapter**、不动 synthetic 算法、不做仿真。
- **口径声明（不变）**：`A-M3–M6 = UNVALIDATED`、`Round 5 = NOT STARTED`、`core-patent = NO-GO`。

---

## 0. 怎么用这份清单

```text
① 逐字段核（§2）      → 每个字段只允许四种结论之一（§1），每条结论必须附**证据物**
② 录入映射表（§3）    → 信号名 / 来源系统 / 协议 / 地址 / 单位 / 采样 / 时戳来源
③ 两道硬门（§4/§5）   → 时钟实测偏差、控制权单一性（这两项任一不成立 = REJECTED）
④ 速查后果（§6）      → 先知道每种答案会把准入门打成什么结论
⑤ 回填 + 重跑（§7）   → UNKNOWN 清零后，才替换 yaml 口径并跑 admit()（= 第 2 步）
```

**停止条件（硬）**：

```text
只要映射表里还有 UNKNOWN  ⇒  字段合同 = NOT STABLE
                          ⇒  不得进入 adapter 实现（第 3 步）
```

> 纪律来源：本项目既有教训 —— **"字段存在 ≠ 语义成立"，"写 ACK ≠ 生效"**。
> 本清单的作用是让这两句话在现场变成可勾选的格子，而不是事后争论。

---

## 1. 四种结论的定义与证据标准

每个字段**只允许**四种结论。**结论必须与证据物绑定**；无证据物 ⇒ 只能记 `UNKNOWN`。

| 结论 | 含义 | 准入门口径 | **必须附的证据物** | **明确禁止的写法** |
|---|---|---|---|---|
| **DIRECT** | 现场**已实测读到该值**，来源与语义已确认 | `available: true` | ① 信号名/点名 + ② OID 或寄存器地址 + ③ **一次实测读数或导出文件**（截图/CSV 路径）+ ④ 采集时刻 | "说明书上有"、"协议文档里有"、"理论上可以读"、"供应商说支持" |
| **DERIVED** | 该值**本身不外露**，但现场确认**推导材料逐份可获得**；推导链**尚未实测** | `available: false` + `derivation: <材料清单>` | 逐份材料各自的信号名/OID + 可获得性确认（每份一行） | **把 DERIVED 写成 DIRECT**（见 §2.3 对 `accepted_setpoint` 的专项禁令） |
| **MISSING** | 现场确认：该值与其推导材料**都拿不到** | `available: false`（无 derivation） | 说明尝试过的通道（协议/OID/厂家答复）与失败原因 | 用"MISSING"掩盖"没问清楚" |
| **UNKNOWN** | 未核对 / 待厂家答复 / 有疑问未闭环 | **准入门无表示** → 保守按 MISSING 预演（§6），但**不得**据此宣布合同稳定 | 记录待办人与答复期限 | 把 UNKNOWN 当 DIRECT 或当 MISSING 直接放行 |

**共同纪律**：

1. **不允许第五种结论**（"大概是吧""应该可以"一律归 `UNKNOWN`）。
2. `DIRECT` 的门槛是**读到过一次**，不是**能读**。
3. 涉及**功率**的字段，必须同时登记它是 `实测 / 计算(V×I) / 估算(额定×I)` 中的哪一种
   —— 与项目既有口径一致（实测 Power → computed → estimated 并标记）。**只写"P"不算登记**。

---

## 2. 逐字段核对清单

### 2.0 命名对照（防口径漂移）

现场与厂商用词常与合同键不同，**核对时一律以合同键归档**，别名只作备注。

| 现场常见叫法 | 合同键 | 责任域 |
|---|---|---|
| EMS 指令号 / 事务 ID | `command_id` | EMS |
| **p_cmd_requested** / 计划出力 / setpoint | `requested_setpoint` | EMS |
| 网关翻译值 / 下发报文值 | `translated_setpoint` | 网关 |
| 设备接受值 / 有效指令 / effective setpoint | `accepted_setpoint` | 设备 |
| 写点回执 / 写成功标志 | `write_ack` | 适配器 |
| 控制权 / 主控 / 当前控制源 | `control_owner` | EMS |
| 本地干预来源 / 触发源 | `override_source` | 设备 |
| 干预原因码 | `override_reason` | 设备 |
| 生效时刻 / 设备侧时戳 | `applied_timestamp` | 设备 |
| PCS/BESS 有功反馈 | `p_meas` | 设备 |
| 关口表 / 独立表计 | `pcc` | PCC 表计 |
| BMS SOC | `soc` | BMS |
| 电芯/功率模块温度 | `temp_c` | BMS |
| 充放限值 / 允许功率包络 | `local_limits` | BMS/PCS |
| **[Pmin, Pmax]** | `p_min_p_max` | 组合（推导） |

> 用户清单中的 `PCS/BESS Pmax / Pmin / 本地限值` **不是三个字段**：分别落在
> `local_limits`（运行期 Reported 包络）与 `p_min_p_max`（推导的动态可行域）两处。

---

### 2.1 EMS 侧

| 合同键 | 现场要问 / 要拿到 | DIRECT 标准 | 伪 DIRECT 陷阱 | 缺层后果 |
|---|---|---|---|---|
| `command_id` | 指令唯一号是否**贯穿**到设备日志？网关/PCS 是否回传同一个 id？ | 在 EMS 日志与 PCS 日志中**找到同一个 id**（附两处截图） | "我们自己生成的 UUID 就是 command_id" —— 若设备侧不回传，则**无法关联**，不算 | 审计留痕、M6 写回关联降级（写回不可关联到指令） |
| `requested_setpoint` | EMS 欲下发值：变量名、量纲、正负号约定（充电为正还是为负） | 实测读到 + 与一次真实指令一致 | 用"计划曲线"代替"实际下发值" | **核心字段：缺 ⇒ REJECTED**（M1 执行偏差 / M2 能力学习 / M3 站级缺口 全不可验证） |
| `control_owner` | 每个控制时刻的**控制权归属**如何取得？是显式变量还是需从日志推断？ | 实测读到控制权变量或权威日志字段 | "我们约定由 EMS 控制" —— **约定 ≠ 实际** | 错误归因防线（控制权仲裁）不可验证 |

### 2.2 网关侧

| 合同键 | 现场要问 / 要拿到 | DIRECT 标准 | DERIVED 材料 | 缺层后果 |
|---|---|---|---|---|
| `translated_setpoint` | 网关是否**外露**翻译后的值（报文镜像/配置回读）？ | 网关有该值的外露点且实测读到 | 网关配置 + 报文镜像 | M1 上报限值区分、Reported 包络 降级 |

> ⚠️ **陷阱**："网关是我们自己写的，所以翻译值就是我们知道的那个值" ——
> **我们计算的期望值 ≠ 网关实际外露的值**。必须确认是**可读回**的，否则记 `DERIVED` 或 `UNKNOWN`。

### 2.3 设备侧（**本节含本轮最关键的专项禁令**）

| 合同键 | 现场要问 / 要拿到 | DIRECT 标准 | DERIVED 材料 | 伪 DIRECT 陷阱 | 缺层后果 |
|---|---|---|---|---|---|
| `accepted_setpoint` | 设备**实际接受的有效指令**是否外露？若否，三份推导材料能否逐份取到？ | **仅在设备确有该外露点并实测读到**时才算 DIRECT | ① BMS 充放限值寄存器 ② PCS 限功率寄存器 ③ 控制日志（**三份缺一不可**） | **见下方专项禁令** | 缺 ⇒ **4 项机制不可验证**：M1 上报限值区分 / M6 写回 / Reported 包络 / commissioning 响应窗 |
| `override_source` | 本地 override 是否有**来源标识**（哪位/哪个模块）？ | 实测读到来源标识位或事件记录 | 设备 override 标识位/事件记录 | "从 p_meas 突变能看出来是谁干的" —— **不是标识** | M1 外部约束/保护/模式判据 不可验证 |
| `override_reason` | 是否有**原因码表**与事件记录？ | 实测读到原因码 + 码表 | 原因码表 + 事件记录 | 把"保护动作"笼统当成 reason | 同上 |
| `applied_timestamp` | 设备侧**生效时刻**如何取得？ | 设备有该时戳且实测读到 | 设备事件记录中的生效时刻 | **用 EMS 侧写点时间代替** —— 那是 *write time*，不是 *applied time* | M1 响应观察窗、commissioning 响应窗标定 不可验证 |
| `p_meas` | 有功反馈的变量名、量纲、正负号、**是否实测** | 实测读到；并登记为 实测 / computed / estimated | — | 把 `V×I` 算出来的值当实测值（**必须标记为 computed**） | **核心字段：缺 ⇒ REJECTED**（M1/M2/M6 + 噪声标定 全不可验证） |

#### 🚫 专项禁令：`accepted_setpoint` 一律不得由"理论可推导"升为 DIRECT

> **背景**：合同 `accepted_setpoint` 当前登记为**推导口径**（`available: false` + derivation）。
> 现场核对阶段的**最高结论只能是 `DERIVED`**，且必须逐份确认三份材料可获得。
>
> **禁止**以下写法：
> ```text
> "accepted 可由 BMS 充放限值 + PCS 限功率寄存器 + 控制日志推出"  → 写成 DIRECT   ❌
> "理论上可以算出来"                                              → 写成 DIRECT   ❌
> ```
> **理由**：推导链**是否成立**只能由 commissioning 实测验证（合同规则：存在推导口径字段
> ⇒ 整体保持 CONDITIONAL，须实测验证推导链后方可升级 ADMITTED）。
> 现场核对阶段能确认的只有「材料在不在」，不是「推导对不对」。
>
> **正确写法**：
> ```text
> accepted_setpoint = DERIVED
>   材料① BMS 充放限值寄存器 : 信号名 ___ / OID ___ / 可获得 ✅
>   材料② PCS 限功率寄存器   : 信号名 ___ / OID ___ / 可获得 ✅
>   材料③ 控制日志           : 路径 ___ / 格式 ___ / 可获得 ✅
>   推导链是否实测：否（commissioning 验证）   ← 必须显式写这一行
> ```
> 三份材料**缺任一** ⇒ 结论只能记 `MISSING`（不得保留 DERIVED）。

### 2.4 BMS / PCS 约束类

| 合同键 | 现场要问 / 要拿到 | DIRECT 标准 | 伪 DIRECT 陷阱 | 缺层后果 |
|---|---|---|---|---|
| `soc` | SOC 变量名、量纲、更新周期 | 实测读到 | 用直流侧估算 SOC 替代 BMS SOC | M3/M5 可行域（SOC 约束）降级 |
| `temp_c` | 温度测点位置（电芯 / 功率模块 / 环境）、数量 | 实测读到 | 用环境温度代替器件温度 | M3/M5 可行域（温度约束）降级 |
| `local_limits` | **运行期**充放限值（Reported 包络）是否有外露点？ | 实测读到运行期限值 | **用铭牌限值代替运行期限值** | Reported 包络、M3/M5 可行域 降级 |
| `p_min_p_max` | 推导材料：`local_limits` 与 SOC/温度约束是否都能取到？ | （组合字段，DIRECT 仅当上游算式直接外露） | **直接填铭牌 `[Pmin, Pmax]`** | M3/M5 动态可行域 不可验证（承接规模不可验证） |

> **注意**：`local_limits` 与执行学习边界的耦合**已被冻结为设计决定**（报告 V0.1 §4）：
> `REPORTED_LIMIT` 不进入 `ExecutionLearned`。核对本字段**不改变**该边界。

### 2.5 独立 PCC 表计

| 合同键 | 现场要问 / 要拿到 | DIRECT 标准 | 伪 DIRECT 陷阱 | 缺层后果 |
|---|---|---|---|---|
| `pcc` | 表计型号、接入位置（POI/PCC）、通信通道是否与资源通信**物理/逻辑独立**？ | 实测读到；并确认与 PCS/BMS 通信链路**无关** | **把各 PCS 读数相加当作 PCC** —— 那样站级残差通道失去独立性，等于没做 | **2 项机制不可验证**：模块6 PCC 残差通道 / PCC 主指标 |

### 2.6 适配器侧

| 合同键 | 现场要问 / 要拿到 | DIRECT 标准 | 伪 DIRECT 陷阱 | 缺层后果 |
|---|---|---|---|---|
| `write_ack` | 写点回执是否可读？ | 实测读到回执 | **把"回执可读"当成"指令已生效"** —— 合同与报告均已明确 **写 ACK ≠ 生效**；生效判定依赖 `applied_timestamp` + `accepted_setpoint` + `p_meas` 三者闭环 | M6 写回、控制权仲裁 降级 |

---

## 3. 真实字段映射表（现场填写）

> 填写规则：每行一组信号；一个字段若来自多个源（如三台设备），**分行登记**，并在"结论"列按**最差者**给出该字段的总结论。
> "证据物"列填截图/导出文件的编号与路径；无则结论不得填 DIRECT。

| # | 合同键 | 现场信号名 / 点名 | 来源系统（型号） | 协议 | 地址（OID / 寄存器） | 单位 / 量纲 | 实测/计算 | 采样或更新 | 时戳来源 | **结论** | 证据物 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | command_id | | | | | — | — | | | | | |
| 2 | requested_setpoint | | | | | | | | | | | **核心** |
| 3 | translated_setpoint | | | | | | | | | | | |
| 4 | accepted_setpoint | | | | | | | | | | | **推导口径，禁升 DIRECT** |
| 5 | write_ack | | | | | — | — | | | | | ACK ≠ 生效 |
| 6 | control_owner | | | | | — | — | | | | | |
| 7 | override_source | | | | | — | — | | | | | |
| 8 | override_reason | | | | | — | — | | | | | |
| 9 | applied_timestamp | | | | | — | — | | | | | ≠ EMS 写点时间 |
| 10 | p_meas | | | | | | | | | | | **核心** |
| 11 | pcc | | | | | | | | | | | **须独立于资源通信** |
| 12 | soc | | | | | | — | | | | | |
| 13 | temp_c | | | | | °C | — | | | | | |
| 14 | local_limits | | | | | | — | | | | | 运行期，非铭牌 |
| 15 | p_min_p_max | | | | | | — | — | | | | 推导 |

**字段级汇总（回填 yaml 用）**

| 结论 | 字段数 | 字段清单 |
|---|---|---|
| DIRECT | | |
| DERIVED | | |
| MISSING | | |
| **UNKNOWN** | | **必须为 0 才可进入第 2 步** |

---

## 4. 时钟节核对（**REJECTED 触发项之一**）

合同节：`clock: {unified, max_skew_s: 0.5, actual_skew_s}`。**秒级偏差即把暂态 / clamp / 能力受限搞混**。

| 核对项 | 要求 | 陷阱 |
|---|---|---|
| NTP/PTP 配置状态 | 三个源（EMS / PCS-BMS / PCC 表计）是否都接同一时间源 | 只看配置"以为同步"，**未实测** |
| **实测偏差**（强制） | 用**同一事件**在三处的时戳对比，至少 3 次、记录差值；`actual_skew_s` 必须填**实测值**（现 yaml 为占位 0.2） | 用"配置上应该同步"代替实测 |
| 判据 | `actual_skew_s > 0.5` ⇒ **REJECTED**，且"时序判据与 commissioning 标定"整体标记不可验证 | — |

**建议的现场做法（只读，不改设备）**：在 EMS 侧触发一次**可识别的写点**，分别从 EMS 日志、
PCS/BMS 日志、PCC 表计事件记录中取同一动作的时刻，比对差值。

---

## 5. 控制权节核对（**REJECTED 触发项之一**）

合同节：`control_authority: {single_owner, owners}`。**存在隐形上游 = 错误归因不可控**。

**五类潜在 owner 逐一排查（每类都要给出"会不会写同一控制量"的结论）**：

| # | 潜在 owner | 核对问法 | 结论（会写 / 不会写 / UNKNOWN） |
|---|---|---|---|
| 1 | 本地 EMS | 是否与 A 控制器写同一控制量？ | |
| 2 | 消防策略 | 是否有独立的放电闭锁/切断写点？ | |
| 3 | 削峰 / 需量策略 | 是否会在高峰改写充放指令？ | |
| 4 | BMS | 是否直接下充放限值（而非仅上报限值）？ | |
| 5 | 厂家云 / 远程运维 | 是否可远程改写运行模式或限值？ | |

**建议的现场做法（只读）**：在一段观察窗内记录同一控制量的**所有写者与写值**，
以"是否出现非 A 控制器的写"为准判定；**不要**仅凭通信点表宣布单一控制权。

**判据**：任一 owner 会写 ⇒ `single_owner: false` ⇒ **REJECTED**。

---

## 6. 结论 → 准入门后果速查（**预演，非现场判定**）

由 `experiments/a_ev/field_check_preview.py` 机械跑出（原始输出见
`results/raw/a_ev_field_check/`）。`UNKNOWN` 在准入门无表示，此处按 `MISSING` **保守代入**：

| 情形 | 整体结论 | 不可验证机制 |
|---|---|---|
| 现状（预登记口径，yaml 原样） | **CONDITIONAL** | —（触发条件为"存在推导口径字段"） |
| 全部 DIRECT（含 accepted 实测外露） | **ADMITTED** | — |
| accepted = DERIVED（材料齐全） | **CONDITIONAL** | —（推导口径，待 commissioning 验证） |
| accepted = MISSING | **CONDITIONAL** | M1 上报限值区分 / M6 写回 / Reported 包络 / commissioning 响应窗 |
| override_source + reason = MISSING | **CONDITIONAL** | M1 外部约束/保护/模式判据 |
| pcc = MISSING | **CONDITIONAL** | PCC 主指标 / 模块6 PCC 残差通道 |
| requested_setpoint = MISSING | **REJECTED** | M1 执行偏差 / M2 能力学习 / M3 站级缺口 |
| p_meas = MISSING | **REJECTED** | M1 执行偏差 / M2 能力学习 / M6 写回 / commissioning 噪声标定 |
| 时钟实测偏差 1.2 s > 0.5 s | **REJECTED** | 时序判据与 commissioning 标定（统一时钟前提） |
| 控制权非单一 | **REJECTED** | 错误归因防线（控制权仲裁） |

**从速查表读出的三条运营含义**：

1. **只有 4 件事会把整体打成 REJECTED**：`requested_setpoint` 缺、`p_meas` 缺、时钟超预算、控制权非单一。这四项是**现场谈判的必保项**。
2. **`accepted_setpoint` 拿不到并不致命，但代价明确**：砍掉 4 项机制（含 M6 写回与 commissioning 响应窗标定）。所以它值得争，但不必因为它把整条线否掉。
3. **`pcc` 与 `override_*` 缺失只砍对应通道**：分别是站级残差通道与"外部约束/保护/模式判据"这一 M1 分支。要事前决定"这两项砍掉后 A 还值不值得做"。

---

## 7. 回填程序（**字段核对完成之后**，才进入第 2 步）

```text
前置：§3 汇总表中 UNKNOWN = 0（否则停止，不得进入 adapter）

① 把 §3 结论写回 configs/a_ev_hil_contract.yaml 的 fields 节
     DIRECT  → {available: true}
     DERIVED → {available: false, derivation: "<材料清单>"}
     MISSING → {available: false}
② clock.actual_skew_s 换成**实测值**；control_authority.owners 换成**实测清单**
③ 跑 admit()（PYTHONPATH=src python -m patent_preexperiment.a_ev.hil_contract --config ...）
   → 产出「第 2 步：真实字段准入重判」报告：
       整体 = ADMITTED / CONDITIONAL / REJECTED
       逐机制 = VERIFIABLE / DERIVED / NOT_VERIFIABLE
④ 若仍为 CONDITIONAL：**禁止"改代码把它变绿"**
   → 须明确写出**哪个物理接口缺失**，并登记为 commissioning 待验证项
⑤ 只有 §5 的 commissioning 通过（尤其 accepted 推导链成立），才允许把 CONDITIONAL 升级 ADMITTED
```

**不得在本步做的事**：改判定规则、改字段清单、加字段。
若现场确有新增字段需求 → 走"**合同改版 + 新测试协议**"流程（预注册纪律），不在本步顺手加。

---

## 8. 与首套台架五问的关系（报告 V0.1 §5）

本清单**预先回答**五问中的前两问：

| 台架问 | 由本清单哪一部分决定 |
|---|---|
| 1. 指令能否真实下发？ | `requested_setpoint` / `translated_setpoint` / `write_ack`（§2.1/§2.2/§2.6） |
| 2. accepted/effective 能否取得（或按推导口径合成）？ | `accepted_setpoint` 及其三份材料（§2.3 + 专项禁令） |
| 3. 实际响应时间是什么？ | `applied_timestamp`（§2.3，注意 ≠ EMS 写点时间） |
| 4. 人为 Pmax/Pmin 限值能否制造 ground truth？ | `local_limits` / `p_min_p_max`（§2.4） |
| 5. A 的能力状态更新/承接/写回是否影响下一次控制？ | `p_meas` + `pcc`（§2.3/§2.5）+ 控制权单一性（§5） |

---

## 9. 治理声明

- 本文件为**现场核对工具**，**未**改动 `hil_contract.py`、`a_ev_hil_contract.yaml`、判定规则与字段清单。
- **未**编写 BESS-PCS adapter、**未**改动 synthetic 算法、**未**做仿真、**未**启任何真实数据实验。
- 配套工具 `field_check_preview.py` 只把结论喂给既有 `admit()`，**不改变**其语义；
  其输出为**预演**，**不得**当作现场判定或实验结论。
- 本文件**不构成**"accepted 推导链已成立"的任何证据；该链只能由 commissioning 实测验证。
- `core-patent = NO-GO`、`Round 5 = NOT STARTED`、`A-M3–M6 = UNVALIDATED` **不变**。

### 附录 A：映射表机读骨架（可复制到现场用）

```yaml
# 现场字段核对表（填写后回填 configs/a_ev_hil_contract.yaml）
site_session:
  date: null
  site: null
  engineer: null
fields:
  command_id:          {verdict: null, signal: null, source: null, protocol: null, address: null, evidence: null}
  requested_setpoint:  {verdict: null, signal: null, source: null, protocol: null, address: null, unit: null, kind: null, evidence: null}  # kind: measured|computed|estimated
  translated_setpoint: {verdict: null, signal: null, source: null, protocol: null, address: null, evidence: null}
  accepted_setpoint:
    verdict: null          # 最高只允许 DERIVED
    materials:
      bms_limits_register: {available: null, signal: null, address: null}
      pcs_limit_register:  {available: null, signal: null, address: null}
      control_log:         {available: null, path: null, format: null}
    derivation_tested: false    # commissioning 前恒为 false
  write_ack:           {verdict: null, signal: null, address: null, evidence: null}
  control_owner:       {verdict: null, signal: null, source: null, evidence: null}
  override_source:     {verdict: null, signal: null, evidence: null}
  override_reason:     {verdict: null, signal: null, code_table: null, evidence: null}
  applied_timestamp:   {verdict: null, signal: null, source_is_device: null, evidence: null}
  p_meas:              {verdict: null, signal: null, unit: null, kind: null, evidence: null}  # kind: measured|computed|estimated
  pcc:                 {verdict: null, meter_model: null, independent_of_resource_comm: null, evidence: null}
  soc:                 {verdict: null, signal: null, unit: null, evidence: null}
  temp_c:              {verdict: null, signal: null, location: null, evidence: null}
  local_limits:        {verdict: null, signal: null, runtime_not_nameplate: null, evidence: null}
  p_min_p_max:         {verdict: null, derivation_materials_ready: null, evidence: null}
clock:
  unified: null
  max_skew_s: 0.5
  actual_skew_s: null        # 必须实测（同一事件三源时戳比对，≥3 次）
  measurements: []
control_authority:
  single_owner: null
  owners_checked:
    local_ems: null          # 会写 / 不会写 / UNKNOWN
    fire_policy: null
    peak_shaving: null
    bms: null
    vendor_cloud: null
summary:
  direct: [] ; derived: [] ; missing: [] ; unknown: []   # unknown 必须为空才可进入第 2 步
```
