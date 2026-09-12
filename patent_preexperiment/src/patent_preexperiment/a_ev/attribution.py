"""模块 1：Deviation Attribution（对应权 1【b】、权 3、说明书 §6）。

规则 + 时序证据融合，**不使用机器学习**（第一版按 A-EV 计划建议保持可解释性）。

**V0.2 两层结构**：
  第一层「有效性判定」：数据 / 通信有效性、时间对齐、控制响应观察窗、瞬时局部条件、
      站级外部约束 —— 决定该偏差**能否被采信**，不能采信者既不构成站级缺口、也不更新能力。
  第二层「能力归因」：在要求方向上是否构成**欠交付** —— 决定该偏差**是否表征能力受限**。
      过执行 / 反向执行属"有效偏差但不表征能力受限"（VALID_EXECUTION_DEVIATION），
      可构成站级缺口，但**不**收缩能力边界。

判定次序严格按权 3 的优先级：**通信无效 > 暂态响应 > 持续可用能力受限**；
资源局部运行条件按说明书 §6.1 判据 4 分「持续激活型 / 瞬时跃迁型」双向处置。

**方向纪律（V0.2）**：`local_limit_dir == UNKNOWN` 一律进入 UNCERTAIN，
**不得**作为任何方向的正向能力证据；限值方向与要求方向不一致时同属"不构成正向证据"。
"""

from __future__ import annotations

from typing import Any

from .thresholds import Thresholds
from .types import (
    AttributionResult,
    Deviation,
    LimitDir,
    Obs,
    Verdict,
    deviation_of,
    limit_dir_matches,
)


class Attriber:
    """有效性与能力归因判断。"""

    def __init__(self, thr: Thresholds) -> None:
        self.thr = thr
        self._consec: dict[str, tuple[int, int]] = {}

    # ------------------------------------------------------------------
    def _reset(self, rid: str) -> None:
        self._consec[rid] = (0, 0)

    def attribute(self, obs: Obs) -> AttributionResult | None:
        """返回 None 表示「偏差未超带，不构成任何执行偏差证据」。"""
        band = self.thr.band(obs.rid)
        dev = deviation_of(obs.p_req, obs.p_meas)

        # 是否构成"值得处理的执行偏差"：要求方向欠交付，或站级缺口超带
        if dev.deficit < band and dev.gap_magnitude < band:
            self._reset(obs.rid)
            return None

        ev: dict[str, Any] = {
            "signed_deviation_kw": round(dev.signed, 3),
            "gap_direction": dev.gap_direction,
            "gap_magnitude_kw": round(dev.gap_magnitude, 3),
            "deficit_kw": round(dev.deficit, 3),
            "delivered_kw": round(dev.delivered_in_req_dir, 3),
            "requested_dir": dev.req_dir,
        }
        return self._classify(obs, dev, ev, band)

    # ------------------------------------------------------------------
    def _classify(
        self, obs: Obs, dev: Deviation, ev: dict[str, Any], band: float
    ) -> AttributionResult:
        req_dir = dev.req_dir

        def res(v: Verdict) -> AttributionResult:
            return AttributionResult(
                verdict=v,
                deviation=dev,
                evidence_direction=req_dir,
                evidence_level=dev.delivered_in_req_dir,
                evidence=ev,
            )

        # ---- 判据 1：数据 / 通信有效性 → 偏差不能被采信（排除）
        if not obs.comm_ok or not obs.data_fresh:
            self._reset(obs.rid)
            ev["criterion"] = "data_comm_validity"
            return res(Verdict.COMM_INVALID)

        # ---- 判据 2：时间对齐 → 对齐失败即不可归因
        if not obs.ts_aligned:
            self._reset(obs.rid)
            ev["criterion"] = "time_alignment"
            return res(Verdict.UNCERTAIN)

        # ---- 判据 3：控制响应观察窗 → 暂态响应，暂缓更新（优先级高于持续性判据）
        if obs.cmd_sent_t > 0.0 and (obs.t - obs.cmd_sent_t) < self.thr.window_s:
            self._reset(obs.rid)
            ev["criterion"] = "response_window"
            ev["elapsed_s"] = round(obs.t - obs.cmd_sent_t, 3)
            return res(Verdict.TRANSIENT)

        # ---- 判据 4a：瞬时跃迁型局部条件（模式切换 / 保护转换瞬间）→ 排除
        if obs.mode_switch or obs.protection_event:
            self._reset(obs.rid)
            ev["criterion"] = "momentary_local_condition"
            return res(Verdict.EXTERNAL_CONSTRAINT)

        # ---- 判据 4b：站级外部约束（控制器自身可知）且本机无持续限值 → 排除
        if obs.station_constraint_active and not obs.local_limit_active:
            self._reset(obs.rid)
            ev["criterion"] = "station_constraint"
            return res(Verdict.EXTERNAL_CONSTRAINT)

        # ---- 判据 4b'：上报型本地限值（V0.3 命令链四层留痕）→ 排除
        # 本地 BMS/PCS 已把指令翻译/裁剪为 accepted（可观测），设备按 accepted 正确执行：
        # (requested − accepted) 属**上报的本地限值**，不构成执行失败证据——
        # 既不更新能力状态（执行学习通道），也不作为站级缺口来源（站级补偿走 PCC 残差通道）。
        if obs.reported_limit_active:
            self._reset(obs.rid)
            ev["criterion"] = "reported_local_limit"
            ev["requested_kw"] = obs.p_cmd_requested
            ev["accepted_kw"] = obs.p_cmd_accepted
            return res(Verdict.REPORTED_LIMIT)

        # ---- 判据 4c：持续激活型局部限值的方向核验（V0.2 修正）
        ld = obs.local_limit_dir
        if obs.local_limit_active and ld is LimitDir.UNKNOWN:
            self._reset(obs.rid)
            ev["criterion"] = "local_limit_dir_unknown"
            return res(Verdict.UNCERTAIN)
        if obs.local_limit_active and not limit_dir_matches(ld, req_dir):
            self._reset(obs.rid)
            ev["criterion"] = "local_limit_dir_mismatch"
            ev["local_limit_dir"] = ld.value
            return res(Verdict.UNCERTAIN)

        # ---- 判据 4c + 判据 5：持续限值 + 方向一致 + 持续性
        if obs.local_limit_active and dev.deficit >= band:
            n, d = self._consec.get(obs.rid, (0, 0))
            n = n + 1 if d == req_dir else 1
            self._consec[obs.rid] = (n, req_dir)
            ev["criterion"] = "persistent_local_limit"
            ev["consecutive"] = n
            if n >= self.thr.persistence_n:
                return res(Verdict.VALID_CAPABILITY_LIMIT)
            return res(Verdict.UNCERTAIN)

        # ---- 未表征能力受限的有效执行偏差：过执行 / 反向执行（V0.2 新增类别）
        if dev.deficit < band:
            self._reset(obs.rid)
            ev["criterion"] = "valid_deviation_not_capability"
            return res(Verdict.VALID_EXECUTION_DEVIATION)

        # ---- 判据 5：欠交付持续但无局部条件证据 → 暂缓（保守）
        self._reset(obs.rid)
        ev["criterion"] = "persistence_without_local_evidence"
        return res(Verdict.UNCERTAIN)


# 归因结论 → 是否允许更新能力状态（与 types.UPDATING_VERDICTS 一致，便于策略侧查询）
def allows_update(v: Verdict) -> bool:
    return v is Verdict.VALID_CAPABILITY_LIMIT
