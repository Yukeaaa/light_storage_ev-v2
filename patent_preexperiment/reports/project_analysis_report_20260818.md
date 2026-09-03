# light_storage_ev-v2 项目全面分析报告

> 生成日期：2026-08-18 ｜ 分析对象：`D:\JobWorkspaces\light_storage_ev-v2`
> 说明：本报告为代码/文档结构与流程梳理，不构成专利法律意见。

---

## 1. 项目定位：一句话

这是**工商业园区"光储充"（光伏-储能-充电）专利方向的预实验工程**，目标不是做最强的算法，而是用
**可审计的科学方法（预注册 + 门评审 + 证据链）**判断一个专利方向值不值得投：

> "充电桩给车辆下发了允许电流（pilot），但车辆实际吸收功率系统性低于桩侧可用功率。EMS 按账面上
> 的 7 kW 安排功率、车实际只吃 4 kW，这 3 kW 差值谁补？"
>
> 发明的核心不是"这 3 kW 给谁"，而是：**在当前数据下，有没有资格继续把这台车当作 7 kW 的可执行负荷？
> 若响应证据不足，就不得盲信、不得做无证据支持的功率上调。**

当前阶段判定（按 v3 corrective audit 后权威口径）：**FILING GO / NARROW CLAIM STRATEGY**。
主证据收窄到 D2 EV 层 M2 双重上调限制；D3/BESS/PCC 系统效果 train+val FAIL、test
CONDITIONAL，只能作弱从属/背景。

---

## 2. 项目结构

```
light_storage_ev-v2/
├── AGENTS.md                        # 权威入口：数据口径、实验治理红线、执行现状、环境工具链（必读）
├── .github/workflows/ci.yml         # Python 3.12：pytest + ruff
├── data/readme.md                   # 数据说明占位（真实数据在仓库外）
├── docs/                            # 协议文档（唯一执行沙盒）
│   ├── 工商业园区光储充_专利方向确定详细预实验计划书_V2.0.md   # ★唯一权威执行协议（E0–E8、门标准）
│   ├── 预实验工程实施方案与实验设计_V1.0.md                    # 工程化/研究化实施方案
│   ├── 光储充专利预实验工程总体落地方案_V2.1.md                # 工程落地方案（不改变门标准）
│   └── evidence/                     # 背景与问题证据台账 + 数据源清单
├── review/                          # 逐轮审查结论归档（审查结论2..13 + 现状/代码审查报告，审计足迹）
├── patent_preexperiment/            # ★真实代码与产物（Python 包 + 实验）
│   ├── pyproject.toml               # 依赖与工具配置（pytest/ruff/mypy strict）
│   ├── configs/                     # 预注册冻结配置（YAML，版本化，不允许散落阈值在代码）
│   ├── src/patent_preexperiment/    # 核心源码包（见下方模块图）
│   ├── experiments/                 # 各实验的 CLI 入口（run.py）
│   ├── tests/                       # 31 个测试文件（契约/切分/门逻辑回归全覆盖）
│   ├── data_registry/               # 数据注册表：split registry、field_mode、baseline、claim 证据台账
│   ├── datasets/                    # 派生标准化数据集（parquet，git 忽略，可从原始数据重建）
│   ├── results/raw/                 # 实验原始产物（E1L/E3L/K0/P0/P2/P2.1/E7-FAST…）
│   ├── results/logs/                # 每次运行日志
│   ├── reports/                     # 各门报告（gate audit）与专利定义文档（claim_tree 等）
│   └── core_search/                 # 系统级核心专利筛选（CORE_SEARCH_MASTER_PLAN + 数据集注册表）
└── (venv/, caches)                  # 本机环境，git 已忽略
```

**src 核心包分层**（按职责）：

| 子包 | 职责 |
|---|---|
| `io/` | 数据路径集中解析（`paths.py`，禁止硬编码绝对路径） |
| `config/` | YAML 加载与 `${var}` 模板展开 |
| `leakguard/` | 禁止特征强制校验（防止在线特征泄漏，阻断式） |
| `response/` | 原始秒级文件 → 1 分钟会话表聚合、会话事件、done/充电阶段 |
| `states/` | 充电阶段状态标记 |
| `metrics/` | bootstrap / 置换检验统计（会话/日级 cluster bootstrap） |
| `registry/` | K0 基线注册 |
| `e0_full/` | E0 数据工程：输入审计、时间切分、池状态、会话分钟、D0 验收、基线 |
| `e1_full/` `e3_full/` | E1（响应差异强度）/ E3（重分配机会）全套加载、统计、门判定 |
| `allocation/` | 重分配机会计算 |
| `e7_fast/` | E7 快速验证链：D0 数据充分性 → D2 EV 验证 → D3 corrective audit → test 永久记录 |
| `p1/` | P1：recent_var 状态判定（已 formal No-Go，移出核心） |
| `phase3_p2/` | P2：D1/D2/D3 设备动作链机制验证（pipeline/state_machine/actions/boundary） |
| `phase3_p2_1/` | P2.1A：D3 falsification（A-gate，formal FAIL） |
| `core_search/` | 系统级专利筛选；Round 3 已关闭，Round 4 仅在真实物理边界遥测可用时继续 |

---

## 3. 技术栈

- **语言/运行时**：Python ≥3.11（实际 3.12，venv 为 3.12.7）；`src` 布局（setuptools）
- **核心依赖**：`pandas≥2.2` + `pyarrow≥15`（数据湖/列存）+ `PyYAML`（配置）+ `matplotlib`（图表）
- **开发工具**：`pytest`（testpaths=tests, pythonpath=src）、`ruff`（line-length=100，E/F/I/UP/B）、
  `mypy --strict`（只查 src）
- **数据格式**：Parquet 分区存储（`site=xxx/year=YYYY/month=MM`），pyarrow dataset 谓词下推加载
- **CI**：GitHub Actions（ubuntu + Python 3.12 + `pip install -e ".[dev]"` + pytest + ruff）
- **统计工具**：numpy 手写 bootstrap / permutation（未引入 sklearn/scipy 等重型库，刻意保持轻量）

无 `keras/torch`、无 `scikit-learn`——项目刻意只用**简单基线 + 可审计统计**，避免"复杂模型不可解释"。

---

## 4. 核心功能与业务逻辑

### 4.1 当前发明链条（E7-FAST v3）

1. **D1 — 信息类别分级选择边界生成方式**：把每辆车的实时信息按可用性分成四档：
   - `M1_capability_rich`（有 BMS 能力信息）、`M2_pilot_actual`（有 pilot+实际功率+足够历史）、
   - `M3_current_only`（只有实际功率+历史）、`M4_history_insufficient`（历史不足）
2. **D2 — M2 双重上调限制**：对具备 pilot+actual+history 的车辆，用
   `min(当前桩侧允许值, 历史实际响应支持水平)` 限制本周期允许增加量，避免把未经历史支持的
   pilot 上调直接当作可执行负荷。
3. **EV 群请求限幅**：EV 群实际接受量还受园区上调请求约束，`ΔP_EV = min(ΔP_req, ΣΔP_i,allow)`。
4. **D3/BESS/PCC 降级**：D3 recovery 已由 P2.1A formal FAIL 移除；D3 系统层 corrective audit 后
   train+val FAIL、test CONDITIONAL，只能作弱从属/背景，不作为 Claim 1 必要技术效果。

### 4.2 关键算法组件

- **M3 保护边界**：同 run 内、当前 cycle 之前、时间窗 15 分钟、实际功率的 0.95 分位数（rolling Q95）；
  样本 <5 或严重缺口 → 边界为空（保守回退）。
- **动作输入外生化**：budget/probe 只由 `(session_id, cycle_index)` 决定（md5(session_id) 首字节做种子），
  生成时**禁止读取**边界/状态/结果——从结构上保证"控制器无法作弊"。
- **disposition 唯一化**：`accepted / clipped_upper / clipped_lower`（无 reject），`final = clip(request, L, U)`。

### 4.3 数据合规与防泄漏（工程最大亮点之一）

- **禁止特征清单**（`configs/forbidden_features.yaml`）：future_disconnect / final_kwh_delivered /
  真实 SOC / BMS 限功率等 17 项，只能做离线标签，**禁止进在线输入**；`leakguard` 在输入 schema 上阻断校验。
- **功率来源优先级**：实测 power → V×I 计算 → 额定电压×I 估算（标记 source）；JPL 额定电压用 192.7V
  （按 kWhDelivered 校准，240V 假设高估 17.7%）。
- **术语纪律**：pilot 与 actual 的差异只能称"导引/允许电流与实际响应差异"，不得称"命令失败/拒绝"。

---

## 5. 数据流与架构

```
仓库外原始数据（~4.49 亿行 / 85,877 时序文件，2020-12 以前）
   │  ACN-Data-Static（静态时序）+ acn_full（API 会话元数据）+ static_api_mapping（96,467 行关联）
   ▼
[E0F-01] 输入审计 → source_manifest + 数据质量 + connectionTime 审计（只审计不自动替换异常）
   ▼
[E0F-02] 时间切分冻结 → split_registry（站点内按会话连接时间 60/20/20 train/val/test；
         caltech=主集 / jpl=边界+current_only / office001=外部验证不进主切分）
   ▼
[E0F-03] 会话 1 分钟表构建 → datasets/session_response_1min/（site×year×month 分区）
[E0F-04] 控制池状态表   → datasets/pool_state_1min|5min（只含 matched 会话）
   ▼
[D0] 数据工程验收门（唯一性/完整性/能量一致性<1%/gold 基准/切分安全/防泄漏/确定性 全绿）
   ▼
[各实验流水线] E1 响应差异强度 → E3 重分配机会 → P2 D1/D2/D3 机制 → P2.1A falsification → E7-FAST
   ▼
[门评审] 每次实验产出 Gate 报告 → Go / Conditional Go / No-Go 判定 → 进入下一阶段 或 收缩/终止
```

**架构设计模式（关键特征）**：

1. **预注册（Preregistration）**：所有阈值、切分、停止线在跑数据**之前**冻结到 YAML 配置
   （`configs/*.yaml`），代码 `schema.py` 加载后 fail-closed 校验（experiment_id/协议版本漂移即报错）。
   → 防止"先看结果再挑阈值"的 p-hacking。
2. **门控流水线（Gate pipeline）**：E0→E1→E3→Pn 串行推进，每步有 kill gate；任一硬杀线失败
   （如"基线消除 >80% 候选"）即停止，**禁止删不利月份/改阈值续命**。
3. **once-only + sentinel 不可逆治理**：正式 test 只能暴露一次（sentinel 状态机 UNCONSUMED→RUNNING→
   CONSUMED），永久禁止重跑；D3 corrective audit 的 test 回放只能称代码纠错审计，不能重新定义为
   confirmatory test。
4. **数据血缘（provenance）**：每份产物记 SHA256（源文件/registry/step0 产物），跨 registry 一致性
   校验（population 冻结 85877/40644/45233，数量+集合双重对账）。
5. **配置驱动**：一切阈值/路径/月份集中在配置文件，代码零硬编码（`io/paths.py` + `yamlutil` 统一解析）。

---

## 6. 配置与部署

### 6.1 环境要求
- Python ≥3.11（推荐 3.12）；Windows 工作机（路径含中文/空格，脚本均加引号）
- 依赖仅 4 个运行时库 + 4 个 dev 库（见 pyproject.toml）
- 数据在仓库外（路径配置 `configs/paths.yaml`，**不入库**；模板 `paths.example.yaml`）

### 6.2 启动/验证方式（在 `patent_preexperiment/` 下）
```bash
..\venv\Scripts\python.exe -m pytest        # 跑 31 组测试
..\venv\Scripts\ruff.exe check              # 静态检查
# 单实验入口（示例）：
python experiments/e0_full/run.py [--workers N] [--reuse-manifest]
python experiments/p1/step0/run.py ...      # P1/P2 系列均有独立 CLI
```

### 6.3 部署治理约定（红线）
- 代码中禁止出现：绝对路径 / 月份选择 / 统计阈值（全在配置）
- 测试集冻结后只跑一次；失败后新方案 = 新版本 + 新测试协议
- 正式 gate 要求 clean committed worktree（git 状态洁净）

---

## 7. 代码质量评估

### 7.1 亮点（明显高于一般研究工程）

| 维度 | 表现 |
|---|---|
| **可复现性治理** | 预注册配置 + SHA256 血缘 + sentinel once-only + git diff 校验，几乎达到"防伪实验室"级别 |
| **防泄漏设计** | leakguard 阻止 17 项禁止特征入在线输入；state_machine 明确"禁止由 recent_var/classifier 驱动" |
| **接口解耦** | actions.py 动作输入外生化、boundary.py 因果化（shift(1)），模块职责单一、向量化无逐行循环 |
| **fail-closed 思维** | 密钥缺失/配置漂移/数据异常一律抛错，绝不静默降级 |
| **测试完备** | 31 个测试文件覆盖配置契约、切分金标准、门逻辑、回归（test_e0_*、test_p2_*、test_e7_fast_*、test_k11/12_regression） |
| **文档纪律** | 每份源码都有 docstring 标注协议依据（AGENTS.md / V2.x 章节号），评审足迹完整 |

### 7.2 潜在改进点

1. **代码规模偏大、模块数量多**：仅 `src` 就有 ~60 个 .py 文件，P1（已 No-Go）/ phase3_p2 /
   phase3_p2_1 / e7_fast 之间存在一定功能重叠（重复的 runner/loader 模式），有重构空间（公共 runner 基类）。
2. **硬编码的"魔法学号"**：schema.py 中 `_EXPECTED_*` 校验值与 config 强耦合——若协议版本更迭需同步改
   两处；建议改为从冻结 manifest 单一来源校验。
3. **性能**：e0 split/registry 构建存在逐行 `iterrows()`（85,877 会话），虽已参数化可运行，但大数据量下
   可改向量化/并行；`p1/step0` 等历史分支长期保留增加维护负担。
4. **报告生成多为手写 Markdown 拼接**（如 e7_fast runner `_write_report`），格式与措辞高度模板化，后续
   若需多语言/HTML/PDF 输出需要重构。
5. **历史文档很多**：v2/P2/R1 报告保留审计足迹，但对外与后续开发只能引用 v3 CURRENT AUTHORITY。
6. **系统层证据弱**：D3 corrective audit 后系统效果不支撑 Claim 1，BESS/PCC 只能作弱从属或背景。

---

## 8. 快速上手路线（给新成员）

1. **先读** `AGENTS.md`（30 分钟）→ 明确数据口径与红线；
2. **再读** `docs/...V2.0.md` 的"预注册/门标准/实验编号"章节 + `README.md`；
3. **看结构**：`src/` 按 `io → response → e0_full → e1/e3 → p2 → e7_fast` 顺序读；
4. **跑验证**：安装依赖 → `pytest` → `ruff`（全绿再动代码）；
5. **理解"当前状态"**：看 `reports/patent_definition/…v3_e7_fast.md`（CURRENT AUTHORITY 3 份）+
   `results/raw/phase3_p2/P2_patent_gate.md` + 最新 3 个 commit message；
6. **参与实验**：严格按"新配置版本 + 新 gate 报告 + clean worktree + once-only"流程，禁止直接改测试集。

---

## 附：当前专利判定快照（截至 2026-08-18，git HEAD=e5304c7）

- **阶段线**：P1 formal No-Go → Patent Gate 2 NARROW CONDITIONAL GO → P2 formal SUCCESS/NARROW GO →
  P2.1A D3 falsification FAIL → **E7-FAST D0/D2 GO + D3 train+val FAIL/test CONDITIONAL →
  FILING GO / NARROW CLAIM STRATEGY**
- **主权利要求**收窄为：**M2 双重上调限制（`min(桩侧允许, 历史响应支持)`）+ EV 群请求限幅
  `ΔP_EV = min(ΔP_req, ΣΔP_i,allow)`**；BESS/PCC 降为强从属（不作为 Claim 1 必要技术效果）
- **D3 recovery 已移除**（P2.1A FAIL），由"信息类别自然变化"替代
- **旧 D3 系统收益数字作废**：不得引用 shortfall 降 30%/40%、BESS 临时补偿降 15%/41%。
- 待办：专利代理师正式检索 + 法律意见（本工程仅给证据链，不给法律结论）
