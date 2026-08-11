# P2.1 Preregistration v1.1 — D3 Falsification + D2 Technical-Effect Closed-Loop SIL Gate

> 日期：2026-08-12（v1.1 草案，待 Review 通过后冻结）
> 依据：P2 formal = SUCCESS / NARROW GO（`results/raw/phase3_p2/P2_patent_gate.md`，
> mechanism realizability only）；审查 2608120033 第一轮（`review/项目现状2608120033.md`）
> + 第二轮（v1.0→v1.1 六项协议级修订）。
> **P3 继续 HOLD**。本协议不"继续优化"，**专门杀这个发明核**。
> 本文件不是法律意见；最终以专利代理师意见为准。

---

## 0. v1.1 changelog（审查第二轮六项修订，全部冻结）

```text
P0-1  A：定义统一 eligible risk set，B0~B4 共用；每个 M3 segment 最多取第一个
      qualifying trigger（D3 recovery 单向，一个 segment 只恢复一次）。
P0-2  A：B1 ε 机械冻结（max−min ≤ 5%×median，连续 3 cycle）；B2 拆 B2a rolling-median /
      B2b rolling-max，"或"删除；adversarial comparator = max(gain(B2a), gain(B2b)) 机械规则。
P0-3  A：Y 语义从"支持更高权限"收紧为 future boundary-support persistence；A PASS 只证明
      D3 trigger 非简单 persistence 同义改写、对后续边界支持持续性有增量预测力，不直接
      证明真实 upward EMS correction 可执行（交给 B）。加 coverage/latency non-inferiority
      防 D3 靠"极端保守只在最易时刻触发"换 precision。
P0-4  A：删除"追加 train 子集"Conditional 后门；改为预先机械数据充分性检查
      （看 Y 之前判定 DATA INSUFFICIENT/HOLD），三态 PASS/FAIL/DATA INSUFFICIENT。
P0-5  B：修正 CI 方向错误。Δ = Arm2 − Arm0；"Arm2 严格更低"要求 CI_upper(Δ) < −δ，
      不是 CI_lower < 0。
P0-6  B：引入预冻结 minimum technical effect（MCID）+ non-inferiority margins；
      PASS = CI_upper(Δ) < −δ（效果）或 CI_upper(Δ) < δ_ni（非劣），不是仅 < 0。

补充冻结（审查 §9-§14）：
  - B：infeasible 基于 emulator 独立 ground truth C_true(t)，不是 D2 自己的 boundary（防 M2 自证）；
  - B：unsupported positive correction=0 移出 superiority gate，改 safety invariant（PROTECTIVE U=0 必然）；
  - B：boundary violation 重定义为 post-gate command 越过 C_true（latent feasible envelope），非 actual 越 protective boundary；
  - B：emulator family / C_true 生成 / lag / saturation / noise / calibration / scenario bank / paired seeds 全部冻结；三臂共享同一 latent EV trajectory + disturbance（paired counterfactual）；
  - B：Arm1 机械定义（M3 default PROTECTIVE，整段永不 NORMAL，仅 mode/run reset 重初始化）；
  - B：标题 HIL → Closed-loop SIL（无真实硬件，避免表述过度）；
  - B：Arm2 vs Arm1 = recovery value（D3 是否降低 unnecessary protective duration 且不增加 infeasible）。
```

> v1.1 **未改动**：D3 trigger 冻结参数（§2）、A→B 前置硬门、禁止调参救场、JPL train only、
> P2 frozen test 不重用、不引入 ML/PV/BESS/经济收益——均沿用 v1.0。

---

## 1. 为什么是 P2.1 而不是 P3

P2 证明 D1/D2/D3 设备动作链**机制可实现**（M1/M2/M4 实现正确性 + M3 natural 1,060 会话）。
但 P2 **没有**证明：

1. D3 的 boundary-contact recovery trigger 包含超过"简单功率持续性"的**增量信息**
   （rolling-Q95 自相关伪证据风险：恒定 5kW 单测即触发 recovery）；
2. D2 的"预算修正允许区间"在独立闭环中产生**真实物理控制效果**，而非仅把已有约束
   换成 "permission / allowed range" 表述（P2 的 requested_delta 是内部枚举 probe，非
   真实 EMS request）。

这两点打不穿 → **Project No-Go**。P2.1 由两个连续 kill gate 组成，**A PASS 才运行 B**：

```text
P2.1A  D3 Falsification     recovery trigger 是否有超过 persistence 的增量辨识力？
        ↓ FAIL              D3 No-Go → 极可能 Project No-Go
        ↓ PASS
P2.1B  D2 Closed-loop SIL   D1+D2+D3 是否在独立闭环产生真实物理控制效果？
        ↓ FAIL              D2 No-Go → Project No-Go
        ↓ PASS
专利代理师检索（ACN element-mapping + EP/CNIPA + ISO 15118）→ FILING GO 候选
```

---

## 2. 研究问题与假设（字段 1）

### P2.1A — D3 Falsification

**问题**：D3 boundary-contact recovery trigger（`protective_bound>0 且 actual ≥ 0.95×boundary
连续 3 cycle`）对 recovery 之后一段时间**未来边界支持持续性**的预测，是否具有**超过简单
功率持续性 baseline 的增量预测力**？

**可证伪假设 H_A**：在冻结 JPL train 域、统一 eligible risk set 上，D3 trigger 对
future boundary-support persistence 的预测增益，**严格大于**最强简单 persistence baseline
（B1）与随机时点匹配 baseline（B3），且满足 coverage/latency non-inferiority（不靠选择性
触发换 precision）。

**零假设 H_A0**：D3 trigger 的预测增益**不优于** B1，或**不优于** B3，或违反 coverage/
latency non-inferiority。H_A0 成立 → D3 无增量辨识力 → **D3 No-Go**。

> **A PASS 的语义边界**：A PASS 只证明 D3 trigger 不是简单 persistence 的同义改写、并对
> 后续边界支持持续性有增量预测力；**不直接证明真实 upward EMS correction 可执行**（JPL
> 无真实 upward request；恒定 5kW 未来继续 5kW 满足 Y=1，但不知 EMS 要求 6kW 时是否响应）。
> "权限提升后控制是否有效"交给 B。

### P2.1B — D2 Technical-Effect Closed-Loop SIL

**问题**：在独立 EMS request generator + 独立 EV response emulator（含独立 latent
capability C_true(t)）的最小闭环中，D1+D2+D3 相对 unrestricted correction baseline，
是否产生**超过预冻结最小技术效果（δ）的物理控制改善**？

**可证伪假设 H_B**：Arm2（D1+D2+D3）相对 Arm0（unrestricted）在 infeasible command rate、
boundary violation 上改善 ≥ δ，且 tracking residual non-inferior；Arm2 相对 Arm1（无 D3）
降低 unnecessary protective duration ≥ δ（D3 的独立价值）。

**零假设 H_B0**：任一 superiority 条件不成立或 non-inferiority 被违反。→ **D2 No-Go**。

---

## 3. 冻结的 D3 trigger 参数（**禁止调参救场**）

```text
protective_bound      Q95 of actual_power history（shift(1) 因果化，窗口 15 min）
recovery condition    protective_bound > 0 AND actual >= 0.95 × protective_bound
                      连续 3 cycle（1-min cycle）
min_history_samples   5
```

> **审查红线**：若 D3 不优于 persistence baseline，**不得**调 0.95、不得改 3 cycles、不得
> 加 classifier / confidence score / 双时间尺度 / learned trigger 救它。先走 D3 No-Go，
> 再按版本化协议变更。本协议冻结上述参数，P2.1A 全程零改动。

---

## 4. P2.1A 实验设计（D3 Falsification）

### 4.1 数据域（**JPL train only**）

```text
development / falsification 域   JPL train（P2 冻结 split 的 train 部分，current-only）
P2 formal test（已 consumed）     frozen historical evidence only
                                  禁止重新用于阈值选择 / 规则修改 / trigger 调参
新独立数据（若升级 formal）       必须使用新 untouched cohort / 新数据域
```

> **数据治理红线**：P2.1A 只在 JPL train 域做 falsification。无新独立数据时，诚实写
> "P2.1A survived falsification on frozen train domain"，**证据等级不升级为 independent
> validation**。禁止 post-hoc 追加 train 子集（见 §6）。

### 4.2 统一 eligible risk set（P0-1；所有 trigger 共用）

```text
site                JPL train（current-only）
run                 未 severe-gap reset（绑定 E0 severe_gap_before）
history_count       >= 5（M3 可评价）
protective_bound    > 0
trigger 候选 t      当前 cycle 属于 M3 可评价区间
post-window         t+1 .. t+W（W=10）内无 disconnect / severe gap / run reset
                    （确保 Y 可计算）
```

**每 M3 segment 最多取第一个 qualifying trigger**（D3 recovery 单向，一个 segment 只恢复
一次；避免某 baseline 一条 session 触发 20 次而另一方法只 1 次，导致 gain() 权重失配）。

> B0~B4 **全部只能在同一 risk set 内取 trigger**。这是 P0-1 的核心：消除"不同方法挑不同
> 时段"的 confound（D3 天然倾向 session 晚段/稳定高平台，persistence 可能更早触发）。

### 4.3 Adversarial baselines（P0-2；机械冻结，无自由度）

对同一 eligible risk set，用以下方法各自产生 trigger 时点（每 segment 取第一个）：

```text
B0  D3 original          原冻结 trigger（actual >= 0.95×Q95_boundary，连续 3 cycle）
B1  simple persistence   连续 3 cycle，max(actual) − min(actual) <= 5% × median(actual_3cycle)
                         （机械冻结 ε = 5%×median；"功率稳定几分钟"）
B2a rolling median       actual >= rolling_median(actual, window=15min, shift(1))，连续 3 cycle
B2b rolling max          actual >= rolling_max(actual, window=15min, shift(1))，连续 3 cycle
    B2 adversarial       = argmax_{B2a,B2b} gain(·)（机械规则：取更强者为 adversarial
                         comparator；报告两者，不 post-hoc 选）
B3  random matched       在同 charging phase 长度区间内均匀随机选时点（phase 长度匹配）
B4  lag/time-shuffle     用 actual 的 lag(1)/shuffle 版本触发（破坏时序关系，null control）
```

> B1 是最关键的"杀"baseline（D3 不优于 B1 → recovery 只是"功率稳定"的重新表述）；
> B4 是 null control（任何有意义方法都应优于 B4）。
> **"或"已删除**：B1 的 ε、B2 的 median/max 全部机械冻结或机械规则选取。

### 4.4 主指标：增量预测增益（P0-3；Y 语义收紧）

**Outcome Y（future boundary-support persistence）**：

```text
Y(t) = 1  若 actual_power(t+1 .. t+W) 的 Q50 >= 0.9 × protective_bound(t)
           （trigger 后 W=10 cycle 内，功率持续保持在 trigger 时保护边界附近）
Y(t) = 0  否则（恢复后功率跌落，边界支持未持续）
```

> 冻结 0.9 与 W=10。Y 是**物理代理**（用 actual，不依赖任何合成 request）；语义为"未来
> 边界支持持续性"，**不是**"已证明可执行更高权限"（见 §2 H_A 语义边界）。

**预测增益**：

```text
gain(m)     = P(Y=1 | trigger=m)            （该 trigger 命中时点中 Y=1 的比例）
Δ(B1)       = gain(B0) − gain(B1)           （D3 相对 persistence 的增量）
Δ(B2)       = gain(B0) − gain(B2 adversarial)
Δ(B3)       = gain(B0) − gain(B3)           （D3 相对随机匹配的增量）
```

**Coverage / latency non-inferiority（P0-3；防选择性触发）**：

```text
coverage(m)         = n_trigger(m) / n_eligible_segments
latency(m)          = median(trigger cycle index within segment)
```

D3 不得靠显著降低 coverage 或大幅延迟 recovery 换更高 precision。冻结 non-inferiority margin：
```text
coverage(B0) >= 0.8 × coverage(B1)            （D3 触发数不少于 persistence 的 80%）
latency(B0)  <= latency(B1) + 3 cycles        （D3 触发不晚于 persistence 3 cycle 以上）
```

**PASS 条件（A，全部满足）**：
1. Δ(B1) 的 cluster bootstrap 95%CI **下界** > 0（D3 严格优于 persistence）；
2. Δ(B3) 的 95%CI 下界 > 0（D3 严格优于随机匹配）；
3. gain(B0) > gain(B4)（null control sanity）；
4. coverage non-inferiority 成立（B0 >= 0.8×B1）；
5. latency non-inferiority 成立（B0 <= B1+3）；
6. Δ(B2) 的 95%CI 下界 > 0（D3 优于最强 rolling baseline；诊断性加严门，防止 Q95 无特殊价值）。

**FAIL 条件（A，任一成立 → D3 No-Go）**：
1. Δ(B1) 的 95%CI 包含 0；
2. Δ(B3) 的 95%CI 包含 0；
3. gain(B0) <= gain(B4)（trigger 无意义）；
4. coverage 或 latency non-inferiority 违反（D3 靠选择性触发换 precision）；
5. Δ(B2) 的 95%CI 包含 0（Q95 无增量；诊断性 FAIL）。

> cluster bootstrap：按 session_id 聚类重采样（不把 cycle 当独立样本）；报告绝对量 gain(m)
> 与相对量 Δ(m) 同报；必须报最差站点/月份；至少 20 个失败案例可视化。

### 4.5 次要分析（不入门，仅诊断）

- 不同 W（5/10/20 cycle）下 Δ(B1) 的稳健性；
- recovery 后 actual 力轨迹 before/after 可视化（20 个案例）；
- B2a vs B2b gap（若接近，说明 rolling 族内部无差别）。

---

## 5. P2.1A 数据充分性检查（P0-4；预先机械，看 Y 之前判定）

**在看任何 Y 结果之前**，按以下机械阈值判定数据充分性：

```text
eligible M3 segments        >= 100
B0 trigger sessions         >= 30
B1 trigger sessions         >= 30
B3 trigger sessions         >= 30
```

- 任一不满足 → **DATA INSUFFICIENT / HOLD**：不计算正式 Gate，不判 PASS/FAIL；
- 全部满足 → 进入正式 PASS/FAIL 判定（§4.4）。

> **删除 v1.0 的 Conditional 后门**：禁止"点估计>0 但 CI 下界==0 → 追加 train 子集"。
> 数据不够 = HOLD（需新协议版本 + 新数据域）；数据够 = 二态 PASS/FAIL，无中间态。
> 这关闭了"看结果再选数据"的自由度。

---

## 6. P2.1B 实验设计（D2 Closed-Loop SIL，**仅 A PASS 后运行**）

### 6.1 最小独立闭环结构（P0-6；emulator 独立 ground truth）

```text
EMS request generator（独立 controller，非内部枚举 probe）
        ↓ requested_delta
D2 action gate（D1+D2+D3 / 或按 arm 禁用部分）
        ↓ command_after_gate(t)
EV response emulator（独立于 gate，含 latent capability C_true(t)）
        ↓ actual_power(t) = min(C_true(t), command_after_gate(t)) 的带 lag/saturation/noise 响应
measurement → boundary / state（D1/D3）
        └─────────── feedback → 下一周期 EMS request
```

**独立性红线**：
- EMS request generator 不得为"让 clip 生效"而枚举 probe；用独立 PI controller 跟踪一个站级
  功率目标（目标轨迹冻结）；
- EV response emulator 不得用 gate 内部逻辑反推；emulator 拥有**独立 ground truth C_true(t)**
  （latent capability），gate 不知道 C_true；
- 闭环产生 actual 时序。

### 6.2 Emulator 冻结（P0-6；防自证）

```text
emulator family       actual(t) = min(C_true(t), command_after_gate(t − lag)) × (1 + noise)
                      （saturation：actual 不超 C_true；lag：EV 不瞬时响应）
lag                   1 cycle（1 min）
noise                 乘性 Gaussian σ=0.05（5%），floor at 0
C_true(t) 生成        从 JPL train session actual_power_kw 轨迹 bootstrap 采样作为 latent
                      capability 轨迹（数据锚定，非人为造），可选 drift（冻结 drift=0）
calibration source    JPL train actual_power_kw 分布
calibration/validation 用 train 内 split（不碰 P2 frozen test）
scenario bank         N=300 scenarios，从 JPL train sessions 采样（冻结 seed=20260812）
paired seeds          scenario i 用 seed i；Arm0/1/2 共享同一 C_true(t)、noise(t)、
                      EMS target(t)、初始状态、session duration——只改 gate 有无
                      （paired counterfactual）
```

> **关键**：三臂共享完全相同的 latent EV trajectory + disturbance，只改 gate。这才是真正的
> paired counterfactual；否则 emulator 选择本身可能决定 D2 是否 PASS。

### 6.3 三臂（Arm1 机械定义，P0-6/§12）

```text
Arm 0  Baseline       unrestricted correction（无 D2 gate）
Arm 1  D1+D2          有信息类别分级 + 预算修正允许区间，但无 D3 recovery
                      机械定义：M3 default = PROTECTIVE，整个连续 M3 segment 永不进入 NORMAL，
                      仅 mode/run reset 按 D1 重新初始化（真正"有 D2 无 D3"）
Arm 2  D1+D2+D3       完整设备动作链
```

### 6.4 物理控制指标（P0-5/P0-6/§9；CI 方向修正 + MCID + 独立 C_true）

所有差值定义 Δ = Arm2 − Arm0（或 Arm2 − Arm1）；bootstrap 95%CI。

```text
Δ_inf       = rate_infeasible(Arm2) − rate_infeasible(Arm0)
              infeasible 定义：command_after_gate(t) > C_true(t) + tol（基于 emulator 独立
              ground truth，不是 D2 自己的 boundary；防 M2 自证）
              tol 冻结 = 0.1 kW

Δ_violation = rate_violation(Arm2) − rate_violation(Arm0)
              violation 定义：command_after_gate(t) > C_true(t)（越过 latent feasible
              envelope；非 actual 越 protective boundary——后者只说明边界保守，方向不明）

safety_invariant  unsupported_positive_correction_rate(Arm2) == 0
              （PROTECTIVE U=0 必然为 0，是 controller invariant / regression check，
              不作 superiority gate）

Δ_tracking = tracking_residual(Arm2) − tracking_residual(Arm0)
              tracking_residual = median|actual − requested|（或 |actual − budget|）

Δ_unnec_prot (recovery value) = unnecessary_protective_duration(Arm2) − (Arm1)
              unnecessary_protective_duration = PROTECTIVE 段中实际可支持（C_true 高于
              当时 command）却仍 PROTECTIVE 的 cycle 数
              （回答"为什么不能永远 PROTECTIVE"——D3 的独立价值）
```

**预冻结 margins（MCID + non-inferiority）**：
```text
δ_inf               = 0.02（Arm2 infeasible rate 绝对降低 >= 2pp）
δ_violation         = 0.02（Arm2 violation rate 绝对降低 >= 2pp）
δ_track_ni          = 0.3 kW（Arm2 tracking residual 不恶化超过 0.3 kW）
δ_prot              = 3 cycle（Arm2 unnecessary protective duration 比 Arm1 少 >= 3 cycle/segment）
δ_inf_ni (Arm2vs1)  = 0.005（Arm2 infeasible 不比 Arm1 差超过 0.5pp；recovery 不引入新 infeasible）
```

### 6.5 PASS / FAIL 条件（B；CI 方向已修正，P0-5）

**Primary effect（Arm2 vs Arm0，全部满足）**：
1. Δ_inf：95%CI **上界** < −δ_inf（Arm2 infeasible 显著更低，降幅 ≥ 2pp）；
2. Δ_violation：95%CI 上界 < −δ_violation（Arm2 violation 显著更低）；
3. safety_invariant：unsupported_positive_correction_rate(Arm2) == 0（M4 不变量维持）；
4. Δ_tracking：95%CI 上界 < δ_track_ni（Arm2 tracking non-inferior，不恶化超 0.3 kW）。

**Recovery value（Arm2 vs Arm1）**：
5. Δ_unnec_prot：95%CI 上界 < −δ_prot（Arm2 比 Arm1 少 ≥ 3 cycle unnecessary protective；
   D3 的独立价值）；
6. Δ_inf(Arm2−Arm1)：95%CI 上界 < δ_inf_ni（Arm2 infeasible 不比 Arm1 差；recovery 不引入新 infeasible）。

**FAIL 条件（B，任一成立 → D2 No-Go）**：
1. Δ_inf：CI 上界 >= −δ_inf（无 ≥ 2pp 改善）；
2. Δ_violation：CI 上界 >= −δ_violation；
3. safety_invariant 违反（Arm2 出现 unsupported positive correction）；
4. Δ_tracking：CI 上界 >= δ_track_ni（gate 把跟踪搞坏）；
5. Δ_unnec_prot：CI 上界 >= −δ_prot（D3 无独立价值 → CLAIM 5 降为弱从属）；
6. Δ_inf(Arm2−Arm1)：CI 上界 >= δ_inf_ni（recovery 引入新 infeasible）。

> Arm1 vs Arm0 仅诊断（若 Arm2 PASS 但 Arm1 也 PASS，D3 无独立技术价值，CLAIM 5 降为弱从属，
> 不自动 Project No-Go）。**完全不要加 PV / BESS / 电价 / 经济收益指标。**

---

## 7. Success / Conditional / No-Go criteria（字段 6；三态，无 Conditional 后门）

| 结果 | 判定 | 条件 |
|---|---|---|
| **A PASS** | D3 有增量辨识力 | 数据充分 + §4.4 PASS 全部满足 |
| **A FAIL** | D3 No-Go | §4.4 任一 FAIL 成立 → 极可能 Project No-Go |
| **A DATA INSUFFICIENT** | HOLD | §5 机械阈值不满足（看 Y 之前判定）；需新协议版本 + 新数据 |
| **B PASS** | D2 有技术效果 | A PASS 后，§6.5 Primary + Recovery value 全部满足 |
| **B FAIL** | D2 No-Go | §6.5 任一 FAIL 成立 → Project No-Go |

**穷尽映射**：
```text
A DATA INSUFFICIENT → HOLD（新协议 + 新数据；不判 No-Go，也不 PASS）
A FAIL → D3 No-Go → 重判 Patent Gate（D3 区别锚消失）→ 极可能 Project No-Go
A PASS, B FAIL → D2 No-Go → Project No-Go
A PASS, B PASS, Arm1 also PASS → D2 有效但 D3 无独立技术价值 → CLAIM 5 降弱从属，进代理师检索
A PASS, B PASS, Arm2>Arm1 → D3 有独立价值 → 进代理师检索（FILING GO 候选）
```

---

## 8. Forbidden post-hoc actions（字段 7）

- 禁止调 D3 trigger 参数（0.95 / 3 cycle / Q95 / 15 min / min_history_samples）；
- 禁止加 classifier / confidence score / 双时间尺度 / learned trigger 救 D3；
- 禁止把 P2 formal test（已 consumed）重新用于阈值选择 / 规则修改；
- 禁止在 P2.1A 失败后"换一个 trigger 再试"（先 No-Go，再新版本协议）；
- 禁止 **post-hoc 追加 train 子集**（数据不够 = DATA INSUFFICIENT/HOLD，不"再找数据"）；
- 禁止调 B1 ε / B2 median-max 选择 / B2 adversarial 选取规则（已冻结）；
- 禁止调 emulator family / C_true 生成 / lag / saturation / noise / scenario bank / δ margins；
- 禁止在 P2.1B 引入 PV / BESS / 电价 / 经济收益指标或据此宣称站级收益；
- 禁止用 EV response emulator 反推 gate 参数（emulator 独立于 gate；infeasible 基于 C_true
  非 D2 boundary）；
- 禁止把 train 域 falsification 结果宣称"独立验证"（无新数据时不升级证据等级）；
- 禁止在 A FAIL/DATA INSUFFICIENT 后运行 B（A 是 B 前置硬门）。

---

## 9. Patent consequence if failed（字段 8）

| 失败点 | 专利后果 | registry |
|---|---|---|
| A FAIL（D3 无增量辨识力） | CLAIM 1 第 8/9 步 + CLAIM 5"实测响应驱动恢复"删除 → 恢复仅剩通信/停充/电池内部（prior art 已覆盖）→ 极可能 Project No-Go | P-003 降 D |
| A DATA INSUFFICIENT | HOLD；CLAIM 5 维持"机制已观测；trigger 语义有效性 train 域证据不足"，不升不降 | P-003 维持 C（有条件） |
| B FAIL（D2 无技术效果） | CLAIM 1 第 5/6 步"预算修正允许区间"退化为抽象措辞 → 按 Patent Gate 2 硬杀线 Project No-Go | P-002 降 D |
| B PASS 但 Arm1 also PASS（D3 无独立价值） | CLAIM 5 降为弱从属（非强从属）；D3 区别锚弱化，代理师检索时 ACN 族风险升高 | P-003 降 C-（弱） |

**两 gate 全 PASS 且 Arm2>Arm1 的后果**：P-003 升 C（trigger 语义有效性 train 域验证，仍非
独立数据验证）；P-002 维持 C（技术效果验证）；进入专利代理师检索；P3 仍不自动开。

---

## 10. 冻结与治理（字段 9-11）

```text
冻结项     本文件 v1.1 + D3 trigger 参数（§3）+ eligible risk set（§4.2）+ baselines（§4.3）
           + Y/W/0.9（§4.4）+ coverage/latency margins（§4.4）+ 数据充分性阈值（§5）
           + emulator 全项（§6.2）+ Arm 定义（§6.3）+ 指标与 δ margins（§6.4）
SHA 锁定   implementation code SHA + protocol SHA + clean worktree
sentinel   P2.1A formal exposure sentinel（一次 consumed 后永久禁止 rerun）
数据域     P2.1A = JPL train only；P2.1B = 仿真闭环（C_true 从 JPL train bootstrap，无真实站点数据消费）
测试集     P2 frozen test 不重新使用；P2.1 不产生"独立 test"声明（除非新数据域）
```

**变更控制**：任何改动（参数、baseline、指标、阈值、emulator、δ margins、risk set）须新
版本 + 新测试协议，走与 evidence freeze 相同的 Review 链；test 暴露后零改动。

**实施前置**：本协议 v1.1 须通过 Freeze Review（核冻结项是否闭合、D3 参数真冻结、baseline
真 adversarial、emulator 真独立、δ margins 真预冻结）→ 才可写 P2.1A 代码；P2.1A 结果先评审
→ 才可运行 P2.1B。

---

## 11. 不做什么（scope discipline）

- **不做** P3 大规模实验、不接真实光伏/储能/现场 EMS、不接真实硬件（本协议是 Closed-loop
  **SIL**，非 HIL——避免实验类型表述过度）；
- **不做** active redistribution / 站级优化 / 经济收益；
- **不做** ML 模型 / classifier / learned trigger；
- **不做** "把 D3 调到 PASS"——目标是杀，不是救；
- **不重新** 消费 P2 formal test；
- **不 post-hoc** 追加 train 子集或调 emulator 救结果。

本协议的唯一目的：**尽最大可能把现有 D3/D2 发明核杀掉；杀不掉，才值得进入正式专利投入。**
