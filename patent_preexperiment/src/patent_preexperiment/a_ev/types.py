"""A-EV 基础类型与常量。

符号约定（全包统一，对应说明书 §8.1）：
    P > 0  = 向站级母线注入功率（放电 / 光伏出力）
    P < 0  = 自站级母线吸收功率（充电 / 电动汽车负荷）
    站级净交换量 P_station = Σ P_i，与站点计划值 P_plan 比较得到站级偏差。

方向常量：
    DIR_UP   = +1  注入方向（上向）
    DIR_DOWN = -1  吸收方向（下向）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

DIR_UP = 1
DIR_DOWN = -1


class Truth(StrEnum):
    """事件真值（由场景生成器注入，控制策略不可见）。"""

    NORMAL = "NORMAL"                          # 正常小扰动
    COMM_FREEZE = "COMM_FREEZE"                # 通信 / 数据冻结：设备正常，观测陈旧
    TRANSIENT = "TRANSIENT"                    # 指令刚下发，仍处响应观察窗内
    LOCAL_LIMIT = "LOCAL_LIMIT"                # 本机限功率持续生效（真实能力受限）
    EXTERNAL_CONSTRAINT = "EXTERNAL_CONSTRAINT"  # 站级外部约束裁剪了动作


class Verdict(StrEnum):
    """有效性与能力归因判断的输出（模块 1）。

    与权 1【b】/ 权 3 的对应：
      权 3 显式枚举三类：通信无效对应的偏差 / 暂态响应对应的偏差 / 持续可用能力受限对应的偏差。
      本实现另设 EXTERNAL_CONSTRAINT 与 UNCERTAIN，二者均落在权 1【b】"资源局部运行条件"
      这一上位判定信息之下，处置为"排除该偏差"或"暂缓更新"（说明书 §6.1 判据 4），
      不构成超出权项的新类别，仅为实现层细化。
    """

    VALID_CAPABILITY_LIMIT = "VALID_CAPABILITY_LIMIT"  # 可持续可用能力受限 → 允许更新
    TRANSIENT = "TRANSIENT"                            # 暂态响应 → 暂缓更新
    COMM_INVALID = "COMM_INVALID"                      # 通信 / 数据无效 → 不作为能力证据
    EXTERNAL_CONSTRAINT = "EXTERNAL_CONSTRAINT"        # 外部约束引起 → 不作为能力证据
    UNCERTAIN = "UNCERTAIN"                            # 证据不足 → 暂缓


#: 允许更新方向化可用能力状态的归因结论
UPDATING_VERDICTS = frozenset({Verdict.VALID_CAPABILITY_LIMIT})


@dataclass(frozen=True)
class ResourceSpec:
    """可控资源的静态与运行参数。"""

    rid: str
    p_rated: float                  # 额定功率（kW，正数）
    #: True = 双向可调；False = **仅下向（吸收）**，即说明书 §12 的"仅支持单向调节的资源"
    bidirectional: bool = True
    soc: float = 0.5                # 荷电状态 0–1
    temp_c: float = 25.0
    p_local_max_up: float | None = None    # 本机上向可用上限（kW）；None = 取额定
    p_local_max_down: float | None = None  # 本机下向可用上限（kW，正数）；None = 取额定
    ramp_kw_per_s: float = 5.0      # 爬坡率
    mode: str = "normal"            # 控制模式
    protection: bool = False        # 保护状态

    def up_limit(self) -> float:
        if not self.bidirectional:
            return 0.0
        lim = self.p_rated if self.p_local_max_up is None else self.p_local_max_up
        base = min(self.p_rated, lim)
        return max(0.0, base)

    def down_limit(self) -> float:
        # 下向（吸收）能力：双向资源与"仅吸收"的单向资源都存在；方向限值只由额定/本机限值决定
        lim = self.p_rated if self.p_local_max_down is None else self.p_local_max_down
        base = min(self.p_rated, lim)
        return max(0.0, base)


@dataclass
class Obs:
    """某一时刻、某一资源的观测（= 控制策略可见的全部信息）。"""

    t: float
    rid: str
    p_req: float                    # 该资源当前的功率控制要求（kW，站级符号）
    p_meas: float                   # 控制器所见的实际执行结果（可能因通信冻结而陈旧）
    cmd_sent_t: float               # 本次功率控制要求的下发时刻
    resp_start_t: float | None      # 响应开始时刻（设备上报）
    comm_ok: bool                   # 通信是否有效
    data_fresh: bool                # 数据是否新鲜（未冻结 / 未缺测）
    ts_aligned: bool                # 时间戳是否对齐
    local_limit_active: bool        # 本机持续限功率是否激活
    local_limit_dir: int            # 限功率所在方向（DIR_UP / DIR_DOWN / 0 未知）
    mode_switch: bool               # 是否处于控制模式切换（瞬时）
    protection_event: bool          # 是否处于保护转换瞬间（瞬时）
    station_constraint_active: bool  # 站级约束是否生效（控制器自身可知）
    soc: float
    temp_c: float


@dataclass
class TruthRow:
    """与 Obs 同时刻的事件真值（仅用于评价，控制策略不可见）。"""

    t: float
    rid: str
    truth: Truth
    true_deviation: float           # 真实执行偏差（p_meas_true - p_req）
    observed_deviation: float       # 控制器所见偏差（p_meas - p_req）


@dataclass
class PlantRow:
    """plant 真值（仅用于评价与指标）。"""

    t: float
    rid: str
    p_req_effective: float          # 含承接修正后的有效要求
    p_meas_true: float              # 真实执行结果
    dispatched_correction: float    # 本步下发给该资源的功率修正量


@dataclass
class CapabilityState:
    """方向化可用能力状态（模块 2）。

    up_bound / down_bound 为**能力边界**（非负，kW），分别对应注入与吸收方向；
    confidence 为对应可信度（0–1）。单边资源只维护其存在的那一侧。
    """

    rid: str
    up_bound: float
    down_bound: float
    up_conf: float = 0.5
    down_conf: float = 0.5
    last_confirmed_t: float = 0.0
    init_source: str = "rated"

    def bound(self, direction: int) -> float:
        return self.up_bound if direction == DIR_UP else self.down_bound

    def conf(self, direction: int) -> float:
        return self.up_conf if direction == DIR_UP else self.down_conf


@dataclass
class AttributionResult:
    """模块 1 输出。"""

    verdict: Verdict
    direction: int                  # 偏差所处功率方向
    magnitude: float                # |偏差|
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def allows_update(self) -> bool:
        return self.verdict in UPDATING_VERDICTS


@dataclass
class Dispatch:
    """模块 4 输出的一条承接指令。"""

    t: float
    carrier_rid: str
    correction: float               # 功率修正量（kW，站级符号）
    direction: int
    reason: str = ""


@dataclass
class StationGap:
    """模块 3 输出。"""

    t: float
    direction: int                  # 缺口方向（0 = 无缺口）
    magnitude: float                # 缺口大小（kW）
    contributors: list[str] = field(default_factory=list)
