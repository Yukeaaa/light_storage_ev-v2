"""E1-Full（R1 / E0F-06 硬切分复现）：主证据体系按 train/validation/test 分别复现 K1 E1。

R1 协议（review/审查结论7 §10.1）：沿用 K1 冻结阈值/事件定义/done-relative 阶段切断/
负对照/统计方法，不做任何 test 后调整；门标准用 e0_full.yaml k1_replication_stop_lines.e1。

与 E1-Lite 的差异（唯一变化=人口与切分）：
- 人口：main evidence universe（L1_strict_matched ∧ role==main ∧ split∈{train,val,test}）
  而非 K1 冻结 6 个月 CG1 样本；train/validation/test 各自独立统计。
- 不再做月份选择：分裂内全部月份；月份浓度按负对照报告（非门判定）。
- 随机种子：e0_full.yaml seeds（bootstrap=42, n_boot=2000, permutation=[7,11,13]）。
- R1 结论以 test split 为准（test 只跑一次，禁止回调参数）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.e1_full.loader import load_main_evidence_minutes, split_df
from patent_preexperiment.metrics.permutation import permutation_negative_control
from patent_preexperiment.response.done import PHASE_CORE
from patent_preexperiment.response.e1_stats import (
    build_fail_cases,
    core_stats,
    events_with_phase,
    negative_controls,
    phase_summary,
    process,
    session_rate,
)
from patent_preexperiment.response.events import GapThresholds

IMPL = Path(__file__).resolve().parents[2]  # patent_preexperiment 实现区
MINUTE_ROOT = IMPL / "datasets" / "session_response_1min"
REGISTRY = IMPL / "data_registry" / "e0_full_split_registry.parquet"
E0_CFG = load_yaml(IMPL / "configs" / "e0_full.yaml")
K1_CFG = load_yaml(IMPL / "configs" / "k1_preregister.yaml")
OUT = IMPL / "results" / "raw" / "E1F"
SEEDS = E0_CFG["seeds"]
PERM_SEEDS: list[int] = SEEDS["permutation"]
BOOT_SEED: int = SEEDS["bootstrap"]
N_BOOT: int = SEEDS["n_boot"]
STOP = E0_CFG["k1_replication_stop_lines"]["e1"]


def _per_split(
    split: str,
    df: pd.DataFrame,
    thr: GapThresholds,
    stop: dict,
) -> dict:
    sub = split_df(df, split)
    labeled, events, session_summary = process(sub, thr)

    mfe = events.merge(
        labeled[["session_id", "timestamp_utc", "minutes_from_end"]],
        left_on=["session_id", "start_utc"], right_on=["session_id", "timestamp_utc"], how="left",
    )
    events["minutes_from_disconnect_at_start"] = mfe["minutes_from_end"].values

    session_summary.to_csv(OUT / f"e1_full_{split}_session_summary.csv", index=False)
    phase_summary(events, labeled).to_csv(OUT / f"e1_full_{split}_phase_summary.csv", index=False)

    core_denom = labeled[
        (labeled["phase"] == PHASE_CORE) & labeled["charging_active"] & labeled["pilot_available"]
    ]["session_id"].nunique()
    core_events = events[events["event_phase"] == PHASE_CORE]
    core = core_stats(events, labeled, thr)

    month_rate: list[dict] = []
    for month, gm in labeled[labeled["phase"] == PHASE_CORE].groupby("cycle_month"):
        denom = gm[gm["charging_active"] & gm["pilot_available"]]["session_id"].nunique()
        ce = core_events[core_events["month"] == month]
        month_rate.append({
            "month": month, "n_denom_sessions": denom, "n_core_events": int(len(ce)),
            "core_event_session_rate": session_rate(ce, denom) if denom else 0.0,
            "core_energy_kwh": float(ce["gap_energy_kwh"].sum()),
        })
    month_rate_df = pd.DataFrame(month_rate)
    month_rate_df.to_csv(OUT / f"e1_full_{split}_month_summary.csv", index=False)

    neg = negative_controls(
        labeled, events, thr, session_summary, core_events,
        perm_seeds=PERM_SEEDS, bootstrap_seed=BOOT_SEED, n_boot=N_BOOT,
    )
    fail_cases = build_fail_cases(events, neg["time_permutation_core"]["perm_core_reference"],
                                  session_summary)
    fail_cases.to_csv(OUT / f"e1_full_{split}_fail_cases.csv", index=False)
    events.to_parquet(OUT / f"e1_full_{split}_event_table.parquet", index=False)

    perm = neg["time_permutation_core"]
    gates = {
        "pass_rate": core["event_session_rate"] >= stop["min_event_session_rate"],
        "pass_median": core["median_gap_kw"] >= stop["min_median_gap_kw"]
        or core["median_gap_ratio_of_working"] >= stop["min_median_gap_ratio"],
        "pass_permutation": bool(perm["diff_bootstrap_ci95"][0] > 0),
        "pass_not_single_station_or_month": bool(
            neg["max_single_station_share_core"] <= 0.50
            and neg["max_single_month_share_core"] <= 0.50
        ),
        "done_cutting_holds": bool(
            core["event_session_rate"] >= stop["min_event_session_rate"]
            and (core["median_gap_kw"] >= stop["min_median_gap_kw"]
                 or core["median_gap_ratio_of_working"] >= stop["min_median_gap_ratio"])
        ),
    }
    gates["all_pass"] = bool(all(gates.values()))

    return {
        "split": split,
        "n_valid_sessions": int(labeled["session_id"].nunique()),
        "n_rows": int(len(labeled)),
        "n_pilot_sessions": int(labeled[labeled["pilot_available"]]["session_id"].nunique()),
        "core_run": core,
        "month_summary": month_rate_df.to_dict("records"),
        "negative_controls": {
            k: v for k, v in neg.items() if k != "time_permutation_core"
        } | {
            "time_permutation_core": {
                k: v for k, v in perm.items()
                if k not in ("perm_core_reference", "_real_has", "_perm_has")
            }
        },
        "gates": gates,
    }


def run_e1_full() -> dict:
    thr = GapThresholds.from_cfg(K1_CFG)
    OUT.mkdir(parents=True, exist_ok=True)

    registry = pd.read_parquet(REGISTRY)
    minutes = load_main_evidence_minutes(MINUTE_ROOT, registry)

    per_split: list[dict] = []
    for split in ("train", "validation", "test"):
        per_split.append(_per_split(split, minutes, thr, STOP))

    test = next(d for d in per_split if d["split"] == "test")
    summary = {
        "experiment_id": "E1_Full_R1_replication",
        "protocol": "R1 K1 硬切分复现（审查结论7 §10.1），test 只跑一次",
        "population": (
            "main_evidence_universe = L1_strict_matched ∧ role==main ∧ "
            "split∈{train,validation,test}"
        ),
        "threshold": {
            k: getattr(thr, k)
            for k in ("p_on_kw", "delta_r", "delta_p_kw", "t_event_min",
                      "initial_exclusion_min", "tail_exclusion_min", "pilot_active_min_a")
        },
        "seeds": {"bootstrap": BOOT_SEED, "n_boot": N_BOOT, "permutation": PERM_SEEDS},
        "stop_lines": STOP,
        "per_split": per_split,
        "r1_verdict_on_test": {
            "test_n_sessions": test["n_valid_sessions"],
            "test_core_rate": test["core_run"]["event_session_rate"],
            "test_gates": test["gates"],
            "verdict": (
                "PASS" if test["gates"]["all_pass"] else "FAIL"
            ),
        },
        "caveat": (
            "test split 只有 2020-05/06/07/08/11 五个月、155 个主集会话（154 measured_pilot）；"
            "若 test 事件量过小需按 evaluable 规则单列报告，不得静默当零。"
        ),
    }
    (OUT / "e1_full_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    sys.exit(0 if run_e1_full() else 1)
