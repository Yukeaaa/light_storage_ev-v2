"""R1 最终收敛审计 A5 确定性生成器（审查结论47；protocol v1.2 FINAL FREEZE；X2=审查结论48）。

严格实现 R1_A5_protocol_amendment.md v1.2：
- 五单变量 fixed buckets（n_active/elapsed pre-existing；recent_actual_q90/
  recent_var/lagged_pilot_actual_ratio train-only ECDF quartile）
- 唯一交互 n_active × elapsed
- 19-column output schema + na_reason
- daily-share bucket-restricted E3/K1 exact evaluable-day
- elimination 1 - rate/rate_A0（A0=0→NA）
- E1 event-start cycle snapshot
- direction_vs_reference = pooled population fixed reference

审查结论48 X2（code-only，未运行）：
- P0-1 ECDF fit universe = frozen E3 valid-cycle keys × online-observable
  nonnull（inner join），assert 子集 + manifest 记 fit provenance
- P0-2 daily-share denominator = 该 bucket valid cycles 的 EV energy
  （cycle 层 restriction，非 session 过滤/全站）
- P0-3 E1 observable universe 与 E3 valid universe 分离（n_evaluable/n_e1_events
  vs n_e3_valid_cycles/n_e3_candidates，同 bucket rule）
- P0-3a 所有变量 + interaction 一律真实计算 E1 event-start stats（layer 不决定）
- P0-4 Layer 2 direction 用 E1 evidence rate，Layer 1 用 E3 candidate rate；
  未 round 原值比较，输出再 round
- P0-5 JPL E1 unavailable → NA + metric_not_applicable（非假 0）
- P0-6 duplicate-edge insufficient 用 cut 后实际 non-empty bins（n_nonempty>=2）
- P1-1 lagged_pilot_actual_ratio → interpretation_scope=diagnostic
- P1-2 manifest 补 ecdf_fit_provenance + minute tables rows/sessions

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


def _ev_cycle_energy(tm: pd.DataFrame) -> pd.DataFrame:
    """pool×cycle 级 EV energy（kWh），供 daily-share bucket 层 restriction。"""
    ev = tm[["site", "timestamp_utc", "actual_power_kw"]].copy()
    ev["cycle"] = ev["timestamp_utc"].dt.floor("5min")
    ev["day"] = ev["timestamp_utc"].astype(str).str[:10]
    out = ev.groupby(["site", "cycle", "day"], sort=False)[
        "actual_power_kw"].sum().div(60).reset_index()
    return out.rename(columns={"actual_power_kw": "kwh"})


def _fit_quartile_edges(
    fit_obs: pd.DataFrame, pool: str
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """v1.2 §8 + 审查结论48 P0-1/P0-6: pool×variable train-only ECDF quartile。

    fit universe = frozen E3 valid-cycle keys × online-observable nonnull。
    Q1=(-inf,q25] / Q2=(q25,q50] / Q3=(q50,q75] / Q4=(q75,+inf)。
    Duplicate edge → merge；cut 后实际 non-empty bins <2 →
    insufficient_bin_resolution（不 jitter、不人为找新 cutpoint）。
    返回 (edges_result, prov)；prov 供 manifest 记录 fit provenance。
    """
    edges_result: dict[str, dict[str, Any]] = {}
    prov: dict[str, dict[str, Any]] = {}
    for var, info in TRAIN_QUARTILE_VARS.items():
        col = info["obs_col"]
        vp: dict[str, Any] = {
            "n_nonnull": 0, "q25": None, "q50": None, "q75": None,
            "edges": None, "labels": None, "effective_bins": 0,
            "insufficient_bin_resolution": True, "reason": ""}
        if col not in fit_obs.columns:
            vp["reason"] = "column_not_in_observable_table"
            edges_result[var] = dict(vp)
            prov[var] = vp
            continue
        series = fit_obs[col].dropna()
        vp["n_nonnull"] = int(len(series))
        if pool == "jpl" and "pilot" in col:
            vp["reason"] = "no_pilot_in_current_only_domain"
            edges_result[var] = dict(vp)
            prov[var] = vp
            continue
        if len(series) < 4:
            vp["reason"] = "insufficient_train_samples"
            edges_result[var] = dict(vp)
            prov[var] = vp
            continue
        q25 = float(series.quantile(0.25))
        q50 = float(series.quantile(0.50))
        q75 = float(series.quantile(0.75))
        vp.update(q25=q25, q50=q50, q75=q75)
        merged: list[float] = []
        for e in [q25, q50, q75]:
            if merged and abs(e - merged[-1]) < 1e-12:
                continue
            merged.append(e)
        edges = [-np.inf] + merged + [np.inf]
        labels = [f"Q{i+1}" for i in range(len(merged) + 1)]
        # P0-6: 用实际 non-empty bins 判定，不只数 edge 数量
        cuts = pd.cut(
            series, bins=edges, labels=labels,
            right=True, include_lowest=True).dropna()
        n_nonempty = int(cuts.nunique())
        vp.update(edges=edges, labels=labels, effective_bins=n_nonempty)
        if n_nonempty < 2:
            vp["reason"] = "duplicate_edge_insufficient_bins"
            edges_result[var] = dict(vp)
            prov[var] = vp
            continue
        vp["insufficient_bin_resolution"] = False
        vp["reason"] = ""
        edges_result[var] = {
            "edges": edges, "labels": labels,
            "insufficient_bin_resolution": False,
            "q25": q25, "q50": q50, "q75": q75,
            "n_train_nonnull": int(len(series)),
            "effective_bins": n_nonempty,
        }
        prov[var] = vp
    return edges_result, prov


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
    merged_bucket: pd.DataFrame, ev_cycle_energy: pd.DataFrame
) -> float | None:
    """v1.2 §9b + 审查结论48 P0-2: bucket-restricted E3/K1 exact daily share。

    分母 = 该 bucket valid cycles 对应 EV energy（cycle 层 inner-join
    restriction，非 session 过滤、非全站）。
    """
    if len(merged_bucket) == 0:
        return None
    cand_day = merged_bucket.groupby(
        "day")["candidate_energy_A2_prev_actual_kwh"].sum()
    if len(cand_day) == 0:
        return None
    keys = merged_bucket[["site", "cycle"]].drop_duplicates()
    ev_res = ev_cycle_energy.merge(keys, on=["site", "cycle"], how="inner")
    ev_day = ev_res.groupby("day")["kwh"].sum()
    ev_on_eval = ev_day.reindex(cand_day.index).clip(lower=1e-6)
    share = cand_day.div(ev_on_eval)
    return float(share.median()) if len(share) else None


def _dir_label(diff: float) -> str:
    if abs(diff) < 1e-12:
        return "equal"
    return "bucket>pooled" if diff > 0 else "bucket<pooled"


def _layer_for_var(var: str) -> str:
    return "evidence" if ("pilot" in var or "var" in var) else "opportunity"


def _interpretation_scope(
    variable: str, layer: str, n_valid: int, n_evaluable: int
) -> str:
    # P1-1: lagged_pilot_actual_ratio 只到 diagnostic，不因 n>=5 升级 hypothesis
    if variable == "lagged_pilot_actual_ratio":
        return "diagnostic" if n_evaluable >= 5 else "insufficient"
    if layer == "evidence":
        return "hypothesis" if n_evaluable >= 5 else "insufficient"
    return "hypothesis" if n_valid >= 5 else "insufficient"


def _compute_bucket_row(
    layer: str, pool: str, split: str, field_mode: str,
    variable: str, bucket: str, bucket_rule: str,
    merged_bucket: pd.DataFrame, ev_cycle_energy: pd.DataFrame,
    s1_cycles: set, pooled_e3_rate_raw: float | None,
    pooled_e1_rate_raw: float | None, e1_applicable: bool,
) -> dict[str, Any]:
    """计算单个 bucket row 的全部 19 列（P0-3/P0-3a/P0-4/P0-5）。"""
    n_valid = int(len(merged_bucket))
    n_cand = 0
    if n_valid and "candidate_A2_prev_actual" in merged_bucket.columns:
        n_cand = int(merged_bucket["candidate_A2_prev_actual"].sum())

    # ---- P0-3: E1 observable universe（与 E3 valid universe 分离）----
    if n_valid and "is_observable" in merged_bucket.columns:
        sub_obs = merged_bucket[merged_bucket["is_observable"]]
    else:
        sub_obs = merged_bucket.iloc[0:0]
    n_evaluable = int(len(sub_obs))
    n_e1: int | None = None
    e1_rate_raw: float | None = None
    if e1_applicable and n_evaluable:
        keys = set(zip(
            sub_obs["site"], sub_obs["cycle"], strict=False))
        n_e1 = int(sum(1 for k in keys if k in s1_cycles))
        e1_rate_raw = n_e1 / n_evaluable
    elif e1_applicable:
        n_e1 = 0

    cand_rate_raw = (n_cand / n_valid) if n_valid else None
    e1_rate = round(e1_rate_raw, 6) if e1_rate_raw is not None else None
    cand_rate = round(cand_rate_raw, 6) if cand_rate_raw is not None else None

    # P0-2: daily share（分母 = 该 bucket valid cycles EV energy）
    daily = _daily_share_bucket(merged_bucket, ev_cycle_energy)

    # elimination（protocol §9b；A0=0→NA+a0_zero_not_evaluable）
    a2_elim_raw: float | None = None
    a3_elim_raw: float | None = None
    na_reasons: list[str] = []
    if "candidate_A0_avg" in merged_bucket.columns and n_valid:
        rate_a0 = float(merged_bucket["candidate_A0_avg"].mean())
        rate_a2 = float(merged_bucket["candidate_A2_prev_actual"].mean())
        rate_a3 = float(
            merged_bucket["candidate_A3_rolling_quantile"].mean()) \
            if "candidate_A3_rolling_quantile" in merged_bucket.columns \
            else 0.0
        if rate_a0 == 0:
            na_reasons.append("a0_zero_not_evaluable")
        else:
            a2_elim_raw = 1 - rate_a2 / rate_a0
            a3_elim_raw = 1 - rate_a3 / rate_a0
    if pool == "jpl":
        na_reasons.append("a0_unavailable_current_only")
    # P0-5: JPL E1 unavailable → NA + metric_not_applicable（非假 0）
    if not e1_applicable:
        na_reasons.append("metric_not_applicable")

    # P0-4: layer-aware direction reference；未 round 原值比较
    direction = "NA"
    if layer == "evidence":
        if e1_rate_raw is not None and pooled_e1_rate_raw is not None:
            direction = _dir_label(e1_rate_raw - pooled_e1_rate_raw)
    else:
        if cand_rate_raw is not None and pooled_e3_rate_raw is not None:
            direction = _dir_label(cand_rate_raw - pooled_e3_rate_raw)

    return {
        "layer": layer,
        "pool": pool,
        "split": split,
        "field_mode": field_mode,
        "variable": variable,
        "bucket": bucket,
        "bucket_rule_source": bucket_rule,
        "n_evaluable": n_evaluable,
        "n_e1_events": n_e1,
        "e1_evidence_rate": e1_rate,
        "n_e3_valid_cycles": n_valid,
        "n_e3_candidates": n_cand,
        "e3_candidate_rate": cand_rate,
        "daily_candidate_energy_share": round(daily, 6)
        if daily is not None else None,
        "a2_elimination": round(a2_elim_raw, 6)
        if a2_elim_raw is not None else None,
        "a3_elimination": round(a3_elim_raw, 6)
        if a3_elim_raw is not None else None,
        "direction_vs_reference": direction,
        "interpretation_scope": _interpretation_scope(
            variable, layer, n_valid, n_evaluable),
        "na_reason": ";".join(na_reasons),
    }


def run_a5(
    cands: dict[str, dict[str, pd.DataFrame]],
    minutes: dict[str, dict[str, pd.DataFrame]],
    e1_events: dict[str, pd.DataFrame],
) -> dict:
    """A5: support/opportunity hypothesis audit（v1.2 protocol，X2=Review 48）。"""
    all_rows: list[dict[str, Any]] = []
    all_edges: dict[str, dict[str, Any]] = {}
    fit_prov: dict[str, dict[str, Any]] = {}

    for pool in POOLS:
        field_mode = "measured_pilot" if pool == "caltech" else "current_only"
        # ---- P0-1: ECDF fit on frozen E3 valid-cycle keys × obs（train only）----
        train_cand = cands[pool]["train"]
        train_tm = minutes[pool]["train"]
        train_obs = _cycle_observables(train_tm)
        fit_keys = train_cand[["site", "cycle"]].drop_duplicates()
        fit_obs = fit_keys.merge(
            train_obs, on=["site", "cycle"], how="inner")
        train_obs_keys = set(zip(
            train_obs["site"], train_obs["cycle"], strict=False))
        fit_key_set = set(zip(
            fit_keys["site"], fit_keys["cycle"], strict=False))
        fit_obs_keys = set(zip(
            fit_obs["site"], fit_obs["cycle"], strict=False))
        assert fit_obs_keys <= train_obs_keys, \
            f"{pool}: fit universe 超出 observable table"
        assert fit_obs_keys <= fit_key_set, \
            f"{pool}: fit universe 超出 E3 valid keys"
        assert len(fit_obs) > 0, f"{pool}: ECDF fit universe 为空"
        edges, prov = _fit_quartile_edges(fit_obs, pool)
        all_edges[pool] = edges
        fit_prov[pool] = {
            "fit_split": "train",
            "fit_universe": "e3_valid_paired_cycle_x_online_observable_nonnull",
            "n_valid_cycles": int(len(fit_keys)),
            "n_mapped_obs": int(len(fit_obs)),
            "n_cycles_missing_obs": int(len(fit_keys) - len(fit_obs)),
            "variables": prov,
        }

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
            merged["is_observable"] = merged["n_active_sessions"].notna()

            # S1: E1 core event-start cycle snapshot（仅 caltech 有 E1）
            s1_cycles: set[tuple[str, pd.Timestamp]] = set()
            e1_applicable = pool == "caltech"
            if e1_applicable and split in e1_events:
                e1 = e1_events[split]
                core = e1[e1["event_phase"] == "core_run_segment"]
                for _, ev in core.iterrows():
                    c_start = pd.to_datetime(
                        ev["start_utc"]).floor("5min")
                    s1_cycles.add((ev["site"], c_start))

            # pooled reference = 同 pool×split 全部 evaluable population
            pooled_e3_rate_raw = float(
                merged["candidate_A2_prev_actual"].mean()) \
                if len(merged) else None
            pooled_e1_rate_raw = None
            if e1_applicable:
                obs_sub = merged[merged["is_observable"]]
                n_obs = int(len(obs_sub))
                if n_obs:
                    keys = set(zip(
                        obs_sub["site"], obs_sub["cycle"], strict=False))
                    n_e1_total = int(
                        sum(1 for k in keys if k in s1_cycles))
                    pooled_e1_rate_raw = n_e1_total / n_obs

            ev_cycle_energy = _ev_cycle_energy(tm)

            # ---- pre-existing buckets ----
            for var, info in PRE_EXISTING_VARS.items():
                layer = _layer_for_var(var)
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
                for bucket in info["labels"]:
                    sub = merged[merged["bucket_col"] == bucket]
                    row = _compute_bucket_row(
                        layer, pool, split, field_mode, var, bucket,
                        info["source"], sub, ev_cycle_energy, s1_cycles,
                        pooled_e3_rate_raw, pooled_e1_rate_raw,
                        e1_applicable)
                    all_rows.append(row)

            # ---- train-quartile buckets ----
            for var, info in TRAIN_QUARTILE_VARS.items():
                layer = _layer_for_var(var)
                edge_info = edges.get(var, {})
                if edge_info.get("insufficient_bin_resolution"):
                    row = _compute_bucket_row(
                        layer, pool, split, field_mode, var, "NA",
                        info["source"], pd.DataFrame(), ev_cycle_energy,
                        s1_cycles, pooled_e3_rate_raw, pooled_e1_rate_raw,
                        e1_applicable)
                    base = row["na_reason"]
                    reason = edge_info.get(
                        "reason", "insufficient_bin_resolution")
                    row["na_reason"] = f"{base};{reason}" if base else reason
                    row["interpretation_scope"] = "insufficient"
                    all_rows.append(row)
                    continue
                merged["bucket_col"] = _apply_bucket(
                    merged, var, edge_info["edges"], edge_info["labels"])
                for bucket in edge_info["labels"]:
                    sub = merged[merged["bucket_col"] == bucket]
                    row = _compute_bucket_row(
                        layer, pool, split, field_mode, var, bucket,
                        info["source"], sub, ev_cycle_energy, s1_cycles,
                        pooled_e3_rate_raw, pooled_e1_rate_raw,
                        e1_applicable)
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
                        sub, ev_cycle_energy, s1_cycles,
                        pooled_e3_rate_raw, pooled_e1_rate_raw,
                        e1_applicable)
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
        "ecdf_fit_provenance": fit_prov,
        "n_rows": int(len(result_df)),
        "variables": ALL_VARIABLES + [INTERACTION],
        "x2_review_48": (
            "P0-1 ECDF fit universe=frozen E3 valid-cycle keys×obs inner join; "
            "P0-2 daily-share denominator=bucket valid cycles EV energy (cycle-level); "
            "P0-3 E1 observable universe separated from E3 valid universe; "
            "P0-3a E1 event-start stats for all variables+interaction; "
            "P0-4 layer-aware direction (Layer2=e1 rate, Layer1=e3 rate), raw compare; "
            "P0-5 JPL E1 unavailable→NA+metric_not_applicable; "
            "P0-6 insufficient by cut actual non-empty bins; "
            "P1-1 lagged_pilot_actual_ratio→diagnostic; "
            "P1-2 manifest ecdf_fit_provenance+minute tables"),
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

    # P1-2: minute table provenance（rows/sessions per pool/split）
    minute_prov: dict[str, dict[str, Any]] = {}
    for pool in POOLS:
        minute_prov[pool] = {}
        for split in SPLITS:
            tm = minutes[pool][split]
            minute_prov[pool][split] = {
                "rows": int(len(tm)),
                "sessions": int(tm["session_id"].nunique())
                if len(tm) else 0,
            }

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
        "minute_tables": minute_prov,
        "ecdf_edges": a5["ecdf_edges"],
        "ecdf_fit_provenance": a5["ecdf_fit_provenance"],
        "outputs": outputs,
        "a5_summary": a5,
        "discipline": (
            "只读 frozen evidence + registry + minute table；"
            "不重跑 formal；不调参；deterministic；"
            "protocol v1.2 FINAL FREEZE；X2=审查结论48 code-only"),
    }
    (OUT / "a5_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps({
        "batch": "a5",
        "x2": "review 48 code-only",
        "n_rows": a5["n_rows"],
        "ecdf_edges_pools": list(a5["ecdf_edges"].keys()),
        "manifest_written": True,
    }, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    run_a5_generator()
