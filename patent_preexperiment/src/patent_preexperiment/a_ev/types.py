"""A-EV 基础类型与常量（V0.2 pre-freeze）。

**统一符号约定（全链共用，对应说明书 §8.1）**：

    P > 0  = 向站级母线注入功率（放电 / 光伏出力）
    P < 0  = 自站级母线吸收功率（充电 / 电动汽车负荷）

    执行偏差           e = P_req - P_meas
    e > 0  → 站级缺注入 → 站级缺口方向 = DIR_UP  （需补注入 / 减吸收）
    e < 0  → 站级注入过多 → 站级缺口方向 = DIR_DOWN（需补吸收 / 减注入）

**两个不可混用的量**（V0.2 关键修正，此前二者被混为一谈）：

    ① 站级缺口（gap_*）：由 `e` 的符号与大小决定——回答"站级要补多少、往哪个方向补"。
    ② 能力边界证据（req_dir / delivered_in_req_dir / deficit）：由**要求方向**上的
       交付水平决定——回答"该资源在哪个功率方向上被观测到只能做到多少"。

二者在"设备按要求方向欠交付"时数值相同（当前四类对照场景均属此列），但在
**过执行 / 反向执行**时不同：

    P_req = +20, P_meas = +40 → |e| = 20（站级多注入 20 → 下向缺口）
                                  deficit = 0（要求方向上足额交付，不构成能力受限证据）
    P_req = +20, P_meas = -20 → |e| = 40（站级缺 40）
                                  deficit = 20（该方向实际交付为 0，构成本方向能力受限证据）

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


class LimitDir(StrEnum):
    """本机限功率所在方向。

    **不复用 0 表示未知**（V0.2 修正）：未知方向不得作为任何方向的正向能力证据，
    因此单独设 UNKNOWN，另设 BOTH 表示"双方向同时受限"，避免语义复用。
    """

    UNKNOWN = "UNKNOWN"
    UP = "UP"
    DOWN = "DOWN"
    BOTH = "BOTH"


def limit_dir_matches(ld: LimitDir, direction: int) -> bool:
    """限值方向是否覆盖给定的功率方向。UNKNOWN 一律不匹配。"""
    if ld is LimitDir.BOTH:
        return True
    if ld is LimitDir.UP:
        return direction == DIR_UP
    if ld is LimitDir.DOWN:
        return direction == DIR_DOWN
    return False


class Truth(StrEnum):
    """事件真值（由场景生成器注入，控制策略不可见）。"""

    NORMAL = "NORMAL"                          # 正常小扰动
    COMM_FREEZE = "COMM_FREEZE"                # 通信 / 数据冻结：设备正常，观测陈旧
    TRANSIENT = "TRANSIENT"                    # 指令刚下发，仍处响应观察窗内
    LOCAL_LIMIT = "LOCAL_LIMIT"                # 本机限功率持续生效（真实能力受限）
    EXTERNAL_CONSTRAINT = "EXTERNAL_CONSTRAINT"  # 站级外部约束裁剪了动作


class Verdict(StrEnum):
    """有效性与能力归因判断的输出（模块 1）。

    **两层结果**（V0.2）：先做「有效性判定」，再做「能力归因」。
      · 通过有效性判定、且在该要求方向上构成欠交付 → VALID_CAPABILITY_LIMIT（允许更新边界）
      · 通过有效性判定、但在要求方向上并未欠交付（过执行 / 反向执行）
        → VALID_EXECUTION_DEVIATION（**有效执行偏差**，构成站级缺口来源，但**不**更新边界）
      · TRANSIENT / COMM_INVALID / EXTERNAL_CONSTRAINT / UNCERTAIN → 既不入缺口、也不更新

    与权项对应：权 3 显式枚举通信无效 / 暂态响应 / 持续可用能力受限三类；
    EXTERNAL_CONSTRAINT 与 UNCERTAIN 均落在权 1【b】"资源局部运行条件"这一上位判定信息
    之下，处置为"排除该偏差"或"暂缓更新"（说明书 §6.1 判据 4），不构成超出权项的新类别。
    """

    VALID_CAPABILITY_LIMIT = "VALID_CAPABILITY_LIMIT"      # 可持续可用能力受限 → 允许更新
    VALID_EXECUTION_DEVIATION = "VALID_EXECUTION_DEVIATION"  # 有效偏差但不表征能力受限
    TRANSIENT = "TRANSIENT"                                # 暂态响应 → 暂缓更新
    COMM_INVALID = "COMM_INVALID"                          # 通信 / 数据无效 → 不作为能力证据
    EXTERNAL_CONSTRAINT = "EXTERNAL_CONSTRAINT"            # 外部约束引起 → 不作为能力证据
    UNCERTAIN = "UNCERTAIN"                                # 证据不足 → 暂缓


#: 允许更新方向化可用能力状态的归因结论
UPDATING_VERDICTS = frozenset({Verdict.VALID_CAPABILITY_LIMIT})

#: 允许作为**站级缺口**来源的归因结论（经有效性判定确认成立的执行偏差）
ADMISSIBLE_VERDICTS = frozenset(
    {Verdict.VALID_CAPABILITY_LIMIT, Verdict.VALID_EXECUTION_DEVIATION}
)


@dataclass(frozen=True)
class Deviation:
    """统一执行偏差（全链共用同一套约定；见模块 docstring）。"""

    req_dir: int                      # 功率控制要求的方向（DIR_UP / DIR_DOWN）
    signed: float                     # e = P_req - P_meas
    gap_direction: int                # 站级缺口方向（sign(e)；0 = 无）
    gap_magnitude: float              # 站级缺口大小 = |e|
    delivered_in_req_dir: float       # 要求方向上实际达到的**功率水平**（≥0）
    deficit: float                    # 要求方向上的欠交付量（≥0）

    @property
    def evidences_limitation(self) -> bool:
        """该偏差是否在要求方向上构成欠交付（= 是否**可能**表征能力受限）。"""
        return self.deficit > 0.0


def deviation_of(p_req: float, p_meas: float) -> Deviation:
    """由功率控制要求与观测执行结果构造统一执行偏差。"""
    req_dir = DIR_UP if p_req >= 0.0 else DIR_DOWN
    signed = p_req - p_meas
    if signed > 0.0:
        gap_dir = DIR_UP
    elif signed < 0.0:
        gap_dir = DIR_DOWN
    else:
        gap_dir = 0
    delivered = max(0.0, req_dir * p_meas)
    deficit = max(0.0, abs(p_req) - delivered)
    return Deviation(
        req_dir=req_dir,
        signed=signed,
        gap_direction=gap_dir,
        gap_magnitude=abs(signed),
        delivered_in_req_dir=delivered,
        deficit=deficit,
    )


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
    local_limit_dir: LimitDir       # 限功率所在方向（UNKNOWN = 未知，不作正向证据）
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
    true_deviation: float           # 真实执行偏差（按统一约定 = P_req_effective - P_meas_true）
    observed_deviation: float       # 控制器所见偏差（= P_req_effective - P_meas_seen）


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

    up_bound / down_bound 为**能力边界**（非负，kW），分别对应注入与吸收方向的
    **可持续功率水平**；confidence 为对应可信度（0–1）。单边资源只维护其存在的那一侧。
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
    deviation: Deviation
    evidence_direction: int          # 能力边界证据方向（= 要求方向）
    evidence_level: float            # 该方向上观测到的可持续功率水平（用于收缩边界）
    evidence: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def of(
        cls,
        verdict: Verdict,
        p_req: float,
        p_meas: float,
        evidence: dict[str, Any] | None = None,
    ) -> AttributionResult:
        d = deviation_of(p_req, p_meas)
        return cls(
            verdict=verdict,
            deviation=d,
            evidence_direction=d.req_dir,
            evidence_level=d.delivered_in_req_dir,
            evidence=evidence or {},
        )

    @property
    def allows_update(self) -> bool:
        return self.verdict in UPDATING_VERDICTS

    @property
    def admissible(self) -> bool:
        """是否可作为站级缺口来源。"""
        return self.verdict in ADMISSIBLE_VERDICTS

    # -- 便于阅读的别名（缺口口径与证据口径显式分开）------------------
    @property
    def gap_direction(self) -> int:
        return self.deviation.gap_direction

    @property
    def gap_magnitude(self) -> float:
        return self.deviation.gap_magnitude

    @property
    def direction(self) -> int:
        """兼容别名：能力证据方向。"""
        return self.evidence_direction

    @property
    def magnitude(self) -> float:
        """兼容别名：要求方向上的欠交付量。"""
        return self.deviation.deficit


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
