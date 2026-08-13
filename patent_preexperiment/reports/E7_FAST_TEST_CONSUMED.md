# E7-FAST TEST_CONSUMED — single-exposure 永久记录

> **目的**：永久锁定 commit `48b5205` 为 E7-FAST D2+D3 test single-exposure 最终结果。
> 后续任何运行（包括 D3 corrective audit 的 test 回放）**不得**重新定义为 confirmatory test，
> 只能称为 code-corrective audit。

---

## 1. 永久锁定

| 项 | 值 |
|---|---|
| **single-exposure commit** | `48b5205` |
| **日期** | 2026-08-13 |
| **test_policy 冻结 commit** | `48b5205`（同 commit；治理瑕疵见审查 §26，fast-track 可接受）|
| **D2 test verdict** | GO（Over improvement 39.65%，CoverageRatio 77.97%）|
| **D3 test verdict（旧代码，request-cap bug）** | GO（shortfall 降 39.65%，unplanned_bess 降 41.41%）|
| **D3 test verdict（corrective audit，request-cap 修正后）** | CONDITIONAL（shortfall 降 4.46%，unplanned_bess 降 6.03%）|

## 2. 治理说明

- `48b5205` 中的 D2 test 结果**不受 D3 request-cap bug 影响**（D2 不使用 park_requested/BESS/PCC），
  D2 test GO 仍然有效。
- `48b5205` 中的 D3 test 结果**受 request-cap bug 影响**，已被 D3 corrective audit 取代。
  旧 D3 test GO 数字（shortfall 降 39.65%）**作废**，不得引用。
- D3 corrective audit 的 test 回放是**代码纠错审计**，不是新的 single-exposure test。
  它使用与 `48b5205` 完全相同的 test 事件（6,643 M2 正向事件），只是修正了代码逻辑。

## 3. 后续禁止事项

- **禁止**重新运行 `test_runner.run_test_exposure()` 并声称是 confirmatory test。
- **禁止**将 D3 corrective audit 的 test 回放结果称为"single-exposure test"。
- **禁止**引用旧 D3 test 数字（shortfall 降 39.65%、unplanned_bess 降 41.41%）作为专利证据。
- **可以**引用 D2 test 数字（Over improvement 39.65%）—— D2 不受 bug 影响。
- **可以**引用 D3 corrective audit train+val 结果作为系统层证据（但标注 CONDITIONAL/弱）。
