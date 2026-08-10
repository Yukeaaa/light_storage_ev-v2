"""P1 正式 test runner（Phase 3 v1.0.2 §1.4/§1.5；Review 55/56 授权）。

执行序列（Review 55 授权 + Review 56 检查点）：
    --fit-train-edges   : 只在 office001 train 上拟合 q50/quartile edges，产出冻结
                          p1_train_edges.json（code-only，不读 test outcome）。
    --formal-test       : 单次 exposure。sentinel 在**读取 test outcome 之前**写入；
                          expected code SHA + clean worktree hard gate；test loader
                          与 pretest loader 物理路径分开；完成后锁死禁止重跑。
    --read-frozen       : 只读已冻结 verdict / manifest，绝不重算。

Review 56 检查点映射：
  1) train q50 只从 train 拟合（fit 阶段只读 train）；
  2) validation 仅用于 code verification，不改 q50/规则（formal 阶段不读 validation）；
  3) test loader 与 pretest loader 物理路径分开（本模块 _load_test_minutes vs
     step0._load_train_val_minutes）；
  4) started sentinel 写在读取 test outcome 之前；
  5) expected code SHA + clean worktree hard gate（test 暴露失败即中止）；
  6) 0/0、+∞、empty-state、duplicate-edge 全部由 rates.exhaustive_ratio / states 机器实现；
  7) bootstrap cluster 单位 = day（预注册一致）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pyarrow.dataset as ds

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.e1_full.gate import git_provenance
from patent_preexperiment.p1.bootstrap import cluster_bootstrap_rate_diff_ci
from patent_preexperiment.p1.features import (
    MIN_RECENT_SAMPLES,
    cycle_observables,
    e1_event_start_cycles,
)
from patent_preexperiment.p1.rates import (
    exhaustive_ratio,
    p1_verdict,
    quartile_direction,
    state_rates,
)
from patent_preexperiment.p1.states import (
    assign_states,
    fit_quartile_edges,
    fit_train_q50,
)
from patent_preexperiment.response.done import PHASE_CORE
from patent_preexperiment.response.e1_stats import process
from patent_preexperiment.response.events import GapThresholds

P1_SITE = "office001"

_MINUTE_COLUMNS = [
    "session_id",
    "station_id",
    "site",
    "garage",
    "field_mode",
    "match_status",
    "timestamp_utc",
    "actual_power_kw",
    "pilot_power_kw",
    "current_a",
    "pilot_a",
    "pilot_available",
    "connected_elapsed_min",
    "minutes_from_end",
    "gap_flag",
    "severe_gap_before",
    "disconnect_time",
    "done_charging_time",
]

_TRAIN_EDGES_PATH = "data_registry/p1_train_edges.json"
_SENTINEL_PATH = "results/raw/phase3_p1/p1_test_sentinel.json"
_SUMMARY_PATH = "results/raw/phase3_p1/p1_test_summary.json"
_MANIFEST_PATH = "results/raw/phase3_p1/p1_manifest.json"


def _load_split_minutes(
    minute_root: Path,
    registry: pd.DataFrame,
    split: str,
) -> pd.DataFrame:
    """Arrow query 层按 session membership 过滤加载指定 split（Review 56 纪律）。

    test/pretest loader 物理路径分开：本函数只被 formal 阶段调用，split 显式传入。
    加载后 fail-closed：loaded ids ⊆ 该 split 会话集。
    """
    allowed = set(registry.loc[registry["split"] == split, "session_id"])
    if not allowed:
        raise ValueError(f"P1 加载失败：split={split} 会话集为空")
    pred = (
        (ds.field("site") == P1_SITE)
        & (ds.field("match_status") == "matched")
        & ds.field("session_id").isin(sorted(allowed))
    )
    dataset = ds.dataset(str(minute_root))
    table = dataset.to_table(filter=pred, columns=_MINUTE_COLUMNS)
    df = cast(pd.DataFrame, table.to_pandas())
    loaded = set(df["session_id"])
    if not (loaded <= allowed):
        raise RuntimeError(
            f"P1 fail-closed：split={split} 加载会话超出允许面："
            f"n={len(loaded - allowed)}"
        )
    return df


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_fit_train_edges(impl_root: Path) -> dict[str, Any]:
    """只在 office001 train 上拟合 q50 与 quartile edges，产出冻结 edges（code-only）。"""
    cfg = load_yaml(impl_root / "configs" / "p1.yaml")
    registry = pd.read_parquet(
        impl_root / "data_registry" / "p1_office001_split_registry.parquet"
    )
    train_minutes = _load_split_minutes(
        impl_root / "datasets" / "session_response_1min", registry, "train"
    )
    obs_train = cycle_observables(train_minutes)
    train_q50 = fit_train_q50(obs_train)
    edges_result, edges_prov = fit_quartile_edges(obs_train)

    payload = {
        "experiment_id": cfg["experiment_id"],
        "protocol_version": cfg["protocol_version"],
        "scope": "P1 train-only edges fit（不读 validation/test outcome）",
        "site": P1_SITE,
        "min_recent_samples": MIN_RECENT_SAMPLES,
        "recent_var_definition": (
            "A5 同源：5-min cycle floor，shift(1).rolling(12, min_periods=2).var()，"
            "run 断裂 / cycle-gap>5min / severe_gap_at_start 重置"
        ),
        "train": {
            "n_sessions": int(train_minutes["session_id"].nunique()),
            "n_cycles": int(len(obs_train)),
            "n_evaluable_cycles": int(obs_train["median_recent_actual_var"].notna().sum()),
            "q50": train_q50,
        },
        "quartile_edges": edges_result,
        "fit_provenance": edges_prov,
        "rule": "train q50 与 quartile 边只在 office001 train 上拟合一次；validation 不改规则",
    }
    payload["provenance"] = git_provenance(impl_root.parent)
    _write_json(impl_root / _TRAIN_EDGES_PATH, payload)
    return payload


def run_formal_test(impl_root: Path, seed: int = 20240810) -> dict[str, Any]:
    """正式 test：单次 exposure，after 锁死。sentinel 先于读取 test outcome 写入。"""
    cfg = load_yaml(impl_root / "configs" / "p1.yaml")
    k1_cfg = load_yaml(impl_root / "configs" / "k1_preregister.yaml")
    thr = GapThresholds.from_cfg(k1_cfg)

    edges_path = impl_root / _TRAIN_EDGES_PATH
    if not edges_path.exists():
        raise FileNotFoundError("P1 formal test 前必须先 fit train edges")
    train_edges = _read_json(edges_path)

    sentinel_path = impl_root / _SENTINEL_PATH
    if sentinel_path.exists():
        existing = _read_json(sentinel_path)
        if existing.get("status") in ("running", "completed"):
            raise RuntimeError(
                "P1 formal test already exposed at "
                f"{existing.get('exposed_sha')!r} (sentinel: {sentinel_path}); rerun prohibited"
            )

    prov = git_provenance(impl_root.parent)
    expected_sha = train_edges["provenance"].get("code_sha")
    if not expected_sha or expected_sha == "unknown":
        raise RuntimeError("P1 hard gate：train edges 冻结时代码 SHA 未知，不能暴露 test")
    if prov["code_sha"] != expected_sha:
        raise RuntimeError(
            f"P1 hard gate：expected code SHA {expected_sha} != current {prov['code_sha']}"
        )
    if prov.get("worktree_clean") is not True:
        raise RuntimeError("P1 hard gate：worktree 不洁净，禁止暴露 formal test")

    # ④ sentinel 在读取 test outcome 之前写入
    sentinel = {
        "status": "running",
        "started_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "expected_code_sha": expected_sha,
        "code_sha": prov["code_sha"],
        "worktree_clean": prov["worktree_clean"],
        "exposed_sha": None,
    }
    _write_json(sentinel_path, sentinel)

    registry = pd.read_parquet(
        impl_root / "data_registry" / "p1_office001_split_registry.parquet"
    )
    test_minutes = _load_split_minutes(
        impl_root / "datasets" / "session_response_1min", registry, "test"
    )
    labeled, events, session_summary = process(test_minutes, thr)
    core_events = events[events["event_phase"] == PHASE_CORE]
    e1_cycles = e1_event_start_cycles(core_events)

    obs_test = cycle_observables(test_minutes)
    obs_states = assign_states(obs_test, train_edges["train"]["q50"])
    r = state_rates(obs_states, e1_cycles)
    ratio = exhaustive_ratio(r)
    ci = cluster_bootstrap_rate_diff_ci(obs_states, e1_cycles, seed=seed)
    quartile = quartile_direction(
        obs_states, train_edges["quartile_edges"], e1_cycles
    )

    summary = {
        "experiment_id": cfg["experiment_id"],
        "protocol_version": cfg["protocol_version"],
        "scope": "P1 formal test（单次 exposure，test E1 outcome）",
        "site": P1_SITE,
        "test": {
            "n_sessions": int(test_minutes["session_id"].nunique()),
            "n_cycles": int(len(obs_test)),
            "n_e1_core_events": int(len(core_events)),
            "n_e1_event_cycles": len(e1_cycles),
            "n_evaluable_cycles": int(obs_states["state"].isin(["S1", "S2"]).sum()),
            "n_s3_cycles": int((obs_states["state"] == "S3").sum()),
        },
        "s1_s2": {
            "n_s1": r.n_s1,
            "n_s2": r.n_s2,
            "n_e1_s1": r.n_e1_s1,
            "n_e1_s2": r.n_e1_s2,
            "rate_s1": round(r.rate_s1, 6),
            "rate_s2": round(r.rate_s2, 6),
            "rate_diff": round(r.rate_diff, 6),
            "rate_ratio": (
                float(ratio.ratio) if ratio.ratio is not None else None
            ),
            "ratio_kind": ratio.ratio_kind,
        },
        "inferential": {
            "bootstrap_unit": "day",
            "seed": seed,
            "ci95": [round(ci[0], 6), round(ci[1], 6)],
        },
        "quartile_direction": quartile,
        "verdict": p1_verdict(r, ratio, ci, quartile, pretest_ok=True),
        "pretest": {
            "reuse": "Step 0 判定 feasible（见 data_registry/p1_step0_feasibility.json）",
        },
    }
    _write_json(impl_root / _SUMMARY_PATH, summary)

    sentinel.update({"status": "completed", "exposed_sha": prov["code_sha"]})
    _write_json(sentinel_path, sentinel)

    manifest = {
        "experiment_id": cfg["experiment_id"],
        "protocol_version": cfg["protocol_version"],
        "batch": "p1_formal",
        "summary": str(Path(_SUMMARY_PATH).as_posix()),
        "sentinel": str(Path(_SENTINEL_PATH).as_posix()),
        "train_edges": str(Path(_TRAIN_EDGES_PATH).as_posix()),
        "code_sha": prov["code_sha"],
        "worktree_clean": prov["worktree_clean"],
        "once_only": True,
        "summary_payload": summary,
    }
    _write_json(impl_root / _MANIFEST_PATH, manifest)
    return summary


def read_frozen(impl_root: Path) -> dict[str, Any]:
    """只读已冻结 verdict，绝不重算、不写任何输出。"""
    summary_path = impl_root / _SUMMARY_PATH
    if not summary_path.exists():
        raise FileNotFoundError(f"P1 frozen summary 不存在：{summary_path}")
    return _read_json(summary_path)
