# P2.1 Preregistration v1.2 — D3 Falsification + D2 Technical-Effect Closed-Loop SIL Gate

> 日期：2026-08-12（v1.2 草案，待 Freeze Review 通过后冻结）
> 依据：P2 formal = SUCCESS / NARROW GO（`results/raw/phase3_p2/P2_patent_gate.md`，
> mechanism realizability only）；审查 2608120033 第一/二/三轮（`review/项目现状2608120033.md`）。
> **P3 继续 HOLD**。本协议不"继续优化"，**专门杀这个发明核**。
> 本文件不是法律意见；最终以专利代理师意见为准。

---

## 0. v1.2 changelog（审查第三轮八项协议闭环修订，全部冻结）

```text
F1  A：冻结 B3/B4 随机性（RNG seed/每 segment 抽样次数/charging phase 机械定义；B4 删除"或"
     统一为 lag(1) shuffle-null）；冻结 cluster bootstrap 算法（percentile、N_boot=2000、
     seed=20260813、resample 后重算每 segment 第一个 trigger）；B2 统计量定义为 functional
     Δ_B2 = gain(B0) − max[gain(B2a), gain(B2b)]，每个 bootstrap replicate 重算完整 functional
     （不先全样本选 B2a/B2b 再固定）；B2a/B2b/B4 纳入数据充分性。
F2  A："消除 confound"改为"控制并显式审计 trigger-selection / timing confound"（timing 仍是
     trigger 规则的一部分，不假装消除）。
F3  B：闭合动作语义 requested_delta → delta_exec → P_cmd（budget-correction chain），不再把
     "预算修正量"悄悄变成"EV 绝对功率命令"；infeasible/violation 基于 P_cmd vs C_true。
F4  B：修 emulator saturation 数学 bug（噪声后再 saturation：actual = min(C_true, max(0,
     P_cmd(t−lag)×(1+noise)))）；v1.1 的 min(C_true, cmd)×(1+noise) 在 noise>0 时会超 C_true。
F5  B：完全冻结 PI controller（Kp/Ki/integrator init/anti-windup/request clamp/target trajectory
     公式/P_base 更新/RNG seed）；三臂共享相同 controller + target。
F6  B：C_true ≠ true capability——重命名为 latent feasible-envelope proxy；采用方案 B
     （冻结多个 adverse C_true scenario families），证据边界限定为"数据锚定 synthetic envelope
     假设下的 closed-loop technical effect"。
F7  B：删除 tracking_residual 的"或"，唯一定义 median|actual − P_cmd|。
F8  B：B-core（Arm2 vs Arm0，D2 technical effect）与 B-recovery（Arm2 vs Arm1，D3 marginal
     recovery value）拆为两个独立 Gate；消除 §6.5"任一 FAIL→D2 No-Go"与 §7"Arm1 also PASS→
     仅降 CLAIM 5"的判定冲突。穷尽映射重写。
```

> v1.2 **未改动**：D3 trigger 冻结参数（§3）、A→B 前置硬门、禁止调参救场、JPL train only、
> P2 frozen test 不重用、不引入 ML/PV/BESS/经济收益、Y 语义（future boundary-support
> persistence）、coverage/latency non-inferiority、删除 Conditional 后门——均沿用 v1.1。

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
        ↓ FAIL / DATA INSUFFICIENT
        ↓ PASS only
P2.1B  D2 Closed-loop SIL   B-core (D2 effect) + B-recovery (D3 marginal value)
        ↓ B-core FAIL       D2 No-Go → Project No-Go
        ↓ B-core PASS
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

### P2.1B — D2 Technical-Effect Closed-Loop SIL（B-core + B-recovery 双 Gate）

**问题 B-core**：在独立 EMS controller + 独立 EV response emulator（含独立 latent
feasible-envelope proxy C_true(t)）的最小闭环中，D1+D2+D3 相对 unrestricted baseline，
是否产生**超过预冻结最小技术效果（δ）的物理控制改善**？

**问题 B-recovery**：D3 recovery 相对"永远 PROTECTIVE"（Arm1），是否在 B-core PASS 前提下
降低 unnecessary protective duration ≥ δ 且不引入新 infeasible？

**零假设 H_B0**：B-core 任一 superiority 条件不成立或 non-inferiority 被违反 → **D2 No-Go**。
**零假设 H_BR0**：B-recovery 不成立 → D3 无独立技术价值（CLAIM 5 降弱从属，但 B-core PASS
不回滚——D2 仍存活）。

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
> validation**。禁止 post-hoc 追加 train 子集（见 §5）。

### 4.2 统一 eligible risk set（F1/F2；所有 trigger 共用）

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

> B0~B4 **全部只能在同一 risk set 内取 trigger**。这**控制并显式审计 trigger-selection /
> timing confound**（F2）：统一 risk set + 每 segment 一触发 + coverage/latency non-inferiority
> 限制了 confound 并使其可审计；但 B0/B1 仍可能选不同 t（timing 本身是 trigger 规则的一部分），
> 故**不假装"消除"confound**。报告 B0/B1 触发时点分布差异作为审计材料。

### 4.3 Adversarial baselines（F1；机械冻结，无随机/选择自由度）

对同一 eligible risk set，用以下方法各自产生 trigger 时点（每 segment 取第一个）：

```text
B0  D3 original          原冻结 trigger（actual >= 0.95×Q95_boundary，连续 3 cycle）
B1  simple persistence   连续 3 cycle，max(actual) − min(actual) <= 5% × median(actual_3cycle)
                         （机械冻结 ε = 5%×median；"功率稳定几分钟"）
B2a rolling median       actual >= rolling_median(actual, window=15min, shift(1))，连续 3 cycle
B2b rolling max          actual >= rolling_max(actual, window=15min, shift(1))，连续 3 cycle
B3  random matched       charging phase = 同 session 内 M3 segment 的连续 cycle 区间
                         （机械定义：从该 segment 的第一个 eligible cycle 起，到 segment 末或
                         disconnect/severe gap 前的连续区间）；在该 phase 长度区间内用
                         冻结 RNG（seed=20260813_A）均匀抽 1 个时点；每 segment 抽 1 次
                         （不重复抽样取最优）
B4  lag-shuffle null     用 actual 的 lag(1) 版本触发 B0 条件（破坏当 cycle 与历史同时序
                         关系；"shuffle"语义统一为 lag(1)，删除 v1.1 的"lag(1)/shuffle"二选一）
```

> B1 是最关键的"杀"baseline（D3 不优于 B1 → recovery 只是"功率稳定"的重新表述）；
> B4 是 null control（任何有意义方法都应优于 B4）。
> **全部机械冻结**：B1 ε、B2 median/max、B3 RNG seed + phase 定义 + 每 segment 抽 1 次、
> B4 统一 lag(1)，无"或"、无 post-hoc 选择。

### 4.4 主指标：增量预测增益（F1；B2 functional + bootstrap 冻结）

**Outcome Y（future boundary-support persistence）**：

```text
Y(t) = 1  若 actual_power(t+1 .. t+W) 的 Q50 >= 0.9 × protective_bound(t)
           （trigger 后 W=10 cycle 内，功率持续保持在 trigger 时保护边界附近）
Y(t) = 0  否则（恢复后功率跌落，边界支持未持续）
```

> 冻结 0.9 与 W=10。Y 是**物理代理**（用 actual，不依赖任何合成 request）；语义为"未来
> 边界支持持续性"，**不是**"已证明可执行更高权限"（见 §2 H_A 语义边界）。

**预测增益与统计量（F1；B2 作为 functional）**：

```text
gain(m)     = P(Y=1 | trigger=m)            （该 trigger 命中时点中 Y=1 的比例）
Δ(B1)       = gain(B0) − gain(B1)
Δ(B3)       = gain(B0) − gain(B3)
Δ(B2)       = gain(B0) − max[gain(B2a), gain(B2b)]    ← functional，非先选后算
```

> **B2 统计量定义**：`Δ(B2) = gain(B0) − max[gain(B2a), gain(B2b)]` 是一个完整 functional。
> bootstrap 每个 replicate 重新计算 `max[gain(B2a), gain(B2b)]`（即哪个 rolling 子方法更强
> 在每个 replicate 内决定），**不**先在全样本固定 B2a 或 B2b 再当固定 comparator。这避免
> "全样本看一眼选强者再 bootstrap"的选择偏差。

**Coverage / latency non-inferiority（防选择性触发）**：

```text
coverage(m)         = n_trigger(m) / n_eligible_segments
latency(m)          = median(trigger cycle index within segment)
coverage(B0) >= 0.8 × coverage(B1)            （D3 触发数不少于 persistence 的 80%）
latency(B0)  <= latency(B1) + 3 cycles        （D3 触发不晚于 persistence 3 cycle 以上）
```

**Cluster bootstrap 冻结（F1）**：

```text
resample unit        session_id（不把 cycle 当独立样本）
method               percentile bootstrap
N_boot               2000
RNG seed             20260813_B（冻结）
per replicate        重采样 session 集合 → 在被抽中的 sessions 上重算每 segment 第一个
                     trigger → 重算 gain(m) → 重算 Δ(B1)/Δ(B3)/Δ(B2)（含 max[B2a,B2b]）
                     完整 functional
CI                   percentile 95%CI（[2.5%, 97.5%]）
```

**PASS 条件（A，全部满足）**：
1. Δ(B1) 的 95%CI **下界** > 0（D3 严格优于 persistence）；
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

> 报告绝对量 gain(m) 与相对量 Δ(m) 同报；必须报最差站点/月份；至少 20 个失败案例可视化；
> 报告 B0/B1 触发时点分布（timing confound 审计材料，F2）。

### 4.5 次要分析（不入门，仅诊断）

- 不同 W（5/10/20 cycle）下 Δ(B1) 的稳健性；
- recovery 后 actual 力轨迹 before/after 可视化（20 个案例）；
- B2a vs B2b gap（若接近，说明 rolling 族内部无差别）。

---

## 5. P2.1A 数据充分性检查（F1；B0-B4 全纳入，看 Y 之前判定）

**在看任何 Y 结果之前**，按以下机械阈值判定数据充分性：

```text
eligible M3 segments        >= 100
B0 trigger sessions         >= 30
B1 trigger sessions         >= 30
B2a trigger sessions        >= 30
B2b trigger sessions        >= 30
B3 trigger sessions         >= 30
B4 trigger sessions         >= 30
```

- 任一不满足 → **DATA INSUFFICIENT / HOLD**：不计算正式 Gate，不判 PASS/FAIL；
- 全部满足 → 进入正式 PASS/FAIL 判定（§4.4）。

> **B2a/B2b/B4 纳入数据充分性**（F1）：B2 是正式 FAIL gate、B4 是 sanity gate，均需足够
> trigger sessions 才能稳定估计。**删除 v1.0 的 Conditional 后门**：禁止"点估计>0 但 CI
> 下界==0 → 追加 train 子集"。数据不够 = HOLD（需新协议版本 + 新数据域）；数据够 = 二态
> PASS/FAIL，无中间态。

---

## 6. P2.1B 实验设计（D2 Closed-Loop SIL，**仅 A PASS 后运行**；B-core + B-recovery 双 Gate）

### 6.1 完整动作链（F3；闭合 budget-correction 语义）

> v1.1 把"预算修正量"悄悄变成"EV 绝对功率命令"——v1.2 明确完整动作链：

```text
P_base(t)             当前 EV budget（kW，随 controller 状态更新）
requested_delta(t)    EMS 请求的预算修正量（kW，可正可负）
  │
  ├─ Arm0:  delta_exec_0(t) = requested_delta(t)            （无 gate）
  ├─ Arm1:  delta_exec_1(t) = D2_gate(requested_delta, L, U, state=PROTECTIVE-frozen)
  └─ Arm2:  delta_exec_2(t) = D2_gate(requested_delta, L, U, state=D3-recovery)
  │
  ↓ delta_exec(t)
P_cmd(t) = clip(P_base(t) + delta_exec(t), 0, P_hw_max)
  │       （P_hw_max = 桩侧硬件上限，冻结=station rated；clip 保证非负 + 不超硬件）
  ↓
EV emulator 输入 = P_cmd(t)
  ↓ actual(t)（见 §6.2）
measurement → boundary / state（D1/D3）→ feedback → 下一周期 P_base / requested_delta
```

**关键**：D2 gate 控制的是 `delta_exec`（budget-correction permission），不是直接输出
`P_cmd`；`P_cmd = clip(P_base + delta_exec, 0, P_hw_max)` 是物理命令。这样 infeasible/
violation 指标测的是**经过 budget-correction chain 后的物理命令**是否越过 latent envelope，
与 CLAIM 1 第 5/6 步同构。

### 6.2 EV response emulator 冻结（F4；修 saturation 数学 bug + F6 C_true 解释）

```text
emulator family       P_resp_raw(t) = max(0, P_cmd(t − lag) × (1 + noise(t)))
                      actual(t)     = min(C_true(t), P_resp_raw(t))
                      （先乘性噪声，后 saturation 到 C_true；保证 actual <= C_true）
lag                   1 cycle（1 min）
noise                 乘性 Gaussian σ=0.05（5%），独立采样 per cycle，floor P_resp_raw at 0
P_hw_max              station rated power（冻结，与 P_base 上限一致）
```

> **F4 数学修正**：v1.1 的 `min(C_true, cmd)×(1+noise)` 在 noise>0 时 actual 可超 C_true
> （如 C_true=5, cmd=5, noise=+5% → actual=5.25）。v1.2 改为噪声后再 saturation：
> `actual = min(C_true, max(0, P_cmd(t−lag)×(1+noise)))`，保证 `actual <= C_true` 恒成立。

**C_true(t) — latent feasible-envelope proxy（F6；方案 B 多 adverse families）**：

> **F6 解释边界**：`C_true(t)` **不是** "vehicle true capability"——observed actual ≠ true
> capability（actual=4kW 可能因 EV 只能 4kW / pilot 限 4kW / 上游限 4kW / 车自请 4kW，而真实
> 可吸收能力可能是 7kW）。把历史 actual 直接当 C_true 会天然奖励"依据历史 actual 做保守
> gate"的 D2（emulator structural bias）。故：
> - **重命名**：C_true → **latent feasible-envelope proxy**（不称 ground truth capability）；
> - **方案 B（多 adverse families）**：冻结多个 C_true scenario families，让 D2 不只在
>   "actual 就是真能力上限"这个最有利假设下受攻击：

```text
family E1  data-anchored        C_true(t) = JPL train session actual_power_kw 轨迹 bootstrap
                                  （最保守 envelope：actual 即上限——对 D2 最有利）
family E2  uplift ×1.25         C_true(t) = E1 × 1.25（latent envelope 高于 observed actual
                                  25%——模拟"车其实能吸收更多但被 pilot/上游压住"）
family E3  uplift ×1.5          C_true(t) = E1 × 1.5
family E4  volatile envelope    C_true(t) = E1 × (1 + 0.2×sin(2πt/T))，T=30 cycle
                                  （envelope 自身波动——攻击 D2 在 envelope 时变下的稳健性）
```

- 每个 scenario 同时跑 E1–E4 四个 C_true family（同一 latent trajectory base，仅 envelope
  变换）；**B-core PASS 须在全部 4 个 family 上成立**（任一 family FAIL → D2 在该假设下
  无效果，记为 B-core conditional FAIL，触发 §7 穷尽映射）；
- scenario bank N=300（从 JPL train sessions 采样，冻结 seed=20260812）；
- 三臂共享同一 C_true family + 同一 latent trajectory base + noise + controller target
  （paired counterfactual，只改 gate）。

> **证据边界**：B-core PASS 的结论限定为"**在数据锚定 synthetic envelope 假设下的
> closed-loop technical effect**"；不宣称"真实车辆能力下的效果"（emulator 是 proxy，非
> 真实 capability）。

### 6.3 EMS PI controller 冻结（F5；三臂共享）

```text
controller formula    requested_delta(t) = Kp × e(t) + Ki × I(t)
                      e(t)    = P_target(t) − P_base(t)        （站级功率跟踪误差）
                      I(t)    = I(t−1) + e(t)                   （积分器）
Kp                    0.5（冻结）
Ki                    0.1（冻结）
integrator init       I(0) = 0
anti-windup           I(t) clamp to [−10, +10]（冻结，防积分饱和）
request clamp         requested_delta clamp to [−3, +3] kW（冻结，与 P2 probe 量级一致
                      但由 controller 独立产生，非枚举）
P_base(t) 更新        P_base(t+1) = P_base(t) + delta_exec(t)
                      （三臂均如此；delta_exec 按 arm 不同 → P_base 演化分叉）
P_target(t)           站级功率目标轨迹 = Σ EV C_true 的 70% × (1 + 0.1×sin(2πt/T_target))
                      （T_target=120 cycle；模拟站级调度目标在 C_true 70% 附近波动，留出
                      向上修正空间——既非总超功率也非极保守）
controller RNG seed   20260813_C（冻结；target 轨迹与 P_base 演化确定性）
```

> **F5 关键**：EMS request aggressive 程度直接决定 D2 看起来多有用——controller 全参数冻结，
> 三臂共享相同 controller + 相同 target trajectory + 相同 seed。`requested_delta` 由 PI
> controller 独立产生，**不**为"让 clip 生效"枚举 probe。

### 6.4 三臂（Arm1 机械定义沿用 v1.1 §6.3）

```text
Arm 0  Baseline       unrestricted correction（delta_exec_0 = requested_delta；无 D2 gate）
Arm 1  D1+D2          有信息类别分级 + 预算修正允许区间，但无 D3 recovery
                      机械定义：M3 default = PROTECTIVE，整个连续 M3 segment 永不进入 NORMAL，
                      仅 mode/run reset 按 D1 重新初始化（真正"有 D2 无 D3"）
Arm 2  D1+D2+D3       完整设备动作链
```

### 6.5 物理控制指标（F3/F7；infeasible/violation 基于 P_cmd vs C_true；tracking 唯一定义）

所有差值 Δ = Arm2 − Arm0（B-core）或 Arm2 − Arm1（B-recovery）；percentile bootstrap 95%CI
（§4.4 冻结设定；resample unit = scenario）。

```text
—— B-core 指标（Arm2 vs Arm0；D2 technical effect）——
Δ_inf       = rate_infeasible(Arm2) − rate_infeasible(Arm0)
              infeasible 定义：P_cmd(t) > C_true(t) + tol（基于 emulator 独立 envelope proxy，
              不是 D2 自己的 boundary；防 M2 自证；与 CLAIM 1 第 6 步 clip 后物理命令同构）
              tol 冻结 = 0.1 kW

Δ_violation = rate_violation(Arm2) − rate_violation(Arm0)
              violation 定义：P_cmd(t) > C_true(t)（越过 latent feasible envelope；
              非 actual 越 protective boundary——后者只说明边界保守，方向不明）

safety_invariant  unsupported_positive_correction_rate(Arm2) == 0
              （PROTECTIVE U=0 必然为 0，controller invariant / regression check，
              不作 superiority gate）

Δ_tracking = tracking_residual(Arm2) − tracking_residual(Arm0)
              tracking_residual = median |actual_power(t) − P_cmd(t)|   ← F7 唯一定义，删"或"

—— B-recovery 指标（Arm2 vs Arm1；D3 marginal recovery value）——
Δ_unnec_prot = unnecessary_protective_duration(Arm2) − unnecessary_protective_duration(Arm1)
              unnecessary_protective_duration = PROTECTIVE 段中 C_true(t) 高于 P_cmd(t)
              （实际可支持更高）却仍 PROTECTIVE 的 cycle 数
              （回答"为什么不能永远 PROTECTIVE"——D3 的独立价值）

Δ_inf_rec   = rate_infeasible(Arm2) − rate_infeasible(Arm1)
              （recovery 不引入新 infeasible）
```

**预冻结 margins（MCID + non-inferiority）**：
```text
δ_inf               = 0.02（B-core：Arm2 infeasible 绝对降低 >= 2pp）
δ_violation         = 0.02（B-core：Arm2 violation 绝对降低 >= 2pp）
δ_track_ni          = 0.3 kW（B-core：Arm2 tracking non-inferior，不恶化超 0.3 kW）
δ_prot              = 3 cycle（B-recovery：Arm2 比 Arm1 少 >= 3 cycle unnecessary protective）
δ_inf_ni_rec        = 0.005（B-recovery：Arm2 infeasible 不比 Arm1 差超 0.5pp）
```

### 6.6 PASS / FAIL 条件（F8；B-core 与 B-recovery 拆分，消除判定冲突）

**B-core Gate（Arm2 vs Arm0；D2 technical effect；须在全部 4 个 C_true family 上成立）**：

PASS（全部满足）：
1. Δ_inf：95%CI **上界** < −δ_inf（每个 C_true family 均成立）；
2. Δ_violation：95%CI 上界 < −δ_violation（每个 family）；
3. safety_invariant：unsupported_positive_correction_rate(Arm2) == 0；
4. Δ_tracking：95%CI 上界 < δ_track_ni（每个 family；non-inferior）。

FAIL（任一成立 → B-core FAIL → D2 No-Go → Project No-Go）：
1. 任一 C_true family 上 Δ_inf：CI 上界 >= −δ_inf；
2. 任一 family 上 Δ_violation：CI 上界 >= −δ_violation；
3. safety_invariant 违反；
4. 任一 family 上 Δ_tracking：CI 上界 >= δ_track_ni。

**B-recovery Gate（Arm2 vs Arm1；D3 marginal recovery value；仅在 B-core PASS 后判定）**：

PASS（全部满足）：
5. Δ_unnec_prot：95%CI 上界 < −δ_prot（Arm2 比 Arm1 少 ≥ 3 cycle unnecessary protective）；
6. Δ_inf_rec：95%CI 上界 < δ_inf_ni_rec（Arm2 infeasible 不比 Arm1 差）。

FAIL（任一成立 → B-recovery FAIL；**不回滚 B-core**，D2 仍存活，仅 D3 无独立价值）：
5. Δ_unnec_prot：CI 上界 >= −δ_prot；
6. Δ_inf_rec：CI 上界 >= δ_inf_ni_rec。

> **完全不要加 PV / BESS / 电价 / 经济收益指标。**

---

## 7. Success / Conditional / No-Go criteria（字段 6；F8 穷尽映射重写，无判定冲突）

| 结果 | 判定 | 条件 |
|---|---|---|
| **A PASS** | D3 有增量辨识力 | 数据充分 + §4.4 PASS 全部满足 |
| **A FAIL** | D3 No-Go | §4.4 任一 FAIL 成立 → 极可能 Project No-Go |
| **A DATA INSUFFICIENT** | HOLD | §5 机械阈值不满足；需新协议版本 + 新数据 |
| **B-core PASS** | D2 有技术效果 | A PASS 后，§6.6 B-core 在全部 4 个 C_true family 上 PASS |
| **B-core FAIL** | D2 No-Go | §6.6 B-core 任一 FAIL → Project No-Go |
| **B-recovery PASS** | D3 有独立技术价值 | B-core PASS 后，§6.6 B-recovery PASS |
| **B-recovery FAIL** | D3 无独立价值（D2 仍存活） | B-core PASS 后，§6.6 B-recovery 任一 FAIL |

**穷尽映射（F8；消除 v1.1 §6.5"任一 FAIL→D2 No-Go"与 §7"Arm1 also PASS→仅降 CLAIM 5"的冲突）**：

```text
A DATA INSUFFICIENT          → HOLD（新协议 + 新数据；不判 No-Go，也不 PASS）
A FAIL                       → D3 No-Go → 重判 Patent Gate（D3 区别锚消失）→ 极可能 Project No-Go
A PASS, B-core FAIL          → D2 No-Go → Project No-Go（P-002 降 D）
A PASS, B-core PASS,
        B-recovery FAIL      → D2 survives，D3 无独立技术价值
                                → CLAIM 5 降弱从属；D3 区别锚弱化；回 Patent Gate /
                                  代理师重点审 ACN 族风险（P-003 降 C-弱，P-002 维持 C）
A PASS, B-core PASS,
        B-recovery PASS      → D2 + D3 technical effect
                                → 进代理师检索（FILING GO 候选）（P-002/P-003 维持 C）
```

> **F8 关键**：B-recovery FAIL **不回滚 B-core**（D2 仍存活，不 Project No-Go）；D3 的独立
> 价值由**直接 Arm2 vs Arm1**判断，而非 v1.1 的"看 Arm1 是否也比 Arm0 好"（后者不等价于
> "D3 无独立价值"）。

---

## 8. Forbidden post-hoc actions（字段 7）

- 禁止调 D3 trigger 参数（0.95 / 3 cycle / Q95 / 15 min / min_history_samples）；
- 禁止加 classifier / confidence score / 双时间尺度 / learned trigger 救 D3；
- 禁止把 P2 formal test（已 consumed）重新用于阈值选择 / 规则修改；
- 禁止在 P2.1A 失败后"换一个 trigger 再试"（先 No-Go，再新版本协议）；
- 禁止 **post-hoc 追加 train 子集**（数据不够 = DATA INSUFFICIENT/HOLD）；
- 禁止调 B1 ε / B2 median-max / B3 RNG seed+phase 定义+抽样次数 / B4 lag 定义（已冻结）；
- 禁止调 cluster bootstrap（percentile / N_boot=2000 / seed / resample 重算 trigger / B2 functional）；
- 禁止调 emulator family / saturation 顺序 / lag / noise / C_true family 定义与 uplift 因子 / scenario bank / δ margins；
- 禁止调 PI controller（Kp/Ki/anti-windup/clamp/target trajectory/P_base 更新/seed）；
- 禁止在 P2.1B 引入 PV / BESS / 电价 / 经济收益指标或据此宣称站级收益；
- 禁止用 EV response emulator 反推 gate 参数；infeasible/violation 基于 P_cmd vs C_true（非 D2 boundary）；
- 禁止把 C_true 称 "true capability"（须称 latent feasible-envelope proxy）；禁止把 B 结论
  宣称"真实车辆能力下的效果"（须限定 "synthetic envelope 假设下的 closed-loop technical effect"）；
- 禁止把 train 域 falsification 结果宣称"独立验证"；
- 禁止在 A FAIL/DATA INSUFFICIENT 后运行 B（A 是 B 前置硬门）；
- 禁止因 B-recovery FAIL 而回滚 B-core PASS（双 Gate 独立）。

---

## 9. Patent consequence if failed（字段 8；F8 对齐双 Gate）

| 失败点 | 专利后果 | registry |
|---|---|---|
| A FAIL（D3 无增量辨识力） | CLAIM 1 第 8/9 步 + CLAIM 5"实测响应驱动恢复"删除 → 恢复仅剩通信/停充/电池内部（prior art 已覆盖）→ 极可能 Project No-Go | P-003 降 D |
| A DATA INSUFFICIENT | HOLD；CLAIM 5 维持"机制已观测；trigger 语义有效性 train 域证据不足" | P-003 维持 C（有条件） |
| B-core FAIL（D2 无技术效果） | CLAIM 1 第 5/6 步"预算修正允许区间"退化为抽象措辞 → 按 Patent Gate 2 硬杀线 Project No-Go | P-002 降 D |
| B-core PASS, B-recovery FAIL（D3 无独立价值） | CLAIM 5 降为弱从属；D3 区别锚弱化；回 Patent Gate / 代理师重点审 ACN 族风险 | P-003 降 C-（弱）；P-002 维持 C |

**A PASS + B-core PASS + B-recovery PASS 的后果**：P-003 升 C（trigger 语义有效性 train 域
验证，仍非独立数据验证）；P-002 维持 C（技术效果验证，synthetic envelope 假设下）；进入
专利代理师检索；P3 仍不自动开。

---

## 10. 冻结与治理（字段 9-11）

```text
冻结项     本文件 v1.2 + D3 trigger 参数（§3）+ eligible risk set（§4.2）+ baselines（§4.3，
           含 B3/B4 RNG）+ Y/W/0.9（§4.4）+ bootstrap 全设定（§4.4）+ B2 functional 定义
           + coverage/latency margins + 数据充分性阈值（§5，B0-B4 全纳入）
           + 动作链（§6.1）+ emulator（§6.2，saturation 顺序 + C_true 4 family）+ PI
           controller（§6.3）+ Arm 定义（§6.4）+ 指标与 δ margins（§6.5）+ 双 Gate（§6.6）
SHA 锁定   implementation code SHA + protocol SHA + clean worktree
sentinel   P2.1A formal exposure sentinel（一次 consumed 后永久禁止 rerun）
数据域     P2.1A = JPL train only；P2.1B = 仿真闭环（C_true 从 JPL train bootstrap + uplift
           /volatile 变换，无真实站点数据消费）
测试集     P2 frozen test 不重新使用；P2.1 不产生"独立 test"声明（除非新数据域）
```

**变更控制**：任何改动（参数、baseline、bootstrap、指标、阈值、emulator、C_true family、
PI controller、δ margins、risk set、双 Gate 判定）须新版本 + 新测试协议，走与 evidence
freeze 相同的 Review 链；test 暴露后零改动。

**实施前置**：本协议 v1.2 须通过 Freeze Review（核冻结项是否闭合、D3 参数真冻结、baseline
真 adversarial、bootstrap 真冻结、emulator 数学正确、PI controller 真冻结、C_true 证据边界
清楚、双 Gate 判定无冲突）→ 才可写 P2.1A 代码；P2.1A 结果先评审 → 才可运行 P2.1B。

---

## 11. 不做什么（scope discipline）

- **不做** P3 大规模实验、不接真实光伏/储能/现场 EMS、不接真实硬件（本协议是 Closed-loop
  **SIL**，非 HIL——避免实验类型表述过度）；
- **不做** active redistribution / 站级优化 / 经济收益；
- **不做** ML 模型 / classifier / learned trigger；
- **不做** "把 D3 调到 PASS"——目标是杀，不是救；
- **不重新** 消费 P2 formal test；
- **不 post-hoc** 追加 train 子集或调 emulator / controller 救结果；
- **不把** C_true 称 true capability，**不把** B 结论说成"真实车辆能力下的效果"。

本协议的唯一目的：**尽最大可能把现有 D3/D2 发明核杀掉；杀不掉，才值得进入正式专利投入。**
