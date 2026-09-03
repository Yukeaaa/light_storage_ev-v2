"""P2 Step0 — K1/K2/K3 kill gates（§5.8；全部冻结 JPL train + 固定 Caltech replay，不挑样本）。

- K1：D1 穷尽确定性 + 信息面变化真的产生不同 boundary mode → FAIL=STOP。
- K2：权限等级能编码为数值 action set 并改变 accept/clip（M2=1.0 / M4=0.0 /
  LOCKED≠PROTECTIVE≠NORMAL）→ FAIL=PROJECT_NO_GO（硬杀线）。
- K3：JPL train 存在不依赖通信/停充/reset 的 natural recovery trace → FAIL=PROJECT_NO_GO
  （v1.0.2：natural=0 即 PROJECT_NO_GO，replay 不得救）。

Step0 不是 test exposure：可重跑（只有正式 test 单次暴露 + sentinel 锁死）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from patent_preexperiment.e1_full.gate import git_provenance
from patent_preexperiment.phase3_p2.metrics import k1_verdict, k2_verdict, k3_verdict
from patent_preexperiment.phase3_p2.pipeline import (
    ReplayTransform,
    load_pool_minutes,
    process_pool,
    seeds_for_pool,
)
from patent_preexperiment.phase3_p2.schema import load_schema

NATURAL = "natural"
MASK = "mask_pilot"
TRUNCATE = "truncate_history"
INJECT = "inject_capability"

_REPLAY_TRANSFORMS = (
    ReplayTransform(name=NATURAL),
    ReplayTransform(name=MASK, mask_pilot=True),
    ReplayTransform(name=TRUNCATE, history_limit_per_run=4),
    ReplayTransform(name=INJECT, inject_capability=True),
)

_OUT_DIR = "results/raw/phase3_p2"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_step0(
    impl_root: Path,
    *,
    chunk_sessions: int = 800,
) -> dict[str, Any]:
    scfg = load_schema(impl_root / "configs" / "phase3_p2_action_schema.yaml")
    registry = pd.read_parquet(impl_root / "data_registry" / "e0_full_split_registry.parquet")
    minute_root = impl_root / "datasets" / "session_response_1min"

    jpl_train = load_pool_minutes(
        minute_root, registry, site="jpl", field_mode="current_only", split="train"
    )
    train_summary, train_traces = process_pool(
        jpl_train,
        scfg,
        seeds_for_pool(jpl_train),
        ReplayTransform(name=NATURAL),
        chunk_sessions=chunk_sessions,
    )

    caltech = load_pool_minutes(
        minute_root, registry, site="caltech", field_mode="measured_pilot", split="train"
    )
    caltech_seeds = seeds_for_pool(caltech)
    replay_summaries: dict[str, dict[str, Any]] = {}
    replay_traces: dict[str, pd.DataFrame] = {}
    for transform in _REPLAY_TRANSFORMS:
        summary, traces = process_pool(
            caltech,
            scfg,
            caltech_seeds,
            transform,
            chunk_sessions=chunk_sessions,
        )
        replay_summaries[transform.name] = summary
        replay_traces[transform.name] = traces

    k1 = k1_verdict(scfg, train_summary, replay_summaries)
    k2 = k2_verdict(scfg, train_summary)
    k3 = k3_verdict(scfg, train_summary)

    if k1 == "FAIL":
        step0_verdict = "STOP"
    elif k2 == "PROJECT_NO_GO":
        step0_verdict = "PROJECT_NO_GO"
    elif k3 == "PROJECT_NO_GO":
        step0_verdict = "PROJECT_NO_GO"
    else:
        step0_verdict = "PROCEED"

    prov = git_provenance(impl_root.parent)
    summary = {
        "experiment_id": scfg.experiment_id,
        "protocol_version": scfg.protocol_version,
        "scope": "P2 Step0 kill gates（JPL train natural + 固定 Caltech replay，不挑样本）",
        "schema": scfg.schema_path,
        "step0_verdict": step0_verdict,
        "kill_gates": {
            "K1_D1_mode_selection": {
                "verdict": k1,
                "fail_verdict": "STOP",
            },
            "K2_D2_action_set": {
                "verdict": k2,
                "fail_verdict": "PROJECT_NO_GO",
                "checks": {
                    "m2": train_summary["m2"],
                    "m2_disp_ok": train_summary["m2_disp_ok"],
                    "m4": train_summary["m4"],
                    "n_diff_lock_prot": train_summary["n_diff_lock_prot"],
                    "n_diff_prot_normal": train_summary["n_diff_prot_normal"],
                },
            },
            "K3_D3_recovery_trace": {
                "verdict": k3,
                "fail_verdict": "PROJECT_NO_GO",
                "n_jpl_train_natural_traces": train_summary["traces"]["n_traces_complete"],
            },
        },
        "jpl_train_natural": train_summary,
        "caltech_replay": {
            name: {
                "transform": {
                    "mask_pilot": bool(t.mask_pilot),
                    "inject_capability": bool(t.inject_capability),
                    "history_limit_per_run": t.history_limit_per_run,
                },
                "summary": replay_summaries[name],
                "traces": {
                    "n_traces_total": int(len(replay_traces[name])),
                    "n_traces_complete": int(
                        replay_traces[name]["complete"].sum()
                    ) if not replay_traces[name].empty else 0,
                },
            }
            for name, t in zip(
                [t.name for t in _REPLAY_TRANSFORMS], _REPLAY_TRANSFORMS, strict=True
            )
        },
        "provenance": prov,
    }
    return summary


def write_step0_evidence(impl_root: Path, summary: dict[str, Any]) -> tuple[Path, Path]:
    out_dir = impl_root / _OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "p2_step0_summary.json"
    _write_json(json_path, summary)
    report_path = out_dir / "p2_step0_report.md"
    _write_step0_report(report_path, summary)
    return json_path, report_path


def write_step0_traces(
    impl_root: Path,
    train_traces: pd.DataFrame,
    replay_traces: dict[str, pd.DataFrame],
) -> Path:
    out_dir = impl_root / _OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "p2_step0_traces.parquet"
    frames = []
    if not train_traces.empty:
        frames.append(train_traces.assign(pool="jpl_train_natural"))
    for name, tr in replay_traces.items():
        if not tr.empty:
            frames.append(tr.assign(pool=f"caltech_replay_{name}"))
    if frames:
        pd.concat(frames, ignore_index=True).to_parquet(path, index=False)
    else:
        pd.DataFrame(columns=["pool"]).to_parquet(path, index=False)
    return path


def _write_step0_report(report_path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# P2 Step0 — K1/K2/K3 kill gates",
        "",
        f"- experiment_id：{summary['experiment_id']}",
        f"- protocol_version：{summary['protocol_version']}",
        f"- scope：{summary['scope']}",
        "",
        f"## Step0 verdict：**`{summary['step0_verdict']}`**",
        "",
        "## Kill gates",
        "",
    ]
    gates = summary["kill_gates"]
    lines += [
        f"- **K1（D1 mode selection）**：`{gates['K1_D1_mode_selection']['verdict']}`"
        f"（FAIL → {gates['K1_D1_mode_selection']['fail_verdict']}）",
        f"- **K2（D2 action set）**：`{gates['K2_D2_action_set']['verdict']}`"
        f"（FAIL → {gates['K2_D2_action_set']['fail_verdict']}）",
        f"  - m2={gates['K2_D2_action_set']['checks']['m2']}、"
        f"m2_disp_ok={gates['K2_D2_action_set']['checks']['m2_disp_ok']}、"
        f"m4={gates['K2_D2_action_set']['checks']['m4']}、"
        f"n_diff_lock_prot={gates['K2_D2_action_set']['checks']['n_diff_lock_prot']}、"
        f"n_diff_prot_normal={gates['K2_D2_action_set']['checks']['n_diff_prot_normal']}",
        f"- **K3（D3 recovery trace）**：`{gates['K3_D3_recovery_trace']['verdict']}`"
        f"（FAIL → {gates['K3_D3_recovery_trace']['fail_verdict']}）",
        f"  - JPL train natural traces："
        f"{gates['K3_D3_recovery_trace']['n_jpl_train_natural_traces']}",
        "",
        "## JPL train natural（current-only）",
        "",
    ]
    lines += _summary_lines(summary["jpl_train_natural"])
    lines += [
        "",
        "## Caltech replay（mode-mechanism，单列辅助）",
        "",
    ]
    for name, entry in summary["caltech_replay"].items():
        lines += [f"### {name}", ""]
        lines += _summary_lines(entry["summary"])
        lines += [
            "",
            f"- traces：total={entry['traces']['n_traces_total']}，"
            f"complete={entry['traces']['n_traces_complete']}（不计入 natural）",
            "",
        ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def _summary_lines(s: dict[str, Any]) -> list[str]:
    return [
        f"- cycles：{s['n_cycles']:,}；sessions：{s['n_sessions']:,}；runs：{s['n_runs']:,}",
        f"- info_mode 分布：{s['mode_counts']}",
        f"- boundary_mode 分布：{s['boundary_mode_counts']}",
        f"- application_state 分布：{s['state_counts']}",
        f"- M1={s['m1']}（唯一 mode 比例）、M2={s['m2']}（n_eligible={s['n_eligible_m3_m4']:,}"
        f"）、m2_cov={s['m2_cov']}、M4={s['m4']}",
        f"- M3 traces：total={s['traces']['n_traces_total']}，"
        f"complete={s['traces']['n_traces_complete']}，"
        f"sessions={s['traces']['n_complete_sessions']}",
        f"- boundary_unavailable cycles：{s['n_boundary_unavailable']:,}",
        f"- release violations：{s['n_release_violations']}（n_protective_eligible="
        f"{s['n_protective_eligible']:,}）",
    ]
