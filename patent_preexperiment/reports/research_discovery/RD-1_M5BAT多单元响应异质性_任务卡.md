# RD-1_M5BAT多单元响应异质性_任务卡

> 建立（UTC）：2026-09-06
> 轨道：B 轨 research discovery（见 `../patent_definition/04_专利目标冻结_多设备动态可用能力边界与协同功率控制.md` §7）。不挂 R5，不是核心专利证据程序，不启动 Round 5。
> 数据：RWTH M5BAT 官方数据集 DOI 10.18154/RWTH-2025-06555，本地 `D:\Users\Micko\Documents\工作\华润集控\光储充\数据\RWTH\Dataset\`（4 个 CSV；另有 `Supplementary_file.pdf`、`AppliedEnergy_1024855.pdf`）。本地可访问性 2026-09-06 确认。

## 1. 研究问题（按数据事实修正后）

同一 M5BAT 站、同一外部激励（站级 schedule / 聚合功率）下，4 个同技术（LMO）电池单元的实际功率分摊是否**稳定地**偏离简单基线，且偏离可由 SOC 与近期响应解释？

**对原提议的事实修正**（依据 R4-A0b 一手审计 + schema CSV）：

| 原提议 | 数据事实 | 影响 |
|---|---|---|
| 10 个电池单元、11 份数据 | 公开集仅 4 个单元（lmo1–4，同名同技术 LMO）；4 份文件（2 tests × measurement/schedule） | 异质性维度收窄 |
| SOC / 温度 / 技术路线 / 状态 | 仅 SOC 可用；temperature、alarms/status、charge/discharge limit 字段**全部缺席** | C 候选特征集 = SOC + 近期响应 |
| 技术路线异质性 | 不存在（4 单元同技术） | 只研究同技术下的状态相关分摊差异 |

## 2. 数据事实（继承 R4-A0b，全部一手）

- measurement：test_1（2023-08-14 → 08-17，1 s）、test_2（2024-05-28 → 05-31，1 s），各 259,201 行 15 列；`bess_soc`/`bess_power_ac` + `lmo{1..4}_power_ac` + `lmo{1..4}_power_dc` + `lmo{1..4}_soc`。
- schedule：15 min，17 列；除单元级 power/energy 外含 `trafo_lmo1_lmo2_power`、`trafo_lmo3_lmo4_power` 两组子变压器功率。
- 对齐：test_1 的 schedule 与 measurement 时间不重叠（NOT_ALIGNED，仅作口径参考）；test_2 原始 timestamp 标签对齐，但 **schedule=UTC+1 / measurement=UTC+2**（补充材料标注）→ A0 必须先冻结时区归一化规则（R4-A1S 伪强教训）。
- schedule 为 M5Use MILP 优化输出，**不是外部实时命令，不是实际限值**；全数据无温度/状态/限值通道。
- 字段单位与粒度详见 `results/raw/core_search/r4_a0b/rwth_m5bat_2025_schema.csv`。

## 3. 阶段门（顺序执行，前门不过后门不开）

- **A0 口径冻结**：时区归一化规则（test_2 两小时偏移的显式处理）、充/放符号约定、单位核对、每单元额定功率表（从 Supplementary/PDF 提取；取不到则用 schedule 份额上限估计并标 estimated）→ 产出 `configs/research_discovery/rd1_a0.yaml`。
- **A1 一致性**：`bess_power_ac` vs `Σ lmo_i_power_ac` 残差分布；`lmo_i_power_dc` vs `ac` 结构；`trafo_lmo1_lmo2_power` vs 单元和。一致性不可接受 → STOP（数据不可信，不进机制问题）。
- **A2 共同激励事件提取**：在 test_2 对齐段内，按 schedule 台阶与聚合功率方向段提取事件窗口；test_1 仅用于 measurement 侧（无对齐 schedule）。
- **A3 异质性量级**：normalized response = `lmo_i_power_ac / rated_i`；同事件跨单元 dispersion（IQR / range / CV）；相似事件重复性。
- **A4 强简单基线对抗**：B0 = 额定比例分摊；B1 = SOC 比例分摊；B2 = SOC-bin + 充/放方向分模型。C = SOC + 近期响应（滚动窗口）+ 方向。**C ≤ B2 → STOP**（异质性不存在或不可用）。
- **A5 机制假设文档**（仅当 C > B2 且增量在留出段稳定）：回答唯一升级问题——"该异质性是否改变站级可用能力边界与功率分配决策"；是 → 提交 A 轨评估；否 → 归档为方向淘汰证据。

## 4. 指标冻结

1. normalized response = P_i / rated_power_i
2. 同事件跨单元 dispersion：IQR / range / CV
3. 相似事件重复性（同条件事件间配对差）
4. 状态变量对响应差异的增量解释力（C 相对 B2 的留出段增量）

统计纪律：同事件/同日配对比较；事件/日级 cluster bootstrap 95%CI；绝对量与相对量同报；必须报最差事件/最差单元。

## 5. anti-rescue 与禁止

- 指标与基线 ladder 冻结后不得中途加特征、换指标、换窗口；失败后新增方案必须 RD-1v2 + 新测试协议。
- 禁止 ML、禁止复杂优化、禁止系统收益/闭环收益结论。
- 禁止把 M5BAT 结论直接写入专利证据链；禁止把 schedule（MILP 输出）称作外部实时命令或实际限值。
- 术语纪律同 V2.0。

## 6. 现状

A0/A1 未开始（本卡即开工依据）。下一步：A0 口径冻结 → A1 一致性核验，均在本地数据上执行，无需等待任何新数据。
