"""BESS 物理模型（review §23 + 用户 D3 口径 §13；简单，不做九宫格）。

主场景：P_BESS_max = bess_power_ratio × actual_before_kw（EV pool peak 代理，单车场景），
SOC=50%, SOC_min=10%, SOC_max=90%, eta=0.95, capacity=2h×P_BESS_max。
BESS 有足够双向调整空间；第一轮只回答 S3 是否减少事后补偿。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BessParams:
    p_bess_max_kw: float        # 额定充/放功率上限（本事件缩放后）
    e_bess_kwh: float           # 容量 = capacity_hours × p_bess_max
    soc_init: float
    soc_min: float
    soc_max: float
    eta_charge: float
    eta_discharge: float


def make_bess_params(
    actual_before_kw: float,
    *,
    power_ratio: float = 0.5,
    capacity_hours: float = 2.0,
    soc_init: float = 0.50,
    soc_min: float = 0.10,
    soc_max: float = 0.90,
    eta_charge: float = 0.95,
    eta_discharge: float = 0.95,
) -> BessParams:
    """按 actual_before 缩放 BESS 功率（单车场景 pool peak 代理）。"""
    p_max = power_ratio * max(actual_before_kw, 0.0)
    return BessParams(
        p_bess_max_kw=p_max,
        e_bess_kwh=capacity_hours * p_max,
        soc_init=soc_init,
        soc_min=soc_min,
        soc_max=soc_max,
        eta_charge=eta_charge,
        eta_discharge=eta_discharge,
    )


def bess_fast_available_power(params: BessParams, direction: str) -> float:
    """BESS 当前可用的快速功率（短周期回放；SOC 在正常区间 → 不瓶颈）。

    direction='charge'（D3-U，PV 富余吸收）→ 受 soc_max 与 P_charge_max 约束；
    direction='discharge'（D3-D，负荷补偿）→ 受 soc_min 与 P_discharge_max 约束。
    主场景 SOC=50% 在中间 → 可用功率 = P_BESS_max（不瓶颈）。
    """
    if direction == "charge":
        # SOC 已满则不能继续充；主场景 soc_init=0.5 < soc_max=0.9 → 不瓶颈
        if params.soc_init >= params.soc_max:
            return 0.0
        return params.p_bess_max_kw
    if direction == "discharge":
        if params.soc_init <= params.soc_min:
            return 0.0
        return params.p_bess_max_kw
    raise ValueError(f"未知 bess direction: {direction!r}（应为 charge/discharge）")
