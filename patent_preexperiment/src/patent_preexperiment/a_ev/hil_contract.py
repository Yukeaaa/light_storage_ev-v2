"""A-EV HIL 数据合同与准入门（对应 A-EV 计划「前置条件核对 / 字段级准入审计」）。

定位：在 HIL adapter 写代码**之前**，把"现场数据拿不拿得到"变成**可机器判定**的
准入检查。纪律（评审 2026-09-12）：**少任何一层，都必须在准入门明确标成
"某类机制不可验证"，而不是事后猜。**

字段 → 机制依赖合同（`CONTRACT_FIELDS`）给出 HIL 第一阶段强制记录的字段清单
（command_id / requested / translated / accepted / write_ack / control_owner /
override_source / override_reason / applied_timestamp / P_meas / PCC，以及约束类
字段），每个字段声明其责任域与**依赖它的机制**；`admit()` 按声明可得性输出
逐机制判定（VERIFIABLE / DERIVED / NOT_VERIFIABLE）与整体准入结论：

    ADMITTED     全字段可得 + 时钟统一 + 单一控制权 → formal 全机制可验证
    CONDITIONAL  核心闭环可得，部分机制因缺层/推导口径标记为不可验证（须在报告中列明）
    REJECTED     核心闭环不可得（无执行偏差可言）/ 时钟超预算 / 控制权多主
                 —— 不得进入 HIL commissioning，先修数据链

判定规则与字段清单属于**预注册内容**：随 HIL 场景集冻结，不依结果变动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 整体准入结论
ADMITTED = "ADMITTED"
CONDITIONAL = "CONDITIONAL"
REJECTED = "REJECTED"


@dataclass(frozen=True)
class FieldSpec:
    """一个合同字段：责任域 + 依赖它的机制 + 是否允许声明推导口径。"""

    key: str
    # 责任域：ems / gateway / device / bms / adapter / pcc_meter / derived
    source: str
    feeds: tuple[str, ...]           # 依赖该字段的机制（缺失 ⇒ 这些机制标记不可验证）
    derived_ok: bool = False         # True = 可用 derivation 声明（如由 BMS 限值 + 控制日志推导）


#: HIL 第一阶段强制记录的字段清单（评审 2026-09-12；顺序即数据链次序）
CONTRACT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("command_id", "ems",
              ("审计留痕", "M6 写回关联")),
    FieldSpec("requested_setpoint", "ems",
              ("M1 执行偏差", "M2 能力学习", "M3 站级缺口")),
    FieldSpec("translated_setpoint", "gateway",
              ("M1 上报限值区分", "Reported 包络"),
              derived_ok=True),
    FieldSpec("accepted_setpoint", "device",
              ("M1 上报限值区分", "M6 写回", "Reported 包络", "commissioning 响应窗"),
              derived_ok=True),
    FieldSpec("write_ack", "adapter",
              ("M6 写回", "控制权仲裁")),
    FieldSpec("control_owner", "ems",
              ("错误归因防线（控制权仲裁）",)),
    FieldSpec("override_source", "device",
              ("M1 外部约束/保护/模式判据",),
              derived_ok=True),
    FieldSpec("override_reason", "device",
              ("M1 外部约束/保护/模式判据",),
              derived_ok=True),
    FieldSpec("applied_timestamp", "device",
              ("M1 响应观察窗", "commissioning 响应窗标定")),
    FieldSpec("p_meas", "device",
              ("M1 执行偏差", "M2 能力学习", "M6 写回", "commissioning 噪声标定")),
    FieldSpec("pcc", "pcc_meter",
              ("模块6 PCC 残差通道", "PCC 主指标")),
    FieldSpec("soc", "bms",
              ("M3/M5 可行域（SOC 约束）",)),
    FieldSpec("temp_c", "bms",
              ("M3/M5 可行域（温度约束）",)),
    FieldSpec("local_limits", "bms_pcs",
              ("Reported 包络", "M3/M5 可行域")),
    FieldSpec("p_min_p_max", "derived",
              ("M3/M5 动态可行域",),
              derived_ok=True),
)

#: 缺失即整体 REJECT 的核心字段（无执行偏差可言）
CORE_FIELDS = frozenset({"requested_setpoint", "p_meas"})


@dataclass(frozen=True)
class MechanismVerdict:
    """单个机制的可验证性判定。"""

    mechanism: str
    verifiable: bool
    derived: bool = False            # True = 依赖推导口径，报告中必须标注口径
    reason: str | None = None


@dataclass
class AdmissionReport:
    """准入结论：逐机制判定 + 整体决定 + 须在报告中列明的缺口。"""

    decision: str
    mechanisms: list[MechanismVerdict] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    derived_fields: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def not_verifiable(self) -> list[MechanismVerdict]:
        return [m for m in self.mechanisms if not m.verifiable]


def _mechanism_index() -> dict[str, list[str]]:
    """机制 → 依赖字段（由 CONTRACT_FIELDS 反转）。"""
    idx: dict[str, list[str]] = {}
    for spec in CONTRACT_FIELDS:
        for mech in spec.feeds:
            idx.setdefault(mech, []).append(spec.key)
    return idx


def load_contract(path: str) -> dict[str, Any]:
    """加载合同 YAML（浅校验顶层结构）。"""
    import yaml

    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    if "hil_contract" not in cfg:
        raise ValueError(f"{path}: 缺少 hil_contract 顶层节")
    return dict(cfg)


def admit(cfg: dict[str, Any]) -> AdmissionReport:
    """按合同配置输出逐机制可验证性判定与整体准入结论。

    合同配置结构（`configs/a_ev_hil_contract.yaml`）：

        hil_contract:
          fields:
            <key>: {available: bool, derivation: str | null}
          clock: {unified: bool, max_skew_s: float, actual_skew_s: float}
          control_authority: {single_owner: bool, owners: [...]}
    """
    hc = cfg.get("hil_contract") or {}
    fields_cfg: dict[str, Any] = hc.get("fields") or {}
    clock: dict[str, Any] = hc.get("clock") or {}
    authority: dict[str, Any] = hc.get("control_authority") or {}

    rep = AdmissionReport(decision=ADMITTED)
    mech_fields = _mechanism_index()
    unavailable: set[str] = set()
    derived: set[str] = set()

    # ---- 字段级判定
    for spec in CONTRACT_FIELDS:
        entry = fields_cfg.get(spec.key)
        if entry is None or not bool(entry.get("available")):
            derivation = (entry or {}).get("derivation")
            if spec.derived_ok and derivation:
                derived.add(spec.key)
                rep.derived_fields.append(f"{spec.key} ← {derivation}")
                continue
            unavailable.add(spec.key)
            rep.missing_fields.append(spec.key)
        elif (entry or {}).get("derivation"):
            derived.add(spec.key)
            rep.derived_fields.append(f"{spec.key} ← {entry['derivation']}")

    # ---- 机制级判定：依赖任一不可得字段 ⇒ 不可验证；含推导字段 ⇒ 可验证但须标口径
    for mech, deps in sorted(mech_fields.items()):
        miss = [d for d in deps if d in unavailable]
        has_derived = any(d in derived for d in deps)
        if miss:
            rep.mechanisms.append(
                MechanismVerdict(
                    mechanism=mech, verifiable=False,
                    reason=f"缺层：{', '.join(miss)}（{mech} 不可验证，不得事后猜）",
                )
            )
        else:
            rep.mechanisms.append(
                MechanismVerdict(mechanism=mech, verifiable=True, derived=has_derived,
                                 reason="依赖推导口径" if has_derived else None)
            )

    # ---- 时钟纪律：统一时钟是时序判据与标定的前提（秒级偏差即混淆暂态/限值/能力受限）
    unified = bool(clock.get("unified"))
    skew = float(clock.get("actual_skew_s", 0.0) or 0.0)
    budget = float(clock.get("max_skew_s", 0.5) or 0.0)
    if not unified or skew > budget:
        rep.notes.append(
            f"时钟{'未统一' if not unified else ''}偏差 {skew}s > 预算 {budget}s："
            "响应观察窗/标定/暂态-限值区分的时序判据系统性失效"
        )
        rep.mechanisms.append(
            MechanismVerdict(mechanism="时序判据与 commissioning 标定（统一时钟前提）",
                             verifiable=False,
                             reason=f"时钟偏差 {skew}s 超预算 {budget}s")
        )

    # ---- 控制权纪律：存在隐形上游（本地 EMS/消防/削峰/BMS/厂家云）⇒ 错误归因不可控
    if not bool(authority.get("single_owner")):
        rep.notes.append("控制权非单一（存在隐形上游写点）：错误归因风险不可控")
        owners_str = ", ".join(map(str, authority.get("owners", [])))
        rep.mechanisms.append(
            MechanismVerdict(mechanism="错误归因防线（控制权仲裁）", verifiable=False,
                             reason="控制权非单一：" + owners_str)
        )

    # ---- 整体结论
    hard_fail = (
        bool(CORE_FIELDS & set(rep.missing_fields))
        or not unified
        or skew > budget
        or not bool(authority.get("single_owner"))
    )
    if hard_fail:
        rep.decision = REJECTED
    elif rep.not_verifiable():
        rep.decision = CONDITIONAL
    elif rep.derived_fields:
        # 推导口径 = 可验证但属降级证据通道：commissioning 期间须实测验证推导链，
        # 验证通过前整体保持 CONDITIONAL，报告中必须逐条标注口径。
        rep.decision = CONDITIONAL
        rep.notes.append(
            "存在推导口径字段（" + ", ".join(rep.derived_fields)
            + "）：commissioning 期间须实测验证推导链后方可升级 ADMITTED"
        )
    else:
        rep.decision = ADMITTED
    if rep.missing_fields:
        rep.notes.append("缺层字段 " + ", ".join(rep.missing_fields) + " → 对应机制已标记不可验证")
    return rep


__all__ = [
    "ADMITTED", "CONDITIONAL", "REJECTED", "CONTRACT_FIELDS", "CORE_FIELDS",
    "AdmissionReport", "FieldSpec", "MechanismVerdict", "admit", "load_contract",
]
