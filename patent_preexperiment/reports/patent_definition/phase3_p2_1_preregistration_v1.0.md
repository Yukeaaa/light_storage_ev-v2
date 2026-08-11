# P2.1 Preregistration v1.0 — D3 Falsification + D2 Technical-Effect Closed-Loop Gate

> **⚠ 本文件已被 v1.1 取代（审查第二轮 6 项协议级修订）。权威版本：**
> `phase3_p2_1_preregistration_v1.1.md`。本 v1.0 仅由 git 历史保留，**不得冻结**。
> v1.0 的主要问题：risk set 未统一（P0-1）、baseline ε/median-max 未冻结（P0-2）、
> Y 语义过强（P0-3）、Conditional 后门（P0-4）、B 的 CI 方向错误（P0-5）、无 MCID（P0-6）。
> 详见 v1.1 §0 changelog。

> 日期：2026-08-12（v1.0 草案，待 Review 通过后冻结）
> 依据：P2 formal = SUCCESS / NARROW GO（`results/raw/phase3_p2/P2_patent_gate.md`，
> mechanism realizability only）；审查 2608120033（`review/项目现状2608120033.md`）。
> **P3 继续 HOLD**。本协议不"继续优化"，**专门杀这个发明核**。
> 本文件不是法律意见；最终以专利代理师意见为准。

---

## 0. 为什么是 P2.1 而不是 P3

P2 证明 D1/D2/D3 设备动作链**机制可实现**（M1/M2/M4 实现正确性 + M3 natural 1,060 会话）。
但 P2 **没有**证明：

1. D3 的 boundary-contact recovery trigger 包含超过"简单功率持续性"的**增量信息**
   （rolling-Q95 自相关伪证据风险：用过去实际功率高分位数当边界，再用"现在仍接近该
   分位数"当恢复证据——恒定 5kW 单测即触发 recovery）；
2. D2 的"预算修正允许区间"在独立闭环中产生**真实物理控制效果**，而非仅把已有约束
   换成 "permission / allowed range" 表述（P2 的 requested_delta 是内部枚举 probe，非
   真实 EMS request）。

这两点打不穿 → **Project No-Go**，而不是继续投入。P2.1 由两个连续 kill gate 组成，
**A PASS 才运行 B**：

```text
P2.1A  D3 Falsification     recovery trigger 是否有超过 persistence 的增量辨识力？
        ↓ FAIL              D3 No-Go → 原发明核重新 Patent Gate（极可能 Project No-Go）
        ↓ PASS
P2.1B  D2 Closed-loop/HIL   D1+D2+D3 是否在独立闭环产生真实物理控制效果？
        ↓ FAIL              D2 No-Go → Project No-Go
        ↓ PASS
专利代理师检索（ACN element-mapping + EP/CNIPA + ISO 15118）→ FILING GO 候选
```

---

## 1. 研究问题与假设（字段 1）

### P2.1A — D3 Falsification

**问题**：D3 boundary-contact recovery trigger（`protective_bound>0 且 actual ≥ 0.95×boundary
连续 3 cycle`）对 recovery 之后一段时间 EV 可支持的上界，是否具有**超过简单功率持续性
baseline 的预测增益**？

**可证伪假设 H_A**：在冻结 JPL train 域上，D3 trigger 对 post-recovery 窗口内"EV 可支持
更高权限"的预测增益，**严格大于**最强简单 persistence baseline 与随机时点匹配 baseline。

**零假设 H_A0**：D3 trigger 的预测增益**不优于**最强 persistence baseline，或**不优于**随机
时点匹配。H_A0 成立 → D3 无增量辨识力 → **D3 No-Go**。

### P2.1B — D2 Technical-Effect Closed-Loop

**问题**：在独立 EMS request generator + 独立 EV response emulator 的最小闭环中，
D1+D2+D3 相对 unrestricted correction baseline，是否产生**明确物理控制效果**？

**可证伪假设 H_B**：D1+D2+D3 在以下物理指标上严格优于 unrestricted baseline——
infeasible command rate / boundary violation / unsupported positive correction rate /
tracking residual / unnecessary protective duration。

**零假设 H_B0**：D1+D2+D3 在上述指标上不优于 unrestricted baseline。H_B0 成立 →
**D2 No-Go**。

---

## 2. 冻结的 D3 trigger 参数（**禁止调参救场**）

```text
protective_bound      Q95 of actual_power history（shift(1) 因果化，窗口 15 min）
recovery condition    protective_bound > 0 AND actual >= 0.95 × protective_bound
                      连续 3 cycle（1-min cycle）
min_history_samples   5
```

> **审查 2608120033 §8 红线**：若 D3 不优于 persistence baseline，**不得**调 0.95、不得改
> 3 cycles、不得加 classifier / confidence score / 双时间尺度 / learned trigger 救它。
> 先走 D3 No-Go，再按版本化协议变更。本协议冻结上述参数，P2.1A 全程零改动。

---

## 3. P2.1A 实验设计（D3 Falsification）

### 3.1 数据域（**JPL train only**）

```text
development / falsification 域   JPL train（P2 冻结 split 的 train 部分，current-only）
P2 formal test（已 consumed）     frozen historical evidence only
                                  禁止重新用于阈值选择 / 规则修改 / trigger 调参
新独立数据（若升级 formal）       必须使用新 untouched cohort / 新数据域
```

> **数据治理红线（审查 §9）**：P2.1A 只在 JPL train 域做 falsification。若暂无新独立数据，
> 诚实写"P2.1A survived falsification on frozen train domain"，**证据等级不升级为
> independent validation**。比再次消费旧 test 干净得多。

### 3.2 Adversarial baselines（5 个对照 trigger）

对同一批 natural recovery 候选时点，用以下方法各自产生"recovery 时点"，比较它们对
post-recovery 可支持上界的预测力：

```text
B0  D3 original          原冻结 trigger（actual >= 0.95×Q95_boundary，连续 3 cycle）
B1  simple persistence   actual 在窄带 [actual_mean±ε] 内连续 3 cycle（"功率稳定几分钟"）
B2  rolling median/max   actual >= rolling median (或 max) threshold，连续 3 cycle
B3  random matched       在同 charging phase 随机选时点（按 phase 长度匹配）
B4  lag/time-shuffle     用 actual 的 lag/shuffle 版本触发（破坏时序关系，null control）
```

> B1 是最关键的"杀"baseline：若 D3 不优于 B1，则 recovery 只是"功率稳定"的重新表述。
> B4 是 null control：任何有意义的方法都应优于 B4。

### 3.3 主指标：增量预测增益

对每个 trigger 方法 m，定义 post-recovery 窗口 W（冻结 W=10 cycle，1-min）与结局
Y_m(t) = "EV 在 [t+1, t+W] 内可支持更高权限"的代理：

```text
Y(t) = 1  若 actual_power(t+1 .. t+W) 的 Q50 >= recovery 时的 protective_bound
           （即恢复后 EV 确实持续承接接近边界水平的功率）
Y(t) = 0  否则（恢复后功率跌落，"更高权限"未被支持）
```

> Y 的代理用 actual 而非 EMS request（JPL 无真实 EMS request）；这是"可支持上界"的物理
> 代理，不依赖任何合成 request。

**主指标 Δ(m)** = D3 原方法的预测增益减去 baseline m 的预测增益：

```text
gain(m)     = P(Y=1 | trigger=m)  （该 trigger 命中时点中 Y=1 的比例）
Δ(B1)       = gain(B0) − gain(B1)    （D3 相对 persistence 的增量）
Δ(B3)       = gain(B0) − gain(B3)    （D3 相对随机匹配的增量）
```

**PASS 条件**（全部满足）：
1. Δ(B1) 的 cluster bootstrap 95%CI 下界 > 0（D3 严格优于 persistence）；
2. Δ(B3) 的 cluster bootstrap 95%CI 下界 > 0（D3 严格优于随机匹配）；
3. gain(B0) > gain(B4)（D3 优于 null control，sanity）。

**FAIL 条件**（任一成立 → D3 No-Go）：
1. Δ(B1) 的 95%CI 包含 0（D3 无 persistence 增量）；
2. Δ(B3) 的 95%CI 包含 0（D3 无随机匹配增量）；
3. gain(B0) <= gain(B4)（D3 不优于 null control，trigger 无意义）。

> cluster bootstrap：按 session_id 聚类重采样（不把 cycle 当独立样本）；报告绝对量
> gain(m) 与相对量 Δ(m) 同报；必须报最差站点/月份。

### 3.4 次要分析（不入门，仅诊断）

- 不同 W（5/10/20 cycle）下 Δ(B1) 的稳健性；
- recovery 后 actual 力轨迹的 before/after 可视化（20 个案例）；
- B2（rolling median/max）是否与 B0 接近（若接近，说明 Q95 无特殊价值）。

---

## 4. P2.1B 实验设计（D2 Closed-Loop / HIL，**仅 A PASS 后运行**）

### 4.1 最小独立闭环结构

```text
EMS request generator（独立 controller，非内部枚举 probe）
        ↓ requested_delta
D2 action gate（D1+D2+D3）
        ↓ clipped delta → EV
EV response emulator（独立于 gate，calibrated on data）
        ↓ actual_power
measurement → boundary / state（D1/D3）
        └─────────── feedback → 下一周期 EMS request
```

**独立性红线**：
- EMS request generator 不得为"让 clip 生效"而枚举 `-3/-1.5/0/+1.5/+3`（P2 的做法）；
  必须是独立的 controller（如简单 PI 跟踪一个站级功率目标）；
- EV response emulator 不得用 gate 内部逻辑反推；用数据校准的响应模型（如 actual =
  f(requested, noise)），**独立于 D2 gate**；
- 闭环运行若干周期，产生 actual 时序。

### 4.2 三臂比较

```text
Arm 0  Baseline             unrestricted correction（无 D2 gate）
Arm 1  D1+D2                有信息类别分级 + 预算修正允许区间，但无 D3 recovery
Arm 2  D1+D2+D3             完整设备动作链
```

### 4.3 物理控制指标（**完全不做经济收益**）

```text
infeasible command rate        超出 EV 可执行范围的 EMS 命令比例
boundary violation             实际功率越过 protective boundary 的 cycle 比例
unsupported positive corr      PROTECTIVE 段出现正向 unsupported release 的比例
tracking residual              |actual − requested|（或 |actual − budget|）的统计
unnecessary protective dur     不必要的保护性持续时间（可支持却仍 PROTECTIVE）
```

**PASS 条件**（Arm 2 vs Arm 0，全部满足）：
1. infeasible command rate：Arm 2 严格低于 Arm 0（95%CI 下界 < 0）；
2. boundary violation：Arm 2 严格低于 Arm 0；
3. unsupported positive correction rate：Arm 2 = 0（M4 不变量维持）；
4. tracking residual：Arm 2 不显著差于 Arm 0（gate 不应显著恶化跟踪）。

**FAIL 条件**（任一成立 → D2 No-Go）：
1. Arm 2 的 infeasible / boundary violation 不优于 Arm 0；
2. Arm 2 出现 unsupported positive correction（M4 不变量破坏）；
3. Arm 2 tracking residual 显著恶化（gate 把跟踪搞坏）。

> Arm 1 vs Arm 0：诊断 D3 的边际价值（若 Arm 2 PASS 但 Arm 1 也 PASS，D3 无独立价值，
> 降为从属）。**完全不要加 PV / BESS / 电价 / 经济收益指标。**

---

## 5. Success / Conditional / No-Go criteria（字段 6）

| 结果 | 判定 | 条件 |
|---|---|---|
| **A PASS** | D3 有增量辨识力 | Δ(B1) 与 Δ(B3) 的 95%CI 下界均 > 0；gain(B0)>gain(B4) |
| **A FAIL** | D3 No-Go | 任一 FAIL 条件成立 → 原发明核重新 Patent Gate（极可能 Project No-Go） |
| **B PASS** | D2 有技术效果 | A PASS 后，Arm 2 vs Arm 0 全部 PASS 条件成立 |
| **B FAIL** | D2 No-Go | 任一 FAIL 条件成立 → Project No-Go |
| **A Conditional** | 追加证据 | Δ(B1) 95%CI 下界 == 0 但点估计 > 0 且 B4 sanity 过——可追加 train 子集或新数据，不自动升 formal |

**穷尽映射**：
```text
A FAIL → D3 No-Go → 重判 Patent Gate（D3 区别锚消失，ACN 族可行性放松区别也弱化）→ 极可能 Project No-Go
A PASS, B FAIL → D2 No-Go → Project No-Go
A PASS, B PASS → 进入专利代理师检索（ACN element-mapping + EP/CNIPA + ISO 15118）→ FILING GO 候选
A Conditional → 追加 train 证据或新数据；不升级 formal；P3 仍 HOLD
```

---

## 6. Forbidden post-hoc actions（字段 7）

- 禁止调 D3 trigger 参数（0.95 / 3 cycle / Q95 / 15 min / min_history_samples）；
- 禁止加 classifier / confidence score / 双时间尺度 / learned trigger 救 D3；
- 禁止把 P2 formal test（已 consumed）重新用于阈值选择 / 规则修改；
- 禁止在 P2.1A 失败后"换一个 trigger 再试"（先 No-Go，再新版本协议）；
- 禁止在 P2.1B 引入 PV / BESS / 电价 / 经济收益指标或据此宣称站级收益；
- 禁止用 EV response emulator 反推 gate 参数（emulator 独立于 gate）；
- 禁止把 train 域 falsification 结果宣称"独立验证"（无新数据时不升级证据等级）；
- 禁止在 A FAIL 后运行 B（A 是 B 的前置硬门）。

---

## 7. Patent consequence if failed（字段 8）

| 失败点 | 专利后果 | registry |
|---|---|---|
| A FAIL（D3 无增量辨识力） | CLAIM 1 第 8/9 步 + CLAIM 5"实测响应驱动恢复"删除 → 恢复仅剩通信/停充/电池内部（prior art 已覆盖）→ 极可能 Project No-Go | P-003 降 D；D3 区别锚消失 |
| B FAIL（D2 无技术效果） | CLAIM 1 第 5/6 步"预算修正允许区间"退化为抽象措辞 → 按 Patent Gate 2 硬杀线 Project No-Go | P-002 降 D |
| A Conditional | CLAIM 5 维持但标注"trigger 语义有效性 train 域有条件成立"，不升 formal | P-003 维持 C（有条件） |

**两 gate 全 PASS 的后果**：P-003 升 C（trigger 语义有效性验证，仍非独立数据验证）；
P-002 维持 C（技术效果验证）；进入专利代理师检索；P3 仍不自动开。

---

## 8. 冻结与治理（字段 9-11）

```text
冻结项     本文件 v1.0 + D3 trigger 参数（§2）+ baselines（§3.2）+ Y/W 定义（§3.3）
           + 闭环结构（§4.1）+ 三臂（§4.2）+ 指标（§4.3）
SHA 锁定   implementation code SHA + protocol SHA + clean worktree
sentinel   P2.1A formal exposure sentinel（一次 consumed 后永久禁止 rerun）
数据域     P2.1A = JPL train only；P2.1B = 仿真闭环（无真实站点数据消费）
测试集     P2 frozen test 不重新使用；P2.1 不产生"独立 test"声明（除非新数据域）
```

**变更控制**：任何改动（参数、baseline、指标、阈值、闭环结构）须新版本 + 新测试协议，
走与 evidence freeze 相同的 Review 链；test 暴露后零改动。

**实施前置**：本协议 v1.0 须通过 Review（只核冻结项是否闭合、D3 trigger 是否真冻结、
baseline 是否真 adversarial）→ 才可写 P2.1A 代码；P2.1A 结果先评审 → 才可运行 P2.1B。

---

## 9. 不做什么（scope discipline）

- **不做** P3 大规模实验、不接真实光伏/储能/现场 EMS；
- **不做** active redistribution / 站级优化 / 经济收益；
- **不做** ML 模型 / classifier / learned trigger；
- **不做** "把 D3 调到 PASS"——目标是杀，不是救；
- **不重新** 消费 P2 formal test。

本协议的唯一目的：**尽最大可能把现有 D3/D2 发明核杀掉；杀不掉，才值得进入正式专利投入。**
