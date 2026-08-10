# 外部证据来源登记（sources.md）

> 每一条 A/B/C 级主张必须能在本文件回查到可验证来源。CSV 台账 `source_ref` 列引用本文件的
> `S-xxx` 编号；新增来源先在此登记再在 CSV 引用（审查结论8 P1-5）。

| 编号 | 来源 | 可验证位置 | 支持的主张 |
|---|---|---|---|
| S-001 | IEC 61851 / SAE J1772 control-pilot 语义：pilot 定义桩侧允许电流上限，不直接等于车辆实际吸收功率 | IEC 61851-1；SAE J1772 | C-001 |
| S-002 | Green, R., & Harper, J., *Plug-In Electric Vehicle Charging Response Characterization for Grid Integration: Implications for Smart Charge Management*, ChargeX Consortium / Argonne & Idaho National Laboratory, ANL-25/62, Oct 2025 | https://www.osti.gov/biblio/3000254 · DOI 10.2172/3000254；https://inl.gov/chargex/chargex-publications/ | C-001、C-002 |
| S-003 | Lee, Z. J., et al., *Adaptive Charging Networks: A Framework for Smart Electric Vehicle Charging*, IEEE Trans. Smart Grid 12(5):4339–4350, 2021（含 non-ideal battery charging behavior、quantized control signals 实际工程挑战） | DOI 10.1109/TSG.2021.3074437 | C-001、C-002、C-003 |
| S-004 | Lee, Z. J., et al., *Large-Scale Adaptive Electric Vehicle Charging*, IEEE SmartGridComm, Aalborg, 2018 | DOI 10.1109/SmartGridComm.2018.8587550 | C-003（ACN 架构） |
| S-005 | Lee, Z. J., Li, T., & Low, S. H., *ACN-Data: Analysis and Applications of an Open EV Charging Dataset*, ACM e-Energy '19 | DOI 10.1145/3307772.3328313 | C-003、C-011、C-012（ACN-Data 数据集依据） |
| S-006 | 本项目 R1 扩展审计报告（A1–A5 正式运行，baseline `34f04f6`；含 A5 recent_var→E1 响应证据密度与最终判定） | `reports/R1_expansion_audit.md`，锚点 `R1_expansion_audit#A5`、`R1_expansion_audit#最终判定` | C-007、P-001、P-003 |
