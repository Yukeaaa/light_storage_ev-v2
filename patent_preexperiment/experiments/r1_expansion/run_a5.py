"""R1 最终收敛审计 A5 确定性生成器（审查结论47；protocol v1.2 FINAL FREEZE）。

严格实现 R1_A5_protocol_amendment.md v1.2：
- 五单变量 fixed buckets（n_active/elapsed pre-existing；recent_actual_q90/
  recent_var/lagged_pilot_actual_ratio train-only ECDF quartile）
- 唯一交互 n_active × elapsed
- 19-column output schema + na_reason
- daily-share bucket-restricted E3/K1 exact evaluable-day
- elimination 1 - rate/rate_A0（A0=0→NA）
- E1 event-start cycle snapshot
- direction_vs_reference = pooled population fixed reference

只读 frozen evidence + registry + minute table；不重跑 formal；deterministic。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

IMPL = Path(__file__).resolve().parents[2]
REPO = IMPL.parent
REG = IMPL / "data_registry" / "e0_full_split_registry.parquet"
MINUTE_ROOT = IMPL / "datasets" / "session_response_1min"
E3_FORMAL = IMPL / "results" / "raw" / "E3F"
E3_PRETEST = IMPL / "results" / "work" / "E3F_pretest"
E1_DIR = IMPL / "results" / "raw" / "E1F"
PREREG = IMPL / "configs" / "r1_expansion_audit.yaml"
PROTOCOL = IMPL / "reports" / "R1_A5_protocol_amendment.md"
OUT = IMPL / "results" / "raw" / "E3F_expansion"
OUT.mkdir(parents=True, exist_ok=True)

SPLITS = ("train", "validation", "test")
POOLS = ("caltech", "jpl")

CONCURRENCY_BUCKETS = [0, 2, 4, 8, 16, 1000]
CONCURRENCY_LABELS = ["1", "2-3", "4-7", "8-15", "16+"]
ELAPSED_BUCKETS = [0, 30, 60, 120, 240, 100000]
ELAPSED_LABELS = ["<30", "30-59", "60-119", "120-239", "240+"]

MINUTE_COLS = [
    "session_id", "site", "station_id", "timestamp_utc",
    "connected_elapsed_min", "field_mode",
    "actual_power_kw", "pilot_power_kw", "pilot_available",
    "gap_flag", "severe_gap_before",
]

# v1.2 §8: pre-existing vs train-quartile variables
PRE_EXISTING_VARS = {
    "n_active": {"edges": CONCURRENCY_BUCKETS, "labels": CONCURRENCY_LABELS,
                 "source": "pre_existing"},
    "elapsed": {"edges": ELAPSED_BUCKETS, "labels": ELAPSED_LABELS,
                "source": "pre_existing"},
}
TRAIN_QUARTILE_VARS = {
    "recent_actual_q90": {"obs_col": "median_recent_actual_q90",
                          "source": "train_quartile_ecdf"},
    "recent_var": {"obs_col": "median_recent_actual_var",
                   "source": "train_quartile_ecdf"},
    "lagged_pilot_actual_ratio": {
        "obs_col": "median_lagged_pilot_actual_ratio",
        "source": "train_quartile_ecdf"},
}
ALL_VARIABLES = list(PRE_EXISTING_VARS.keys()) + list(TRAIN_QUARTILE_VARS.keys())
INTERACTION = "n_active_x_elapsed"


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _git_prov(repo: Path) -> dict:
    try:
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        return {"code_sha": sha, "worktree_clean": not bool(status)}
    except Exception:
        return {"code_sha": "unknown", "worktree_clean": None}


def _load_candidates() -> dict[str, dict[str, pd.DataFrame]]:
    cands: dict[str, dict[str, pd.DataFrame]] = {}
    for pool in POOLS:
        cands[pool] = {}
        for split in SPLITS:
            if split == "test":
                p = E3_FORMAL / f"e3_full_test_{pool}_candidate.parquet"
            else:
                p = E3_PRETEST / f"e3_full_{split}_{pool}_candidate.parquet"
            if not p.exists():
                raise FileNotFoundError(f"候选表不存在 {p}")
            cands[pool][split] = pd.read_parquet(p)
    return cands


def _load_minutes(
    registry: pd.DataFrame,
) -> dict[str, dict[str, pd.DataFrame]]:
    mins: dict[str, dict[str, pd.DataFrame]] = {}
    for pool, site, role, fm in [
        ("caltech", "caltech", "main", None),
        ("jpl", "jpl", "current_only_fallback", "current_only"),
    ]:
        mins[pool] = {}
        for split in SPLITS:
            pred = (
                (ds.field("site") == site)
                & (ds.field("sample_layer") == "L1_strict_matched")
                & (ds.field("role") == role)
                & (ds.field("split") == split)
            )
            if fm:
                pred = pred & (ds.field("field_mode") == fm)
            df = ds.dataset(str(MINUTE_ROOT)).to_table(
                filter=pred, columns=MINUTE_COLS).to_pandas()
            mins[pool][split] = df
    return mins


def _load_e1_events() -> dict[str, pd.DataFrame]:
    evs: dict[str, pd.DataFrame] = {}
    for split in SPLITS:
        p = E1_DIR / f"e1_full_{split}_event_table.parquet"
        if p.exists():
            evs[split] = pd.read_parquet(p)
    return evs


def _cycle_observables(tm: pd.DataFrame) -> pd.DataFrame:
    """pool×cycle 级在线可观测量（复用 Batch_2.1 X3 冻结实现）。"""
    tm = tm.copy()
    tm["cycle"] = tm["timestamp_utc"].dt.floor("5min")
    tm["active"] = (tm["actual_power_kw"] >= 0.5).astype(float)
    tm["has_pilot"] = tm["pilot_power_kw"].notna().astype(float)
    tm = tm.sort_values(
        ["site", "session_id", "timestamp_utc"], kind="stable")
    sess_cycle = tm.groupby(
        ["site", "session_id", "cycle"], sort=False).agg(
        actual_mean=("actual_power_kw", "mean"),
        pilot_mean=("pilot_power_kw", "mean"),
        pilot_available_first=("has_pilot", "first"),
        elapsed_min=("connected_elapsed_min", "min"),
        severe_gap_at_start=("severe_gap_before", "first"),
        severe_gap_any=("severe_gap_before", "max"),
        n_active_min=("active", "sum"),
    ).reset_index()
    sess_cycle = sess_cycle.sort_values(["session_id", "cycle"])
    sess_cycle["_gap"] = sess_cycle["actual_mean"].isna()
    sess_cycle["_prev_cycle"] = sess_cycle.groupby(
        "session_id", sort=False)["cycle"].shift(1)
    sess_cycle["_cycle_gap"] = (
        sess_cycle["cycle"] - sess_cycle["_prev_cycle"]
    ).dt.total_seconds() / 60.0
    sess_cycle["_break"] = (
        sess_cycle["_gap"].fillna(True)
        | (sess_cycle["_cycle_gap"] > 5.0).fillna(True)
        | sess_cycle["severe_gap_at_start"].fillna(True)
    )
    sess_cycle["_run"] = sess_cycle.groupby(
        "session_id", sort=False)["_break"].cumsum()
    run_key = ["session_id", "_run"]
    sess_cycle["actual_lag1"] = sess_cycle.groupby(
        run_key, sort=False)["actual_mean"].shift(1)
    sess_cycle["actual_lag2"] = sess_cycle.groupby(
        run_key, sort=False)["actual_mean"].shift(2)
    sess_cycle["pilot_lag1"] = sess_cycle.groupby(
        run_key, sort=False)["pilot_mean"].shift(1)
    sess_cycle["recent_actual_q90"] = sess_cycle.groupby(
        run_key, sort=False)["actual_mean"].transform(
        lambda s: s.shift(1).rolling(12, min_periods=2).quantile(0.90))
    sess_cycle["recent_actual_var"] = sess_cycle.groupby(
        run_key, sort=False)["actual_mean"].transform(
        lambda s: s.shift(1).rolling(12, min_periods=2).var())
    sess_cycle["response_persistence_lagged"] = (
        sess_cycle["actual_lag1"] - sess_cycle["actual_lag2"]).abs()
    sess_cycle["lagged_pilot_actual_ratio"] = (
        sess_cycle["pilot_lag1"]
        / sess_cycle["actual_lag1"].clip(lower=1e-6))
    sess_cycle["severe_gap_lag1"] = sess_cycle.groupby(
        run_key, sort=False)["severe_gap_at_start"].shift(1)
    sess_cycle["history_supported"] = sess_cycle[
        "recent_actual_q90"].notna()
    obs = sess_cycle.groupby(["site", "cycle"]).agg(
        n_active_sessions=(
            "session_id",
            lambda s: sess_cycle.loc[
                s.index, "n_active_min"].gt(0).sum()),
        n_connected=("session_id", "nunique"),
        median_elapsed=("elapsed_min", "median"),
        median_actual_kw=("actual_mean", "median"),
        std_actual_kw=("actual_mean", "std"),
        pilot_available_at_start=("pilot_available_first", "mean"),
        median_pilot_kw=("pilot_mean", "median"),
        median_recent_actual_q90=("recent_actual_q90", "median"),
        median_recent_actual_var=("recent_actual_var", "median"),
        median_response_persistence_lagged=(
            "response_persistence_lagged", "median"),
        median_lagged_pilot_actual_ratio=(
            "lagged_pilot_actual_ratio", "median"),
        lagged_severe_gap_rate=("severe_gap_lag1", "mean"),
        history_coverage=("history_supported", "mean"),
    ).reset_index()
    return obs


def _fit_quartile_edges(
    train_obs: pd.DataFrame, pool: str
) -> dict[str, dict[str, Any]]:
    """v1.2 §8: pool×variable train-only ECDF quartile edges。

    Q1=(-inf,q25] / Q2=(q25,q50] / Q3=(q50,q75] / Q4=(q75,+inf)。
    Duplicate edge → merge；不足 2 非空区间 → insufficient_bin_resolution。
    """
    edges_result: dict[str, dict[str, Any]] = {}
    for var, info in TRAIN_QUARTILE_VARS.items():
        col = info["obs_col"]
        if col not in train_obs.columns:
            edges_result[var] = {
                "edges": None, "labels": None,
                "insufficient_bin_resolution": True,
                "reason": "column_not_in_observable_table",
            }
            continue
        series = train_obs[col].dropna()
        if pool == "jpl" and "pilot" in col:
            edges_result[var] = {
                "edges": None, "labels": None,
                "insufficient_bin_resolution": True,
                "reason": "no_pilot_in_current_only_domain",
            }
            continue
        if len(series) < 4:
            edges_result[var] = {
                "edges": None, "labels": None,
                "insufficient_bin_resolution": True,
                "reason": "insufficient_train_samples",
            }
            continue
        q25 = float(series.quantile(0.25))
        q50 = float(series.quantile(0.50))
        q75 = float(series.quantile(0.75))
        # v1.2: Q1=(-inf,q25] / Q2=(q25,q50] / Q3=(q50,q75] / Q4=(q75,+inf)
        raw_edges = [q25, q50, q75]
        # duplicate-edge merge
        merged: list[float] = []
        for e in raw_edges:
            if merged and abs(e - merged[-1]) < 1e-12:
                continue
            merged.append(e)
        if len(merged) < 1:
            edges_result[var] = {
                "edges": None, "labels": None,
                "insufficient_bin_resolution": True,
                "reason": "all_quantiles_equal",
            }
            continue
        labels = [f"Q{i+1}" for i in range(len(merged) + 1)]
        edges_result[var] = {
            "edges": [-np.inf] + merged + [np.inf],
            "labels": labels,
            "insufficient_bin_resolution": False,
            "q25": q25, "q50": q50, "q75": q75,
            "n_train_nonnull": int(len(series)),
        }
    return edges_result


def _apply_bucket(
    merged: pd.DataFrame, var: str, edges: list, labels: list
) -> pd.Series:
    """Apply pre-fitted edges to any split（val/test 只 apply，不重拟合）。"""
    obs_col = TRAIN_QUARTILE_VARS.get(var, {}).get("obs_col", var)
    if obs_col not in merged.columns:
        return pd.Series(["NA"] * len(merged), index=merged.index)
    return pd.cut(
        merged[obs_col], bins=edges, labels=labels,
        right=True, include_lowest=True).astype(str)


def _daily_share_bucket(
    merged_bucket: pd.DataFrame, tm: pd.DataFrame
) -> float | None:
    """v1.2 §9b: bucket-restricted E3/K1 exact evaluable-day daily share。

    分母 = 该 bucket valid paired cycles 对应 EV energy（非全站）。
    """
    if len(merged_bucket) == 0:
        return None
    cand_day = merged_bucket.groupby("day")[
        "candidate_energy_A2_prev_actual_kwh"].sum()
    ev = tm.copy()
    ev["day"] = ev["timestamp_utc"].astype(str).str[:10]
    # 只取该 bucket 的 sessions 的 EV energy（bucket restriction）
    bucket_sessions = set(merged_bucket["session_id"]) \
        if "session_id" in merged_bucket.columns else None
    if bucket_sessions:
        ev = ev[ev["session_id"].isin(bucket_sessions)]
    ev_day = ev.groupby("day")["actual_power_kw"].sum() / 60.0
    ev_on_eval = ev_day.reindex(cand_day.index).clip(lower=1e-6)
    share = cand_day.div(ev_on_eval)
    return round(float(share.median()), 6) if len(share) else None


def _compute_bucket_row(
    layer: str, pool: str, split: str, field_mode: str,
    variable: str, bucket: str, bucket_rule: str,
    merged_bucket: pd.DataFrame, tm: pd.DataFrame,
    s1_cycles: set, all_e3_valid: pd.DataFrame,
) -> dict[str, Any]:
    """计算单个 bucket row 的全部 19 列。"""
    n_eval = int(len(merged_bucket))
    # E1 events in this bucket
    if layer == "evidence" and s1_cycles:
        n_e1 = int(merged_bucket.apply(
            lambda r: (r["site"], r["cycle"]) in s1_cycles, axis=1).sum())
    else:
        n_e1 = 0
    e1_rate = round(n_e1 / max(n_eval, 1), 6) if n_eval else None

    n_valid = n_eval
    n_cand = int(merged_bucket["candidate_A2_prev_actual"].sum()) \
        if "candidate_A2_prev_actual" in merged_bucket.columns and n_eval \
        else 0
    cand_rate = round(n_cand / max(n_valid, 1), 6) if n_valid else None

    # daily share
    daily = _daily_share_bucket(merged_bucket, tm) if n_eval else None

    # elimination
    a2_elim = None
    a3_elim = None
    na_reason = ""
    if "candidate_A0_avg" in merged_bucket.columns and n_eval:
        rate_a0 = float(merged_bucket["candidate_A0_avg"].mean())
        rate_a2 = float(merged_bucket["candidate_A2_prev_actual"].mean())
        rate_a3 = float(
            merged_bucket["candidate_A3_rolling_quantile"].mean()) \
            if "candidate_A3_rolling_quantile" in merged_bucket.columns \
            else 0.0
        if rate_a0 == 0:
            a2_elim = None
            a3_elim = None
            na_reason = "a0_zero_not_evaluable"
        else:
            a2_elim = round(1 - rate_a2 / rate_a0, 6)
            a3_elim = round(1 - rate_a3 / rate_a0, 6)
    elif pool == "jpl":
        na_reason = "a0_unavailable_current_only"

    # direction vs pooled reference
    pooled_rate = float(all_e3_valid["candidate_A2_prev_actual"].mean()) \
        if "candidate_A2_prev_actual" in all_e3_valid.columns \
        and len(all_e3_valid) else None
    direction = "NA"
    if cand_rate is not None and pooled_rate is not None:
        if cand_rate > pooled_rate:
            direction = "bucket>pooled"
        elif cand_rate < pooled_rate:
            direction = "bucket<pooled"
        else:
            direction = "equal"

    interp = "hypothesis" if n_eval >= 5 else "insufficient"

    return {
        "layer": layer,
        "pool": pool,
        "split": split,
        "field_mode": field_mode,
        "variable": variable,
        "bucket": bucket,
        "bucket_rule_source": bucket_rule,
        "n_evaluable": n_eval,
        "n_e1_events": n_e1,
        "e1_evidence_rate": e1_rate,
        "n_e3_valid_cycles": n_valid,
        "n_e3_candidates": n_cand,
        "e3_candidate_rate": cand_rate,
        "daily_candidate_energy_share": daily,
        "a2_elimination": a2_elim,
        "a3_elimination": a3_elim,
        "direction_vs_reference": direction,
        "interpretation_scope": interp,
        "na_reason": na_reason,
    }


def run_a5(
    cands: dict[str, dict[str, pd.DataFrame]],
    minutes: dict[str, dict[str, pd.DataFrame]],
    e1_events: dict[str, pd.DataFrame],
) -> dict:
    """A5: support/opportunity hypothesis audit（v1.2 protocol）。"""
    all_rows: list[dict[str, Any]] = []
    all_edges: dict[str, dict[str, Any]] = {}

    for pool in POOLS:
        field_mode = "measured_pilot" if pool == "caltech" else "current_only"
        # ---- fit ECDF edges on train only ----
        train_cand = cands[pool]["train"]
        train_tm = minutes[pool]["train"]
        train_obs = _cycle_observables(train_tm)
        train_cand.merge(
            train_obs, on=["site", "cycle"], how="left",
            suffixes=("", "_obs"))
        edges = _fit_quartile_edges(train_obs, pool)
        all_edges[pool] = edges

        for split in SPLITS:
            cand = cands[pool][split]
            tm = minutes[pool][split]
            if len(cand) == 0:
                continue
            obs = _cycle_observables(tm)
            merged = cand.merge(
                obs, on=["site", "cycle"], how="left",
                suffixes=("", "_obs"))
            merged["day"] = merged["cycle"].astype(str).str[:10]

            # S1 cycles
            s1_cycles: set[tuple[str, pd.Timestamp]] = set()
            if pool == "caltech" and split in e1_events:
                e1 = e1_events[split]
                core = e1[e1["event_phase"] == "core_run_segment"]
                for _, ev in core.iterrows():
                    c_start = pd.to_datetime(
                        ev["start_utc"]).floor("5min")
                    s1_cycles.add((ev["site"], c_start))

            # ---- pre-existing buckets ----
            for var, info in PRE_EXISTING_VARS.items():
                if var == "n_active":
                    merged["bucket_col"] = pd.cut(
                        merged["n_active"], bins=info["edges"],
                        labels=info["labels"], right=False,
                        include_lowest=True).astype(str)
                elif var == "elapsed":
                    merged["bucket_col"] = pd.cut(
                        merged["median_elapsed"], bins=info["edges"],
                        labels=info["labels"], right=False,
                        include_lowest=True).astype(str)
                layer = "opportunity"
                for bucket in info["labels"]:
                    sub = merged[merged["bucket_col"] == bucket]
                    row = _compute_bucket_row(
                        layer, pool, split, field_mode, var, bucket,
                        info["source"], sub, tm, s1_cycles, merged)
                    all_rows.append(row)

            # ---- train-quartile buckets ----
            for var, info in TRAIN_QUARTILE_VARS.items():
                edge_info = edges.get(var, {})
                if edge_info.get("insufficient_bin_resolution"):
                    row = _compute_bucket_row(
                        "evidence" if "pilot" in var else "opportunity",
                        pool, split, field_mode, var, "NA",
                        info["source"], pd.DataFrame(), tm,
                        s1_cycles, merged)
                    row["na_reason"] = edge_info.get(
                        "reason", "insufficient_bin_resolution")
                    row["interpretation_scope"] = "insufficient"
                    all_rows.append(row)
                    continue
                layer = "evidence" if "pilot" in var or "var" in var \
                    else "opportunity"
                merged["bucket_col"] = _apply_bucket(
                    merged, var, edge_info["edges"], edge_info["labels"])
                for bucket in edge_info["labels"]:
                    sub = merged[merged["bucket_col"] == bucket]
                    row = _compute_bucket_row(
                        layer, pool, split, field_mode, var, bucket,
                        info["source"], sub, tm, s1_cycles, merged)
                    all_rows.append(row)

            # ---- interaction n_active × elapsed ----
            merged["n_active_bucket"] = pd.cut(
                merged["n_active"], bins=CONCURRENCY_BUCKETS,
                labels=CONCURRENCY_LABELS, right=False,
                include_lowest=True).astype(str)
            merged["elapsed_bucket"] = pd.cut(
                merged["median_elapsed"], bins=ELAPSED_BUCKETS,
                labels=ELAPSED_LABELS, right=False,
                include_lowest=True).astype(str)
            for na_b in CONCURRENCY_LABELS:
                for el_b in ELAPSED_LABELS:
                    sub = merged[
                        (merged["n_active_bucket"] == na_b)
                        & (merged["elapsed_bucket"] == el_b)]
                    if len(sub) == 0:
                        continue
                    bucket_label = f"{na_b}|{el_b}"
                    row = _compute_bucket_row(
                        "opportunity", pool, split, field_mode,
                        INTERACTION, bucket_label, "pre_existing_cross",
                        sub, tm, s1_cycles, merged)
                    all_rows.append(row)

    # ---- output ----
    result_df = pd.DataFrame(all_rows)
    # v1.2 §9: 19 columns
    expected_cols = [
        "layer", "pool", "split", "field_mode", "variable", "bucket",
        "bucket_rule_source", "n_evaluable", "n_e1_events",
        "e1_evidence_rate", "n_e3_valid_cycles", "n_e3_candidates",
        "e3_candidate_rate", "daily_candidate_energy_share",
        "a2_elimination", "a3_elimination", "direction_vs_reference",
        "interpretation_scope", "na_reason",
    ]
    assert list(result_df.columns) == expected_cols or set(
        result_df.columns) == set(expected_cols), (
        f"schema mismatch: {list(result_df.columns)}")
    result_df = result_df[expected_cols]
    result_df.to_csv(OUT / "a5_support_domain_hypothesis.csv", index=False)

    a5_summary = {
        "module": "A5_support_domain_hypothesis",
        "protocol_version": "v1.2 FINAL FREEZE",
        "protocol_sha256": _sha256_file(PROTOCOL),
        "ecdf_edges": all_edges,
        "n_rows": int(len(result_df)),
        "variables": ALL_VARIABLES + [INTERACTION],
        "note": (
            "五单变量 + n_active×elapsed 交互；train-only ECDF quartile；"
            "19-column schema；daily-share bucket-restricted E3/K1 exact；"
            "elimination A0=0→NA；E1 event-start snapshot；"
            "direction=pooled reference；test 只产假设"),
    }
    (OUT / "a5_summary.json").write_text(
        json.dumps(a5_summary, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return a5_summary


def run_a5_generator() -> dict:
    prov = _git_prov(REPO)
    registry = pd.read_parquet(REG)
    cands = _load_candidates()
    minutes = _load_minutes(registry)
    e1_events = _load_e1_events()

    a5 = run_a5(cands, minutes, e1_events)

    outputs: dict[str, Any] = {}
    for p in sorted(OUT.glob("a5_*.csv")):
        outputs[str(p.relative_to(IMPL))] = {
            "sha256": _sha256_file(p),
            "rows": int(len(pd.read_csv(p)))}
    for p in sorted(OUT.glob("a5_*.json")):
        if p.name == "a5_manifest.json":
            continue
        outputs[str(p.relative_to(IMPL))] = {"sha256": _sha256_file(p)}

    input_provs: dict[str, Any] = {}
    for pool in POOLS:
        for split in SPLITS:
            if split == "test":
                p = E3_FORMAL / f"e3_full_test_{pool}_candidate.parquet"
            else:
                p = E3_PRETEST / f"e3_full_{split}_{pool}_candidate.parquet"
            input_provs[f"e3_{pool}_{split}_candidate"] = {
                "sha256": _sha256_file(p),
                "rows": int(len(pd.read_parquet(p)))}
    for split in SPLITS:
        p = E1_DIR / f"e1_full_{split}_event_table.parquet"
        if p.exists():
            input_provs[f"e1_{split}_events"] = {
                "sha256": _sha256_file(p),
                "rows": int(len(pd.read_parquet(p)))}

    manifest = {
        "batch": "a5",
        "preregister": str(PREREG.relative_to(IMPL)),
        "preregister_sha256": _sha256_file(PREREG),
        "protocol": str(PROTOCOL.relative_to(IMPL)),
        "protocol_sha256": _sha256_file(PROTOCOL),
        "protocol_version": "v1.2 FINAL FREEZE",
        "analysis_code_sha": prov["code_sha"],
        "worktree_clean": prov["worktree_clean"],
        "inputs": {
            "split_registry": {
                "sha256": _sha256_file(REG),
                "rows": int(len(registry))},
            **input_provs,
        },
        "ecdf_edges": a5["ecdf_edges"],
        "outputs": outputs,
        "a5_summary": a5,
        "discipline": (
            "只读 frozen evidence + registry + minute table；"
            "不重跑 formal；不调参；deterministic；"
            "protocol v1.2 FINAL FREEZE"),
    }
    (OUT / "a5_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps({
        "batch": "a5",
        "n_rows": a5["n_rows"],
        "ecdf_edges_pools": list(a5["ecdf_edges"].keys()),
        "manifest_written": True,
    }, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    run_a5_generator()
