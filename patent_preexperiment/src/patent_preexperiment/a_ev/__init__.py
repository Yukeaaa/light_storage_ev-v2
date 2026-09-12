"""A 案算法参考实现与可控真值实验台（A-EV 线）— V0.2 pre-freeze。

定位（重要，勿误读）：
- 本包是 **机制参考实现 + 场景/标签/指标管线**，用于把 A 权 1【a】–【e】写成可运行的代码，
  并为将来的 HIL / 可控真值实验准备好「场景 → 事件真值 → 指标」的完整链路。
- **不是效果验证**。本包在**合成场景**上运行，输出**不得**作为收益结论、
  不得写入权利要求或申请文本、不得用于替代 A 轨 R5 7/7。
- 阈值遵循「**先冻结产生规则、HIL commissioning 后落数值并加锁**」（见 `thresholds.py`）。

模块划分与 A 权 1 五段的对应：
    types.py         统一符号约定（signed deviation）+ 基础类型
    thresholds.py    阈值**产生规则**（per-resource band / 响应窗 / 持续时长换算）
    attribution.py   模块 1  Deviation Attribution            ← 【b】有效性与能力归因判断
    capability.py    模块 2  Capability State Update          ← 【c】方向化可用能力状态更新
                     （并含模块 5 的执行回写与分级恢复，← 【e】）
    gap_carrier.py   模块 3  Gap Mapping        ← 【d】前半（偏差 → 待补偿站级功率缺口）
                     模块 4  Carrier Selection  ← 【d】后半（可承接贡献 / 方向兼容 / 承接选择）
    algorithm.py     A 参考实现（串联 1–5）+ 事务状态 + 消融开关
    baselines.py     整链对照 B0 / B1 / B2 + 模块消融 A-no-state / A-no-writeback
    scenario.py      HIL 可控真值场景生成器（评价集 / 标定集 / 稳健性矩阵严格分离）
    metrics.py       主指标（EMUR + RESID full/steady）与次指标
    runner.py        评估 harness（含阈值锁定校验与阶段守卫）
"""

from __future__ import annotations

__all__ = [
    "types",
    "thresholds",
    "attribution",
    "capability",
    "gap_carrier",
    "algorithm",
    "baselines",
    "scenario",
    "metrics",
    "runner",
]
