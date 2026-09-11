"""模块 1：Deviation Attribution（对应权 1【b】、权 3、说明书 §6）。

规则 + 时序证据融合，**不使用机器学习**（第一版按 A-EV 计划建议保持可解释性）。
判定次序严格按权 3 的优先级：**通信无效 > 暂态响应 > 持续可用能力受限**；
资源局部运行条件按说明书 §6.1 判据 4 分「持续激活型 / 瞬时跃迁型」双向处置。
"""

from __future__ import annotations

from typing import Any

from .types import DIR_UP, AttributionResult, Obs, Verdict


class Attriber:
    """有效性与能力归因判断。"""

    def __init__(self, cfg: dict[str, Any]) -> None:
        a = cfg["attribution"]
        self.band = float(a["deviation_band_kw"])
        self.window = float(a["response_window_s"])
        self.need_consec = int(a["persistence_n"])
        self._consec: dict[str, tuple[int, int]] = {}

    # ------------------------------------------------------------------
    def _reset(self, rid: str) -> None:
        self._consec[rid] = (0, 0)

    def attribute(self, obs: Obs) -> AttributionResult | None:
        """返回 None 表示「偏差未超带，不构成能力证据」。"""
        req_dir = DIR_UP if obs.p_req > 0 else -DIR_UP
        under = abs(obs.p_req) - abs(obs.p_meas)   # 该方向上的欠交付量
        if under < self.band:
            self._reset(obs.rid)
            return None

        ev: dict[str, Any] = {"under_delivery_kw": round(under, 3), "requested_dir": req_dir}

        # ---- 判据 1：数据 / 通信有效性 → 偏差不能被采信（排除）
        if not obs.comm_ok or not obs.data_fresh:
            self._reset(obs.rid)
            ev["criterion"] = "data_comm_validity"
            return AttributionResult(Verdict.COMM_INVALID, req_dir, under, ev)

        # ---- 判据 2：时间对齐 → 对齐失败即不可归因
        if not obs.ts_aligned:
            self._reset(obs.rid)
            ev["criterion"] = "time_alignment"
            return AttributionResult(Verdict.UNCERTAIN, req_dir, under, ev)

        # ---- 判据 3：控制响应观察窗 → 暂态响应，暂缓更新（优先级高于持续性判据）
        if obs.cmd_sent_t > 0.0 and (obs.t - obs.cmd_sent_t) < self.window:
            self._reset(obs.rid)
            ev["criterion"] = "response_window"
            ev["elapsed_s"] = round(obs.t - obs.cmd_sent_t, 3)
            return AttributionResult(Verdict.TRANSIENT, req_dir, under, ev)

        # ---- 判据 4a：瞬时跃迁型局部条件（模式切换 / 保护转换瞬间）→ 排除
        if obs.mode_switch or obs.protection_event:
            self._reset(obs.rid)
            ev["criterion"] = "momentary_local_condition"
            return AttributionResult(Verdict.EXTERNAL_CONSTRAINT, req_dir, under, ev)

        # ---- 判据 4b：站级外部约束（控制器自身可知）且本机无持续限值 → 排除
        if obs.station_constraint_active and not obs.local_limit_active:
            self._reset(obs.rid)
            ev["criterion"] = "station_constraint"
            return AttributionResult(Verdict.EXTERNAL_CONSTRAINT, req_dir, under, ev)

        # ---- 判据 4c + 判据 5：持续激活型局部限值 + 方向一致 + 持续性
        dir_ok = obs.local_limit_dir in (0, req_dir)
        n, d = self._consec.get(obs.rid, (0, 0))
        if obs.local_limit_active and dir_ok:
            n = n + 1 if d == req_dir else 1
            self._consec[obs.rid] = (n, req_dir)
            ev["criterion"] = "persistent_local_limit"
            ev["consecutive"] = n
            if n >= self.need_consec:
                return AttributionResult(Verdict.VALID_CAPABILITY_LIMIT, req_dir, under, ev)
            return AttributionResult(Verdict.UNCERTAIN, req_dir, under, ev)

        # ---- 判据 5：偏差持续但无局部条件证据 → 暂缓（保守）
        self._reset(obs.rid)
        ev["criterion"] = "persistence_without_local_evidence"
        return AttributionResult(Verdict.UNCERTAIN, req_dir, under, ev)


# 归因结论 → 是否允许更新能力状态（与 types.UPDATING_VERDICTS 一致，便于策略侧查询）
def allows_update(v: Verdict) -> bool:
    return v is Verdict.VALID_CAPABILITY_LIMIT
