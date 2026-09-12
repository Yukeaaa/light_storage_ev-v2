"""阈值产生规则（**先冻结规则、后落数值**；A-EV 计划 §7）。

设计依据（2026-09-12 评审）：固定 2 kW 对 100 kW BESS 是 2%、对 60 kW 充电设备是
3.33% —— 对**异构资源不是同一个门槛含义**。因此把"阈值"拆成两层：

    ┌ 产生规则（rule）  ← **现在冻结**：写进配置与预注册，产生方式不再依结果变动
    └ 数值（value）     ← HIL commissioning 完成后按规则一次性算出并加锁

规则本身同样属于预注册内容：`k_sigma` / `alpha` / 分位 / 裕量 / 最短持续时长
都必须**在看正式结果之前**定死。本模块只负责"按规则算数"，不做任何拟合。

未提供 `thresholds_provenance` 时回落到 `attribution.*` 的标量配置（供单测与小规模
回归使用），此时 `band_by_rid` 为该标量，行为与 V0.1 一致。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .types import ResourceSpec


@dataclass(frozen=True)
class Thresholds:
    """按规则实例化后的阈值集合。"""

    band_by_rid: dict[str, float]
    default_band: float
    window_s: float
    persistence_n: int
    confirm_n: int
    provenance: dict[str, Any]

    def band(self, rid: str) -> float:
        return self.band_by_rid.get(rid, self.default_band)

    @property
    def is_rule_based(self) -> bool:
        return bool(self.provenance)


def _band_rule(r: dict[str, Any], p_rated: float) -> float:
    """偏差判定带：max(计量分辨率, k·噪声标准差, α·额定功率)。"""
    return max(
        float(r.get("meter_resolution_kw", 0.0)),
        float(r.get("k_sigma", 0.0)) * float(r.get("noise_sigma_kw", 0.0)),
        float(r.get("alpha", 0.0)) * float(p_rated),
    )


def _ceil_periods(min_s: float, dt_s: float) -> int:
    return max(1, int(math.ceil(min_s / dt_s)))


def build_thresholds(cfg: dict[str, Any], specs: list[ResourceSpec]) -> Thresholds:
    """按配置实例化阈值。规则在先、数值在后；数值缺失时回落到标量。"""
    attr = cfg["attribution"]
    prov = cfg.get("thresholds_provenance")
    fallback_band = float(attr["deviation_band_kw"])
    fallback_window = float(attr["response_window_s"])
    fallback_persist = int(attr["persistence_n"])
    fallback_confirm = int(cfg["recovery"]["confirm_n"])

    if not prov:
        by_rid = {s.rid: fallback_band for s in specs}
        return Thresholds(
            band_by_rid=by_rid,
            default_band=fallback_band,
            window_s=fallback_window,
            persistence_n=fallback_persist,
            confirm_n=fallback_confirm,
            provenance={},
        )

    dt = float(prov.get("data_dt_s", 1.0))
    band_rule = dict(prov.get("deviation_band", {}))
    by_rid = {s.rid: _band_rule(band_rule, s.p_rated) for s in specs}
    default_band = max(by_rid.values()) if by_rid else fallback_band

    win_rule = dict(prov.get("response_window", {}))
    p95 = win_rule.get("p95_step_response_time_s")
    # p95 为 commissioning 待落数值：未落定前回落到标量窗口，保证规则已冻结而数值待定
    window = (
        float(p95) + float(win_rule.get("margin_s", 0.0)) if p95 is not None else fallback_window
    )

    persist_rule = dict(prov.get("persistence", {}))
    persist_min = persist_rule.get("persistence_min_s")
    persistence_n = (
        _ceil_periods(float(persist_min), dt) if persist_min is not None else fallback_persist
    )

    confirm_rule = dict(prov.get("recovery_confirm", {}))
    confirm_min = confirm_rule.get("confirm_min_s")
    confirm_n = (
        _ceil_periods(float(confirm_min), dt) if confirm_min is not None else fallback_confirm
    )

    return Thresholds(
        band_by_rid=by_rid,
        default_band=default_band,
        window_s=window,
        persistence_n=persistence_n,
        confirm_n=confirm_n,
        provenance=prov,
    )
