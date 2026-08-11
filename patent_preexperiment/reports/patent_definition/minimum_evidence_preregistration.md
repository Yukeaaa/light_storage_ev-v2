# Patent Definition Phase 3 — Minimum Evidence Preregistration（v1.0.2；§2 P2 骨架已被 v1.1 取代）

> 依据：审查结论52（Final R1 Patent Gate：PROTECTIVE GO + D2/D3 fusion）；
> Phase 2 Claim Architecture Freeze（`open_questions_decision_record.md`，commit `79ff1a1`）。
> 本文件 = **一个总协议 + 三个独立预注册实验**（P1/P2/P3），严格串行。
> 每个实验固定 8 字段，第 8 项（失败后删哪一句）是本阶段最重要的纪律：
> 从"实验过没过"改为"这个实验失败，会从专利里删掉哪一句"。
>
> **v1.0.1（审查结论53，protocol-only closure）**：① Step 0 禁止读取 test E1 labels；
> ② 删除未定义的 matched hard gate；③ 冻结 `min_recent_samples=2`（A5 同源）；
> ④ 封死 ratio zero-denominator 与 duplicate-edge 语义；⑤ 删除 P3→P-004 错误映射；
> ⑥ `NOT_EVALUABLE` 与 Conditional patent route 分开表述。未改实验设计与科学方向。
>
> **v1.0.2（审查结论54，protocol-only mathematical exhaustiveness）**：把全部 outcome
> 映射为唯一 verdict——`0/0` → NA → No-Go；`rate_S2 ≤ rate_S1`（含 equality）→ No-Go；
> `n_S1=0 或 n_S2=0`（train-q50 外推后缺状态）→ NOT_EVALUABLE + route Conditional。
> 不允许留下未定义分支。未改实验设计与科学方向。
>
> **v1.1（Patent Gate 2 重新定义 P2；本文件仅改 P2 骨架状态，未动 P1/P3 冻结字段）**：
> Patent Gate 2 FINAL = NARROW CONDITIONAL GO / HOLD P2（`results/raw/patent_gate2/
> patent_gate2_final.md`，commit `aeee71b`）。Gate 2 结论要求 P2 从"JPL current-only 保护
> 实施例性能验证"重定义为 **D1/D2/D3 机制成立率验证**（信息模式驱动边界选择 + 预算修正
> 动作集 + 响应驱动恢复；D2 为硬杀线，失败即 Project No-Go）。**§2 旧 P2 骨架被取代**，
> 新 P2 完整冻结于 `phase3_p2_preregistration_v1.0.1.md`（8 字段 + Step0 K1/K2/K3 kill
> gates + 机器可审计动作 schema `configs/phase3_p2_action_schema.yaml`；v1.0.1 为
> Review 66 修复版，取代 v1.0）。P1 字段 1–8 维持 v1.0.2 冻结不变；P3 维持 BLOCKED
> （本文件 §3 骨架仅作历史保留）。
>
> **冻结效力**：本文档 P1 冻结为 v1.0.2；P2 以 `phase3_p2_preregistration_v1.0.md` 为准。
> 任何改动须新版本 + 新测试协议，禁止静默修改阈值/变量/population；封存 test 永不重跑；
> office001 外部验证禁止回填阈值。
> 本文件不是法律意见。

---

## 0. Master Protocol（总协议）

### 0.1 目的

在最小证据预算内，为 CLAIM 1–9 提供**直接可审计的实验证据**，并明确每个实验与
CLAIM / claim_id 的映射与失败后果，杜绝"开放式研发"。

### 0.2 实验序列（严格串行，不并行）

```text
P1 独立数据验证 C-007（专利生死门）→ Go/条件 Go/No-Go 门
P2 D1/D2/D3 机制成立率验证（Gate 2 重定义版；P1 未出结果前不启动）
P3 E4.1 克制版（P2 未出结果前不启动）
```

每个实验报告必须回答 8 字段全部内容，尤其第 8 项"失败后删哪一句"。

### 0.3 8 字段模板（所有实验统一）

```text
1. Patent question
2. Supported CLAIM(s)
3. Supported claim_id(s)
4. Input/data independence requirement
5. Frozen method
6. Success / Conditional / No-Go criteria
7. Forbidden post-hoc actions
8. Patent consequence if failed
```

### 0.4 统计纪律（沿用 AGENTS.md，逐条不放松）

- 同会话/池/日/预算下**配对比较**；会话/日级 **cluster bootstrap 95%CI**，
  不把分钟点当独立样本。
- **绝对量与相对量同报**；必须报**最差站点/月份/会话**。
- 每实验至少抽取 **20 个失败案例**（失败=候选/事件/边界触发案例）并归档。
- D1-R 主指标顺序（凡涉及预算/修正/边界）：高估/未执行功率电量 → 站级预算跟踪残差 →
  交付影响 → 动作与运行时间。

### 0.5 数据治理

- 封存 test（E1/E3 formal）永不重跑；A5 已运行结果（`34f04f6` → evidence `a827df3`）为事实基线。
- **test label 隔离（v1.0.1）**：任何实验先确定并哈希 train/val/test split；**Step 0 / 预检
  只能读取 train + validation**；test 的 E1 event label / event count 在正式 test 前
  **完全不可读取**；实现为 code-only baseline + clean worktree 后，formal test **单次 exposure**。
- **office001 只做外部验证，禁止用其结果改任何阈值**（AGENTS.md）。
- 低覆盖/异常月份（2019-12、2020-02、2020-04、2020-12、2021 全年）只作 stress/敏感性，
  不进主切分、不参与门判定。
- 每个实验独立冻结 train/val/test 切分与参数（见各实验字段 4/5），test 只跑一次。
- 输出：每实验产出 manifest（代码 SHA、输入 SHA、worktree_clean、运行时戳）+ 报告。

### 0.6 术语纪律（沿用，违规即退回）

- pilot 与 actual 差异只能称"导引/允许电流与实际响应差异"。
- 只用观察值称"预算差值"；未经验证不称"可回收能力/可回收电量"。
- 未通过 E4.1 验证的响应仿真器不得输出闭环收益结论（P3 只输出技术行为，不输出经济性）。
- 闭环收益（C-005/C-006）保持 D 级，本阶段任何实验**不得**顺带声称。

### 0.7 失败后果声明要求

每个实验报告 §"Patent consequence if failed" 必须明确写出：
**若 No-Go，从 CLAIM 1–9 中删除/改写哪一句，claim_evidence_registry 中哪个 claim_id 降级。**
见 §4 专利删除矩阵。

---

## 1. P1 — 独立数据验证 C-007（专利生死门）

> 目标不是再证明"actual 与 pilot 有差值"，而是验证：
> **仅凭在线可观测的近期实际响应特征，能否在新独立数据中重复识别出
> response-supported / protective / insufficient 三类支持状态的证据差异。**

### 1.1 Patent question

在从未参与 A5 阈值/分桶确定的外部站点上，"近期实际功率波动越高 → E1 响应证据密度越高"
的方向关系是否可重复？据此能否把 recent actual variance 操作化为三态支持状态
（S1/S2/S3）并观测到状态间的证据密度差异？

### 1.2 Supported CLAIM(s)

- **CLAIM 1 第 2 步**：响应证据支持状态的形成（三态）。
- **CLAIM 3**：三态支持状态的实施例（滑动窗口方差 → 划分等级）。
- 间接支撑 CLAIM 2（变化特征作为三态确定方式）与 CLAIM 4（pilot 分支）。

### 1.3 Supported claim_id(s)

- **C-007**（核心：recent actual variance 可区分响应证据密度）。
- **P-001**（支持状态 → 边界模式选择的信息基础）。

### 1.4 Input/data independence requirement

- **主验证集 = office001**（E0-Full 冻结 pipeline 构建，`matched` 会话，1-min 分钟表）。
  - office001 **从未参与** A5 任何阈值/分桶/参考确定（A5 pools 仅 caltech + jpl）；
  - 与 A5 的**唯一接口**是"同一套冻结 E1 事件定义"与"同一套 recent_var 计算方法"
    （E0-Full 冻结代码，不改）。
- **切分（先哈希，v1.0.1）**：office001 站点内时间 60/20/20，split 注册先确定并哈希；
  quartile 边只在 office001 **train** 上拟合一次；**Step 0 / 预检只读 train + validation**；
  **test 的 E1 event label / event count 在正式 test 前不可读取**（code-only baseline +
  clean worktree → formal test 单次 exposure）。
- **绝对不**使用：E1/E3 封存 test；低覆盖/异常月份（仅敏感性）；A5 已用的 caltech/jpl 任何
  数据（避免与 C-007 发现同源）。
- **备份**：若 office001 pilot 覆盖或 pretest E1 事件数不足（见 1.6 预检），备份 = UCSD
  ChargePointEV（E7 pipeline，允许按 V2.0 E7 构建）；两者均不可行 → **P1 evidence verdict =
  NOT_EVALUABLE**、**Patent route verdict = Conditional**（见 1.6），**不静默换数据**。

### 1.5 Frozen method

1. **预检（Step 0，不入门）**：**只读 office001 train + validation**。报告 `matched`
   会话数（**仅作 population audit，不参与 Go/No-Go**）、measured_pilot 覆盖占比、
   **train+validation pretest E1 事件数**（同一套冻结 E1 定义）、站点/月份覆盖。
   产出《数据可行性报告》。**test 的 E1 event label / event count 不可读取。**
2. **变量**：`recent_var` = 与 A5 完全相同的滑动窗口 recent actual power 方差计算
   （E0-Full 冻结实现，**不重新发明、不重拟合**）。
3. **三态映射（冻结于本文档 v1.0.1）**：
   - **S1/S2 主切分直接用 office001 train raw q50（median）**，不依赖 duplicate-edge
     后是否存在 `"Q2"` label：
     - **S1 response-supported** = recent_var ≤ train_q50（实际稳定）；
     - **S2 protective** = recent_var > train_q50（实际波动，按 P-003 语义降低信任）；
   - **S3 insufficient** = 同一 session、同一 uninterrupted run 内先前有效 5-min cycle
     observation **< `min_recent_samples`** → recent_var 不可评估 → S3。
   - **`min_recent_samples = 2`**（v1.0.1 冻结；来源 = A5 `recent_actual_var` 同源实现：
     前一时刻数据、12-cycle rolling window、`min_periods=2`、run 断裂 / severe gap 后重置）。
     **Step 0 不再记录/另定该值。**
4. **指标（test，单次）**：
   - 主指标：E1 evidence rate（cycle 级，event-start snapshot，与 A5 同口径）按 S1/S2 分层；
     `rate_ratio = rate_S2 / rate_S1`（effect size）与 `rate_diff = rate_S2 − rate_S1`
     （inferential）。**`rate_ratio` 的零分母/空状态分支一律按 §1.6 穷尽映射规则判定**
     （`0/0` → NA → No-Go；`+∞` 仅限 `rate_S1=0 且 rate_S2>0`；`n_S1=0 或 n_S2=0` →
     NOT_EVALUABLE）；**test 暴露后不得再发明处理**。
   - 次指标：quartile direction 用 **A5 duplicate-edge rule**——highest effective variance
     bin > lowest effective variance bin（即 Q4>Q1 语义）；不足 2 个 effective bins →
     `insufficient_bin_resolution`，**不得偷偷重找 cutpoint**；S3 占比与触发正确性；
     绝对量+相对量。
   - 统计：会话/日级 cluster bootstrap 95%CI；报最差月份/站点；≥20 个失败案例归档。
5. **敏感性（报告不入门）**：低覆盖/异常月份 + caltech-train 绝对边外推 office001（报告该
   敏感性结果，明确"不推翻主门、不回填阈值"）。

### 1.6 Success / Conditional / No-Go criteria

| 结果 | 判定 | 量化条件 |
|---|---|---|
| **Success (Go)** | 主门 | ① 预检可行：measured_pilot 覆盖 ≥ 50%、**train+validation pretest E1 事件 ≥ 50**（matched 会话数仅作 population audit，不入门）；② effect-size：按 §1.6 穷尽映射计算 raw `rate_ratio` 且 `rate_ratio ≥ 1.5`（`rate_S1=0 且 rate_S2>0` → +∞；`rate_S1=0 且 rate_S2=0` → NA → **No-Go**；**不加 pseudocount / continuity correction**）；③ inferential：cluster bootstrap 95% CI of `rate_diff = rate_S2 − rate_S1` **下界 > 0**；④ secondary quartile direction 符合 duplicate-edge rule（highest effective bin > lowest effective bin；不足 2 bins → `insufficient_bin_resolution`，不重找 cutpoint）；⑤ S3 触发符合定义 |
| **Conditional (条件 Go)** | 部分成立 / 不可评估 | 方向正确但 `1.2 ≤ raw rate_ratio < 1.5`；或 rate_diff CI 含 0 但 point 一致；或样本位于下界（pretest E1 事件 20–50）；或 **P1 evidence verdict = NOT_EVALUABLE**（office001 与 UCSD 均数据不可行 → **Patent route verdict = Conditional**，表述为"不可评估"而非"部分成立"） |
| **No-Go** | 主门失败 | 方向反转或无正向分离（`rate_S2 ≤ rate_S1`，含 equality；`rate_S1=0 且 rate_S2=0` → NA）；或 rate_diff CI 上界 < 0；或 pretest E1 事件 < 20 且备份不可行；或 S3 异常主导 |

**穷尽映射规则（v1.0.2，覆盖全部 outcome，不允许未定义分支）**：

```text
A. n_S1 > 0 且 n_S2 > 0（可评估）：
   rate_S1 = 0 且 rate_S2 > 0 → rate_ratio = +∞（后续仍按 ②/③ 判定 Go/Conditional）
   rate_S1 = 0 且 rate_S2 = 0 → rate_ratio = NA → No-Go（可评估，但无正向 state separation）
   rate_S1 > 0 → rate_ratio = rate_S2 / rate_S1
   rate_S2 ≤ rate_S1 → No-Go（无正向分离/反转；覆盖 equality）
   rate_S2 > rate_S1 → 按 ② effect-size 与 ③ inferential 判定 Go / Conditional

B. n_S1 = 0 或 n_S2 = 0（train-q50 外推到 test 后缺状态，无法比较）：
   P1 evidence verdict = NOT_EVALUABLE
   Patent route verdict = Conditional
   （原因：非机制被反证，而是状态缺失；不归为 No-Go）

三 verdict 穷尽：
   Go          = 有正向分离且强
   Conditional = 有正向分离但弱，或 NOT_EVALUABLE
   No-Go       = 可评估但无正向分离 / 反转
```

### 1.7 Forbidden post-hoc actions

- 禁止在 office001 上多轮尝试不同三态切法/不同窗口/不同方向再挑一组"成立"的；
- 禁止把 office001 结果回填/调整 caltech 阈值；禁止重跑封存 test；
- 禁止用敏感性（异常月份/caltech 绝对边外推）结果推翻或豁免主门；
- 禁止训练 classifier 或宣称"已验证 support rule"超出方向性复现；
- 禁止把 No-Go 私下改成 Conditional 而不走版本化协议变更；
- **禁止在 test 暴露后处理 ratio 零分母 / duplicate-edge**：若 test 出现 `rate_S1=0` 或
  effective bins < 2，必须按本文件已冻结规则判定，不得事后发明 pseudocount / 换 cutpoint。

### 1.8 Patent consequence if failed

- **No-Go（方向反转 / 无正向分离 / evidence 不存在）**：**删除 CLAIM 1 第 2 步"响应证据支持状态"作为强技术中心**
  的资格 → 专利退化到 **field/data-mode driven protective switching**（独立权利要求中心改为
  "按信息条件/数据模式选择边界应用模式 + 保守回退"，variance 特征从 CLAIM 2/3 中删除）；
  `claim_evidence_registry`：**C-007 降级为 D**（描述性假设失去跨站点锚点）、**P-001 弱化**。
  **注：`rate_ratio = NA`（`rate_S1=0 且 rate_S2=0`）与 `rate_S2 ≤ rate_S1`（含 equality）
  均按本 No-Go 后果处理**。
- **Conditional**：CLAIM 1 第 2 步**措辞收窄**（限定"在存在导引/响应信息充分场景"，或把
  variance 作为 CLAIM 3 必要实施例而非 CLAIM 2 泛化）；C-007 维持 C 级不上 B；
  需额外一次独立复现才能回到强中心。若为 **NOT_EVALUABLE**（office001 与 UCSD 均不可行，
  或 test 中 `n_S1=0` / `n_S2=0` 导致状态缺失无法比较），
  专利后果按 Conditional 同规则，但表述为"不可评估"，**不归为 No-Go**。
- **Go**：C-007 升 **B 级（跨站点独立复现）**；P-001 强化；CLAIM 1 第 2 步维持强技术中心，
  三态写入实施例。**结论措辞仅限**："**variance-based state separation 获得独立站点复现**"——
  **不得声称**"S2 protective 已证明更有效"（P1 只验证 `recent_var → E1 evidence density`
  的区分关系；protective 边界是否更好由 P2/P3 回答）。

---

## 2. P2 — ~~JPL current-only 保护实施例~~（**已被取代**，见 v1.1 changelog）

> **v1.1：本节旧 P2 骨架已被 Patent Gate 2 重定义版取代。** 新 P2 完整协议 =
> `phase3_p2_preregistration_v1.0.1.md`（D1/D2/D3 机制成立率验证 + Step0 K1/K2/K3 kill
> gates；v1.0.1 修复 Review 66 P0 接口闭环）。本节仅作历史保留，**不得作为执行依据**；
> 新 P2 未出结果前**不启动**。

### 2.1 Patent question

在没有 pilot、没有 BMS 能力信息时，仅依靠 actual/history 能否构造**有明确退化逻辑的
protective boundary 实施例**？它是否比直接沿用原预算更保守/稳定？历史不足时能否正确退化
到 S3？**不验证主动释放功率。**

### 2.2 Supported CLAIM(s)

- **CLAIM 1 第 3/4 步**：不同信息模式 → 不同边界应用模式（current-only 分支）。
- **CLAIM 5**（current-only history protective mode）、**CLAIM 6**（history 不足 → fallback）。

### 2.3 Supported claim_id(s)

- **P-001 / P-002 / P-003**、**C-012**（JPL 边界方向弱证据）。

### 2.4 Input/data independence requirement

- 主数据 = **jpl E3F 冻结**（current-only 域），与 P1 数据互斥；P2 独立切分/参数，
  jpl train 拟合、jpl test 单次评估；不触碰 office001（留作 P1）。
- 只回答 current-only 技术行为；不主张"JPL 比 Caltech 好"。

### 2.5 Frozen method（骨架，展开冻结于 P1 门后）

- protective boundary = 基于实际功率历史的滚动分位/保守上界 + 退化触发条件；
  S3 fallback 触发 = 历史覆盖不足阈值；退化链 S1?→S2→S3 按 Phase 2 冻结语义。
- 基线 = "直接沿用原预算（无条件信任）"；对比指标：站级预算跟踪残差、过度预算事件率、
  边界越界率、压制时长（对正常充电的影响）；会话/日级配对 + cluster bootstrap。

### 2.6 Success / Conditional / No-Go criteria（冻结原则）

- **Success**：protective boundary 相对基线显著减少过度预算残差（CI 下界排除 0），
  未显著压制正常充电（压制时长 ≤ 上限），S3 触发正确；配对各子场景 ≥ 20 案例。
- **Conditional**：效果方向正确但 CI 边缘，或单月/单站集中。
- **No-Go**：保护边界与基线无差异/更差，或 S3 退化逻辑错误，或压制正常充电不可接受。

### 2.7 Forbidden post-hoc actions

- 禁止"主动释放功率/差值回收/多车重分配"进入本实验；
- 禁止宣称闭环收益；禁止新增复杂模型；
- 禁止用 P2 结果回填 P1 或 office001 阈值。

### 2.8 Patent consequence if failed

- **No-Go**：**删除 CLAIM 5/6 的 current-only 锚点** → 独立权利要求第 4 步收窄到
  "存在导引信息"场景，current-only 分支降为从属或删除；
  P-001/P-002 弱化、C-012 维持弱证据。
- **Go**：current-only 分支获得实施例证据（P-001/P-002 升级），CLAIM 5/6 成立。

---

## 3. P3 — E4.1 克制版（协议骨架）

> P2 未出结果前**不启动**。本节骨架；仿真器验证（AGENTS.md 纪律）在 P2 门后展开。

### 3.1 Patent question

只回答三件事：

```text
1) EV 能力被高估时，protective boundary 是否减少过度功率预算？
2) EV 实际响应恢复时，系统能否提高应用模式/约束等级，避免长期压制车辆？
3) current-only / history-insufficient 情况下，fallback 是否按预期工作？
```

### 3.2 Supported CLAIM(s)

- **CLAIM 1 第 5 步**：约束等级 → 边界应用模式 → 修正允许范围。
- **CLAIM 1 第 6 步**：应用模式与约束等级可降低亦可提高（保护降级/响应恢复）。
- **CLAIM 6/7**（fallback / recovery）。

### 3.3 Supported claim_id(s)

- **P-002**（控制权限/约束等级切换，D）。
- **P-004 明确不映射（v1.0.1）**：P-004 = active bounded correction（对应 **CLAIM 8** 的
  未来独立验证）；P3 禁止 active redistribution 且只测 protective/recovery/fallback →
  **P3 不支撑 P-004**；P-004 维持 D 级，防止 active correction 从后门回来。

### 3.4 Input/data independence requirement

- 输入 = 已冻结 A5/E3F 结果 + P1/P2 的响应行为观测（不引入新原始数据）。
- 仿真器本身须先通过 E4.1 验证（对照 P1/P2 实测响应行为）后，才输出技术行为结论。

### 3.5 Frozen method（骨架）

- 场景三组：能力高估 / 响应恢复 / current-only 退化；单会话到小池级别；
- 指标：过度预算电量、越界事件率、恢复延迟/压制时长、fallback 触发正确性；
- 输出**技术行为**，不输出经济性。

### 3.6 Success / Conditional / No-Go criteria（冻结原则）

- **Success**：三个问题均有确定性回答且行为符合设计（protective 减少过度预算、
  恢复解除保护不长期压制、fallback 安全退化）。
- **Conditional**：部分行为符合、部分边缘（逐项报告）。
- **No-Go**：protective/recovery/fallback 任一核心行为与设计相反。

### 3.7 Forbidden post-hoc actions

- **禁止**：光伏消纳收益、储能经济收益、全站经济优化、新调度算法、active redistribution、
  新复杂模型（= C-005/C-006 保持 D 级的硬边界）；
- 不扩成"大光储充闭环仿真项目"。

### 3.8 Patent consequence if failed

- **No-Go**：**删除/弱化 CLAIM 1 第 5/6 步与 CLAIM 7 的技术行为依据** →
  保护/恢复机制退化为纯架构设计主张，实施例证据依赖 P1/P2；P-002 维持 D。
- **Go**：第 5/6 步与 CLAIM 7 获得技术行为证据（P-002 升 C），实施例可用。

---

## 4. 实验 → CLAIM / claim_id 映射总表

| 实验 | CLAIM | claim_id | 主门 | 失败专利后果 |
|---|---|---|---|---|
| P1 | CLAIM 1(2)、CLAIM 2/3、CLAIM 4(间接) | C-007、P-001 | 三态证据密度可重复（rate_ratio≥1.5、CI>1、方向一致） | 删 CLAIM 1 第 2 步强中心 → field/data-mode driven protective switching；C-007 降 D |
| P2 | CLAIM 1(3/4/5/6)、CLAIM 2/3/4/5 | P-001/P-002/P-003、C-012 | **D1/D2/D3 机制成立率**（v1.1 重定义版，见 `phase3_p2_preregistration_v1.0.1.md`）：K1/K2/K3 全过；M1=M2=1.0、M4=0.0、M3 **natural JPL** recovery trace ≥20/≥5 会话 | K2 失败 → **PROJECT NO-GO**（硬杀线）；K1/K3/M4 失败 → 组合核心缺失 → 极可能 No-Go；Conditional 见新 P2 协议 §6 |
| P3 | CLAIM 1(5/6)、CLAIM 6/7 | P-002 | 三问题技术行为确定且符合设计 | 删 CLAIM 1 第 5/6 步与 CLAIM 7 技术行为依据；P-002 维持 D |

## 5. 专利删除矩阵（失败时逐句删）

| 若 No-Go | 从专利删除/改写 | registry 降级 |
|---|---|---|
| P1 | CLAIM 1 第 2 步"响应证据支持状态"强中心 → 改为信息/数据模式驱动 | C-007 → D；P-001 弱化 |
| P2 | v1.1 重定义版：K2（D2 权限无法落动作边界）→ **PROJECT NO-GO**；K1 → 删 CLAIM 1 第 3 步信息类别分支；K3 → 删第 6 步/CLAIM 5 响应恢复；M4 违反 → 技术问题不成立 | P-002 确认 wording 级 / P-001→D / P-003 弱化 / C-012 维持弱 |
| P3 | CLAIM 1 第 5/6 步 + CLAIM 7 技术行为依据 → 架构设计主张 | P-002 维持 D |

> 任一 No-Go 触发的专利收缩方向汇总：**CLAIM 1 第 2 步 → 第 4 步 → 第 5/6 步** 依次收窄，
> 最坏情形独立权利要求只剩"信息模式驱动的 protective boundary 选择 + conservative fallback"。

## 6. 变更控制与版本

- 本文档 = **Phase 3 v1.0.2（P1 冻结）**。**v1.1（2026-08-11，Patent Gate 2 重定义 P2）**：
  P2 骨架被 `phase3_p2_preregistration_v1.0.1.md` 取代（D1/D2/D3 机制验证 + Step0 K1/K2/K3
  kill gates；v1.0.1 = Review 66 接口闭环修复版）；P1 字段 1–8 与 P3 骨架不变。P3 字段 5
  细节展开 = 新版本（v1.2）+ 新测试协议。
- **v1.0.2 changelog（审查结论54，protocol-only mathematical exhaustiveness）**：把全部
  outcome 映射为唯一 verdict，不允许未定义分支——⑦ `rate_S1=0 且 rate_S2=0` → `rate_ratio=NA`
  → **No-Go**（可评估但无正向 state separation）；⑧ `rate_S2 ≤ rate_S1`（含 equality）
  → **No-Go**；⑨ test 中 `n_S1=0 或 n_S2=0`（train-q50 外推到新站点后缺状态）
  → evidence **NOT_EVALUABLE** + route **Conditional**（非机制被反证，不归 No-Go）；
  ⑩ `+∞` 仅限 `rate_S1=0 且 rate_S2>0`。三 verdict 穷尽：Go=有正向分离且强 /
  Conditional=有正向分离但弱或 NOT_EVALUABLE / No-Go=可评估但无正向分离或反转。
- **v1.0.1 changelog（审查结论53，protocol-only closure）**：① Step 0/预检禁止读取
  test E1 labels，可行性只看 train+validation pretest；split 先确定并哈希，code-only
  baseline → formal test 单次 exposure；② 删除未定义的 `matched ≥ 阈值` hard gate
  （matched 会话数仅 population audit）；③ 冻结 `min_recent_samples=2`（A5 `recent_actual_var`
  同源：前一时刻数据、12-cycle rolling、min_periods=2、run 断裂/severe gap 重置）；
  ④ effect-size 用 raw `rate_ratio ≥ 1.5`（`rate_S1=0`→∞ 数学明确，无 pseudocount；
   **v1.0.2 细化为：仅当 `rate_S2>0` 时为 +∞；`rate_S2=0` → NA → No-Go**），
  inferential 用 rate_diff cluster CI 下界 > 0；S1/S2 主切分用 train raw q50（median），
  secondary quartile 用 duplicate-edge rule（不足 2 effective bins → insufficient_bin_resolution）；
  ⑤ P3 supported claim_id 删 P-004（P-004 仅对应 CLAIM 8 未来独立验证）；⑥ 双数据不可行 →
  P1 evidence verdict = NOT_EVALUABLE + Patent route verdict = Conditional（非"部分成立"）；
  Go 措辞限定为"variance-based state separation 获得独立站点复现"。
- 每个实验 commit 记录：protocol SHA、analysis code SHA、输入 SHA、worktree_clean、运行时戳。
- 本文件不是法律意见；最终以专利代理师出具的意见为准。

---

## 附：Phase 3 交付物清单（每实验）

```text
configs/phase3_{p1|p2|p3}_*.yaml   预注册配置（冻结）
src/experiments/phase3_{p1|p2|p3}/ 代码（frozen）
results/raw/phase3_{p1|p2|p3}/     原始产物 + manifest
reports/patent_definition/phase3_{p1|p2|p3}_gate.md  门报告（含 8 字段 + 专利删除矩阵行）
```
