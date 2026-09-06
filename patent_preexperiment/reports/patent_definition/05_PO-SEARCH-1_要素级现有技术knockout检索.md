# 05_PO-SEARCH-1_要素级现有技术knockout检索

> 执行时间（UTC）：2026-09-06
> 性质：`04_专利目标冻结_…` §5 规定的先检索门。判定对象 = E1–E4 闭环是否有专利生存空间。本检索是要素级 knockout 初筛，不是全文专利海搜；判定为"暂存活"不等于新颖性确认。
> 检索层：A（单要素常规化）→ B（两两稳定组合）→ C（整体闭环高度近似）。关键层 = C。

## 1. 检索执行记录

| # | 检索词（原样） | 状态 |
|---|---|---|
| Q1 | battery energy storage state of power SOP limit estimation dispatch BMS patent | 失败（超时） |
| Q2 | dynamic transformer rating dynamic line rating integration dispatch real-time capacity limit scheduling | 成功 |
| Q3 | PV inverter available power capability estimation curtailment dispatch power limit | 成功 |
| Q4 | microgrid energy management feasibility restoration corrective power reallocation constraint violation | 失败（超时） |
| Q5 | battery state of power SOP estimation peak power capability BMS electric vehicle | 成功 |
| Q6 | energy management system feasible region device limits power reallocation microgrid dispatch | 成功 |
| Q7 | aggregate flexibility feasible region envelope distributed energy resources device constraints | 成功 |
| Q8 | online update power capability limit from measured execution feedback dispatch self-learning | 成功 |
| Q9 | 光储充 储能 可用功率 动态 边界 功率分配 专利 | 失败（超时） |
| Q10 | adaptive power capability constraint learning closed-loop dispatch patent inverter battery station | 成功（含 CN 补查：储能电站 逆变器 自适应 功率能力 约束学习 闭环调度 专利） |
| Q11 | feedback optimization constraint violation learning correction term operational limits power systems | 失败（超时，重试 2 次未恢复） |
| Q12 | US20160336765A1 / Applied Energy 执行偏差论文 / OFO 约束学习线 深查 | 失败（WebFetch 连续超时） |

覆盖率说明：A/B 层证据充分；C 层 8 次成功检索未见整体闭环披露，但 **CN 专利空间为浅覆盖**（Q9 超时，仅 Q10 附带命中），US20160336765A1 权利要求级深查未完成——两项列为强制深查待办（§6），C 层判定据此为"暂定"。

## 2. A 层判定：单要素全部常规化（预测证实）

| 要素 | 现有技术 | 判定 |
|---|---|---|
| E1（BESS 能力边界） | State of Power (SOP) 估计是 BMS 标准功能：峰值充放能力（2s/10s/30s 窗口）由等效电路模型/内阻 + SOC/温度估计，综述与方法文献密集（[J. Energy Storage 综述](https://www.sciencedirect.com/science/article/abs/pii/S2352152X26022498)、[MDPI 综述](https://www.mdpi.com/1996-1073/18/14/3834)） | **crowded** |
| E1（变压器能力边界） | DTR/动态增容：top-oil/hot-spot 热模型直接嵌入 DC-OPF 调度（[EPSR 论文](https://www.sciencedirect.com/science/article/abs/pii/S0378779619300902)）、配网高 PV 渗透下 DTR 调度（[IEEE/ResearchGate](https://www.researchgate.net/publication/345319912)）、按 HST 而非负载率限值调度 | **crowded** |
| E1（PV 能力边界） | 可用功率估计（irradiance–power 模型、volt-watt 反推、FPPT 余量控制、AGC 备用估计）成熟（[IET RPG](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/iet-rpg.2019.1003)、[NREL 85148](https://docs.nlr.gov/docs/fy23osti/85148.pdf)、[FPPT](https://psecommunity.org/wp-content/plugins/wpor/includes/file/2302/LAPSE-2023.8532-1v1.pdf)） | **crowded** |
| E2（边界 → 站级可行域） | 聚合柔性域/运行包络是一整个文献族：由设备约束（功率/能量/爬坡）构造 DER 聚合可行域，含网络约束的内逼近（[arXiv 2512.04472](https://arxiv.org/html/2512.04472v2)、[DER 聚合可行域](https://www.researchgate.net/publication/413680409)、[flexibility envelopes](https://www.sciencedirect.com/science/article/pii/S2352467726003759)、operating envelopes） | **crowded**（作为数学构造） |
| E3（边界变化 → 重分配） | 纠正性调度/re-dispatch/curative actions 是电力系统常规概念；MPC 滚动重解天然覆盖"约束变化后重新分配"（[Real-time Curative Actions via OFO](https://www.researchgate.net/publication/373034069)） | **crowded**（作为一般概念） |
| E4（执行反馈 → 边界修正） | 最近身候选：OFO（在线反馈优化）用测量反馈持续更新控制决策并讨论限值保守化（[OFO 综述幻灯](http://people.ee.ethz.ch/~floriand/docs/Slides/Dorfler_ECC2020.pdf)、[momentum OFO](https://arxiv.org/pdf/2512.07077)）；Applied Energy 执行偏差论文涉及 SOC 相关功率能力与执行差（[S0306261925020707](https://www.sciencedirect.com/science/article/pii/S0306261925020707)，**未完成深查**） | **部分常规化；关键连接未证实 crowded** |

## 3. B 层判定：两两组合存在，但连接语义不同

| 组合 | 现有技术状态 | 判定 |
|---|---|---|
| E1+E2 | 聚合柔性域文献族 = 设备能力边界 → 聚合可行域，已是稳定研究方向；DTR-嵌入-调度 = 变压器 E1+E2 商用组合 | **crowded** |
| E2+E3 | 纠正性/curative 调度、MPC 重解 = 可行域变化触发再分配的一般机制 | **crowded**（一般语义） |
| E3+E4 | 自适应滚动调度（含 DRL）、OFO 反馈更新控制量存在；但"**执行偏差 → 设备边界置信度更新 → 回灌为调度约束**"这一具体连接未检索到稳定组合 | **部分空白** |

## 4. C 层判定（关键层）：未见整体闭环披露，暂定关键连接缺失

**最同构的四个家族**（均未构成完整 E1→E2→E3→E4 披露）：

1. **微网 MPC 专利族**（如 [US20160336765A1](https://patents.google.com/patent/US20160336765A1/en)、清华/国网/南瑞 MPC 储能调度申请）：闭环存在，但边界来自模型/额定，**无执行反馈修正设备能力边界环**（权利要求级深查 OPEN）。
2. **OFO 家族**：测量反馈更新控制决策，但更新对象是控制量/对偶修正，**不是"设备能力边界知识库"**；约束违反学习支线未深查（OPEN）。
3. **自适应/DRL 调度**（[Applied Energy 自适应滚动调度](https://www.sciencedirect.com/science/article/abs/pii/S0306261922015513)、[CN117713168A](https://patents.google.com/patent/CN117713168A/zh)）：策略自适应，**无显式边界确认/置信度机制**。
4. **聚合柔性域**：可行域构造完整，但域由模型计算，**不由执行偏差在线校正**。

跨 8 次成功检索（含 Q10 内嵌 CN 补查），未发现 E1→E2→E3→E4 全链路披露；检索工具亦明确反馈"无逐字匹配专利"。**C 层判定：关键连接（E4 执行反馈确认边界 + E3→E4 责任归属/定向转移）未证实 crowded——目标暂存活。**

## 5. 空白点收窄建议（供目标修订参考）

真正可辩护的核心不是"动态边界"本身（A 层 crowded），而是 **E4 中心的连接机制**：

```text
边界/计划变化
→ 判定站级计划落出可行域
→ 识别责任设备与约束类型
→ 定向转移功率到其他设备
→ 用执行偏差更新该设备边界置信度（保守化）
```

其中"执行确认的能力边界（execution-confirmed capability boundary）"是四家族共同的缺失件。注意一个内在一致性：R4-A 曾实证探测的 tracking shortfall 状态结构，正是这个 E4 环节的物理素材——**专利空白点与证据瓶颈是同一个对象**。

## 6. 强制深查清单（起草任何权利要求前必须完成）

- [ ] US20160336765A1 权利要求逐条比对（微网 MPC 是否含边界学习环）——本轮 WebFetch 超时未完成。
- [ ] Applied Energy 执行偏差论文（S0306261925020707）全文：是否把执行偏差回灌为后续调度约束。
- [ ] OFO 约束违反学习支线（Q11 重试）。
- [ ] CN 专利空间补查（Q9 重试）：光储充/储能电站 + 可用功率/能力边界 + 动态分配。
- [ ] 复用 `02_prior_art_element_map_v3_e7_fast.md` 的 EV 侧要素映射到 E1–E4 框架。

## 7. 最终判定

```text
PO-SEARCH-1 = SURVIVE WITH CONDITIONS

A 层：E1–E3 单要素全部常规化，E4 部分常规化
B 层：E1+E2、E2+E3 crowded；E3+E4 关键连接部分空白
C 层：未发现整体闭环披露（CN 深查 OPEN，暂定关键连接缺失）

=> 专利目标暂存活，按 §5 方向收窄
=> RD-1 A0/A1 解锁（B 轨）；核心专利 status = NO-GO 不变
=> 深查清单（§6）完成前不得起草权利要求
```

决策规则对照（04 文件 + 本轮冻结的执行序）：命中"单要素 crowded 但完整闭环缺少关键连接 → 目标暂存活 → 再开 RD-1 A0/A1"分支。
