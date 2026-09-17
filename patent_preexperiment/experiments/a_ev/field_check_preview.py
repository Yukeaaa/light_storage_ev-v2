#!/usr/bin/env python3
"""HIL 场地字段核对 → 准入门后果速查（核对清单配套工具，**非现场判定**）。

定位
----
现场字段核对清单（`reports/patent_definition/A-EV_HIL场地字段核对清单与映射表_V0.1.md`）
要求逐字段只给四种结论：``DIRECT / DERIVED / MISSING / UNKNOWN``。
本工具把**结论组合**映射到既有准入门（`a_ev.hil_contract.admit()`）的
**整体结论**（ADMITTED / CONDITIONAL / REJECTED）与**逐机制判定**，
让清单上每一个答案都有明确的、可预见的后果。

纪律（不得违反）
----------------
* 本工具**不改动**合同语义、字段清单与判定规则；只是把结论喂给既有 ``admit()``。
* 本工具输出**不是**现场判定 —— 现场结论须由核对表实测填写（附证据）。
* ``UNKNOWN`` 在准入门里**没有表示**：本工具一律按 ``MISSING`` 保守代入以便展示后果，
  但**核对表只要还有 UNKNOWN，字段合同即视为 NOT STABLE，不得进入 adapter 实现**。
* 不写 adapter、不连线、不做仿真。

运行
----
    ..\\..\\venv\\Scripts\\python.exe experiments/a_ev/field_check_preview.py
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from patent_preexperiment.a_ev.hil_contract import CONTRACT_FIELDS, admit, load_contract

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "configs" / "a_ev_hil_contract.yaml"

#: 四种现场结论
DIRECT = "DIRECT"
DERIVED = "DERIVED"
MISSING = "MISSING"
UNKNOWN = "UNKNOWN"

#: 推导口径的"材料清单"（现场须逐份确认可获取；缺任一 ⇒ DERIVED 不成立）
MATERIALS: dict[str, str] = {
    "translated_setpoint": "网关翻译值外露（网关配置/报文镜像）",
    "accepted_setpoint": "BMS 充放限值寄存器 + PCS 限功率寄存器 + 控制日志（三份缺一不可）",
    "override_source": "设备 override 标识位/事件记录",
    "override_reason": "设备 override 原因码表 + 事件记录",
    "p_min_p_max": "local_limits ∩ SOC/温度约束推导",
}


def _apply(cfg: dict[str, Any], verdicts: dict[str, str]) -> dict[str, Any]:
    """把字段结论写入合同副本（不改原文件）。UNKNOWN 按 MISSING 保守代入。"""
    out = copy.deepcopy(cfg)
    fields = out["hil_contract"]["fields"]
    for spec in CONTRACT_FIELDS:
        v = verdicts.get(spec.key, DIRECT)
        if v in (MISSING, UNKNOWN):
            fields[spec.key] = {"available": False}
        elif v == DERIVED:
            fields[spec.key] = {
                "available": False,
                "derivation": MATERIALS.get(spec.key, "（现场未登记材料清单）"),
            }
        else:
            fields[spec.key] = {"available": True}
    return out


def _all_direct(overrides: dict[str, str] | None = None) -> dict[str, str]:
    v = {spec.key: DIRECT for spec in CONTRACT_FIELDS}
    v.update(overrides or {})
    return v


SCENARIOS: list[tuple[str, dict[str, str], dict[str, Any]]] = [
    ("S0 现状（预登记口径，yaml 原样）", {}, {}),
    ("S1 全部 DIRECT（含 accepted 实测外露）", _all_direct(), {}),
    ("S2 accepted=DERIVED，材料齐全", _all_direct({"accepted_setpoint": DERIVED}), {}),
    ("S3 accepted=MISSING（推导材料取不到）", _all_direct({"accepted_setpoint": MISSING}), {}),
    ("S4 override_source/reason=MISSING",
     _all_direct({"accepted_setpoint": DERIVED,
                  "override_source": MISSING,
                  "override_reason": MISSING}), {}),
    ("S5 独立 PCC 表计 MISSING",
     _all_direct({"accepted_setpoint": DERIVED, "pcc": MISSING}), {}),
    ("S6 requested_setpoint MISSING（核心字段）", _all_direct({"requested_setpoint": MISSING}), {}),
    ("S7 p_meas MISSING（核心字段）", _all_direct({"p_meas": MISSING}), {}),
    ("S8 时钟偏差 1.2s > 预算 0.5s",
     _all_direct({"accepted_setpoint": DERIVED}),
     {"clock": {"unified": False, "max_skew_s": 0.5, "actual_skew_s": 1.2}}),
    ("S9 控制权非单一（存在隐形上游）",
     _all_direct({"accepted_setpoint": DERIVED}),
     {"control_authority": {"single_owner": False,
                            "owners": ["ems_a", "pcs_local", "vendor_cloud"]}}),
]


def main() -> None:
    base = load_contract(str(CONTRACT_PATH))
    rows: list[dict[str, Any]] = []

    for name, verdicts, patches in SCENARIOS:
        if verdicts:
            cfg = _apply(base, verdicts)
        else:
            cfg = copy.deepcopy(base)
        for section, val in patches.items():
            cfg["hil_contract"][section] = val
        rep = admit(cfg)
        nv = [m.mechanism for m in rep.not_verifiable()]
        rows.append(
            {
                "scenario": name,
                "decision": rep.decision,
                "n_not_verifiable": len(nv),
                "not_verifiable": nv,
                "derived_field_count": len(rep.derived_fields),
                "missing_fields": rep.missing_fields,
                "notes": rep.notes,
            }
        )

    dest = Path(__file__).resolve().parents[2] / "results" / "raw" / "a_ev_field_check"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "verdict_consequence_preview.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = ["# 字段结论 → 准入门后果速查（预演）", ""]
    lines += ["| 情形 | 整体结论 | NOT_VERIFIABLE 机制数 | 不可验证机制 | 推导字段数 |",
              "|---|---|---|---|---|"]
    for r in rows:
        mechs = "；".join(r["not_verifiable"]) if r["not_verifiable"] else "—"
        lines.append(
            f"| {r['scenario']} | **{r['decision']}** | {r['n_not_verifiable']} | {mechs} | "
            f"{r['derived_field_count']} |"
        )
    (dest / "verdict_consequence_preview.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for r in rows:
        print(f"{r['decision']:12s} | {r['scenario']}")
        for m in r["not_verifiable"]:
            print(f"               └ NOT_VERIFIABLE: {m}")
    print(f"\n[written] {dest}")


if __name__ == "__main__":
    main()
