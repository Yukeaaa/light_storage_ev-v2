"""R1 最终收敛审计 Batch_2.1 确定性生成器（审查结论38/39；A3+A4 修正，不重跑 formal）。

A3 修正（审查结论38）：
- A0=0 month elimination → NA + evaluable flag（不用 epsilon denominator）
- 补 daily_candidate_energy_share（E3/K1 exact evaluable-day 口径）
- fidelity assertion：recomputed split-level daily-share ≈ frozen E3 六值
- 输出 n_months_evaluable / n_months_A2/A3_elim_gt_80 + 对应月份
- a3_baseline_pressure.csv exact aggregate output

A4 修正（审查结论38/39）：
- P0: concurrency 用 frozen candidate table n_active（EV nunique），不从 minute-row sum 构造
  n_active 不假设 0-3（train median=7, JPL median=17, test 才降至 ~2）
- NaN/None/equal/missing → consistent=False（VALID_DIRECTIONS = {true>false, true<false}）
- S1/S2/S3 非互斥（独立 boolean 列：is_e1_core / is_e3_valid / is_e3_candidate_A2）
- E1→5min cycle 映射覆盖率输出（event-start cycle snapshot，不展开 duration）
- lagged observables: 先聚合到 5min cycle，再 session×run 组内 shift(1)+rolling（不跨 run/gap）
- observable 三类：definitional / baseline_related_history / independent_operational
  definitional（median_actual_kw）不单独进 A5
- gap_flag 不用（可能含当前周期信息）；用 severe_gap_before（pre-action 可知）
- pilot_actual_ratio → lagged（lagged_pilot_actual_ratio）
- 同 bucket 对照 + n_true/n_false 最小样本记录
- test_not_reversed 标志（train+val consistent vs test direction，分开报告）
- A5_ENTRY 准入门冻结（非 definitional + pre-action + train稳定 + val同向 + test不反向 + 样本充足）

只读 frozen evidence + registry + minute table；不调用 formal runner；
不重算事件/candidate 定义；只 groupby/join/slice；deterministic rerun。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

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
OUT = IMPL / "results" / "raw" / "E3F_expansion"
OUT.mkdir(parents=True, exist_ok=True)

SPLITS = ("train", "validation", "test")
POOLS = ("caltech", "jpl")
CONCURRENCY_BUCKETS = [0, 2, 4, 8, 16, 1000]
CONCURRENCY_LABELS = ["1", "2-3", "4-7", "8-15", "16+"]
VALID_DIRECTIONS = {"true>false", "true<false"}

# frozen E3 daily-share truth（fidelity assertion，审查结论39）
FROZEN_DAILY_SHARE = {
    ("caltech", "train"): 0.041346,
    ("caltech", "validation"): 0.037781,
    ("caltech", "test"): 0.0,
    ("jpl", "train"): 0.037816,
    ("jpl", "validation"): 0.037153,
    ("jpl", "test"): 0.027001,
}
FIDELITY_TOL = 0.001  # 允许 round(6) 精度误差

# A4 observable 三类（审查结论39 §7）
OBS_CLASS = {
    # Class I: definitional — 与 candidate 定义代数相关，不单独进 A5
    "median_actual_kw": "definitional",
    # Class II: baseline_related_history — 与 A2 基线相近，更可能强化 D1-P
    "median_recent_actual_q90": "baseline_related_history",
    "median_recent_actual_var": "baseline_related_history",
    "median_lagged_pilot_actual_ratio": "baseline_related_history",
    # Class III: independent_operational — 最值得关注
    "median_elapsed": "independent_operational",
    "pilot_coverage": "independent_operational",
    "median_response_persistence": "independent_operational",
    "severe_gap_fraction": "independent_operational",
    # std_actual_kw 介于 I/II 之间，标 baseline_related
    "std_actual_kw": "baseline_related_history",
}
TAUTOLOGICAL_OBS = {
    k for k, v in OBS_CLASS.items() if v == "definitional"
}
A5_ELIGIBLE_CLASSES = {"baseline_related_history", "independent_operational"}

MINUTE_COLS = [
    "session_id", "site", "station_id", "timestamp_utc",
    "connected_elapsed_min", "field_mode",
    "actual_power_kw", "pilot_power_kw", "pilot_available",
    "gap_flag", "severe_gap_before",
]


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
                raise FileNotFoundError(
                    f"候选表不存在 {p}；"
                    f"{'run --pretest first' if split != 'test' else 'check E3F'}"
                )
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
                filter=pred, columns=MINUTE_COLS
            ).to_pandas()
            mins[pool][split] = df
    return mins


def _load_e1_events() -> dict[str, pd.DataFrame]:
    evs: dict[str, pd.DataFrame] = {}
    for split in SPLITS:
        p = E1_DIR / f"e1_full_{split}_event_table.parquet"
        if p.exists():
            evs[split] = pd.read_parquet(p)
    return evs


# ---- A3: 强简单基线压力审计（修正） ----


def _elimination(
    rate_other: float, rate_a0: float
) -> tuple[float | None, bool]:
    """审查结论38 fix-1: A0=0 → NA + evaluable=False。"""
    if rate_a0 == 0 or rate_a0 is None or pd.isna(rate_a0):
        return None, False
    return float(1 - rate_other / rate_a0), True


def _daily_energy_share(
    cand: pd.DataFrame, tm: pd.DataFrame
) -> dict[str, float | None]:
    """E3/K1 exact evaluable-day 口径（与 frozen E3 同源）。

    candidate table day（valid paired cycle day）→ EV day energy。
    candidate=False 的 evaluable day → share=0 真实零（进入 median）。
    无 valid cycle 的 day → 不进入。
    """
    if len(cand) == 0:
        return {"median": None, "mean": None}
    cand_day = cand.groupby("day")[
        "candidate_energy_A2_prev_actual_kwh"
    ].sum()
    ev = tm.copy()
    ev["day"] = ev["timestamp_utc"].astype(str).str[:10]
    ev_day = ev.groupby("day")["actual_power_kw"].sum() / 60.0
    ev_on_eval = ev_day.reindex(cand_day.index).clip(lower=1e-6)
    share = cand_day.div(ev_on_eval)
    return {
        "median": round(float(share.median()), 6) if len(share) else None,
        "mean": round(float(share.mean()), 6) if len(share) else None,
    }


def _fidelity_assert(
    pool: str, split: str, recomputed: float | None
) -> dict[str, Any]:
    """审查结论39: recomputed daily-share ≈ frozen E3 split-level truth。"""
    truth = FROZEN_DAILY_SHARE.get((pool, split))
    if truth is None or recomputed is None:
        return {"frozen": truth, "recomputed": recomputed, "pass": None}
    passed = abs(recomputed - truth) < FIDELITY_TOL
    return {
        "frozen": truth,
        "recomputed": recomputed,
        "pass": bool(passed),
        "diff": round(recomputed - truth, 6),
    }


def run_a3(
    cands: dict[str, dict[str, pd.DataFrame]],
    minutes: dict[str, dict[str, pd.DataFrame]],
) -> dict:
    """A3: rate/elimination/daily share/concentration by split×month + station exposure。"""
    all_rows: list[dict[str, Any]] = []
    fidelity_results: dict[str, dict[str, Any]] = {}

    for pool in POOLS:
        for split in SPLITS:
            cand = cands[pool][split].copy()
            if len(cand) == 0:
                continue
            proxies = (
                ["A0_avg", "A2_prev_actual", "A3_rolling_quantile"]
                if pool == "caltech"
                else ["A2_prev_actual", "A3_rolling_quantile"]
            )

            # ---- by month ----
            month_rows: list[dict[str, Any]] = []
            for month, gm in cand.groupby("month"):
                row: dict[str, Any] = {
                    "pool": pool, "split": split, "month": month,
                }
                row["n_valid_cycles"] = int(len(gm))
                for p in proxies:
                    col_c = f"candidate_{p}"
                    col_e = f"candidate_energy_{p}_kwh"
                    if col_c in gm.columns:
                        row[f"rate_{p}"] = round(
                            float(gm[col_c].mean()), 6)
                        row[f"n_candidate_{p}"] = int(gm[col_c].sum())
                        row[f"energy_{p}_kwh"] = round(
                            float(gm[col_e].sum()), 6)
                if "rate_A0_avg" in row:
                    for p in ("A2_prev_actual", "A3_rolling_quantile"):
                        if f"rate_{p}" in row:
                            elim, evaluable = _elimination(
                                row[f"rate_{p}"], row["rate_A0_avg"])
                            row[f"elimination_{p}_vs_A0"] = (
                                round(elim, 6) if elim is not None else None)
                            row[f"elimination_{p}_evaluable"] = evaluable
                month_rows.append(row)
            month_df = pd.DataFrame(month_rows)
            month_df.to_csv(
                OUT / f"a3_{pool}_{split}_by_month.csv", index=False)

            # ---- split-level summary ----
            summary: dict[str, Any] = {
                "pool": pool, "split": split,
                "n_valid_cycles": int(len(cand)),
                "n_months": int(cand["month"].nunique()),
            }
            for p in proxies:
                col_c = f"candidate_{p}"
                if col_c in cand.columns:
                    summary[f"rate_{p}"] = round(
                        float(cand[col_c].mean()), 6)
                    summary[f"n_candidate_{p}"] = int(cand[col_c].sum())
            if "rate_A0_avg" in summary:
                for p in ("A2_prev_actual", "A3_rolling_quantile"):
                    if f"rate_{p}" in summary:
                        elim, _ = _elimination(
                            summary[f"rate_{p}"], summary["rate_A0_avg"])
                        summary[f"elimination_{p}_vs_A0"] = (
                            round(elim, 6) if elim is not None else None)

            # daily energy share + fidelity assertion
            daily = _daily_energy_share(cand, minutes[pool][split])
            summary["daily_candidate_energy_share_median"] = daily["median"]
            summary["daily_candidate_energy_share_mean"] = daily["mean"]
            fid = _fidelity_assert(pool, split, daily["median"])
            fidelity_results[f"{pool}_{split}"] = fid
            summary["daily_share_fidelity"] = fid

            # concentration
            opp = (
                cand[cand["candidate_A2_prev_actual"]]
                if "candidate_A2_prev_actual" in cand.columns
                else pd.DataFrame())
            if len(opp):
                opp_eng = opp.groupby("month")[
                    "candidate_energy_A2_prev_actual_kwh"].sum()
                summary["top_month_share_opp_energy"] = round(
                    float(opp_eng.max() / max(opp_eng.sum(), 1e-9)), 6)
                summary["top_month"] = str(opp_eng.idxmax())

            # month-level >80% diagnostic（A2 + A3）
            for p in ("A2_prev_actual", "A3_rolling_quantile"):
                elim_col = f"elimination_{p}_vs_A0"
                eval_col = f"elimination_{p}_evaluable"
                if elim_col in month_df.columns:
                    eval_months = month_df[month_df[eval_col] == True]  # noqa: E712
                    gt80 = eval_months[eval_months[elim_col] > 0.80]
                    summary[f"n_months_evaluable_{p}"] = int(
                        len(eval_months))
                    summary[f"n_months_{p}_elim_gt_80"] = int(len(gt80))
                    summary[f"months_{p}_elim_gt_80"] = sorted(
                        gt80["month"].tolist())

            all_rows.append(summary)

            # ---- station exposure（仅 caltech）----
            if pool == "caltech":
                tm = minutes[pool][split].copy()
                tm["cycle"] = tm["timestamp_utc"].dt.floor("5min")
                cycle_st = tm.groupby(["site", "cycle"])[
                    "station_id"].apply(
                    lambda s: sorted(set(s))).reset_index(name="stations")
                cand_ws = cand.merge(
                    cycle_st, on=["site", "cycle"], how="left")
                total_cand = int(
                    cand["candidate_A2_prev_actual"].sum()
                ) if "candidate_A2_prev_actual" in cand.columns else 0
                exploded = cand_ws.explode("stations").dropna(
                    subset=["stations"])
                st_valid = exploded.groupby("stations").size().reset_index(
                    name="n_valid_cycles_exposed")
                st_cand = exploded[
                    exploded["candidate_A2_prev_actual"]
                    if "candidate_A2_prev_actual" in exploded.columns
                    else False
                ].groupby("stations").size().reset_index(
                    name="n_candidate_cycles_exposed")
                st_df = st_valid.merge(
                    st_cand, on="stations", how="left").fillna(0)
                st_df["n_candidate_cycles_exposed"] = st_df[
                    "n_candidate_cycles_exposed"].astype(int)
                st_df["fraction_of_pool_candidate_exposed"] = st_df[
                    "n_candidate_cycles_exposed"] / max(total_cand, 1)
                st_df = st_df.rename(columns={"stations": "station"})
                st_df.to_csv(
                    OUT / f"a3_{pool}_{split}_station_exposure.csv",
                    index=False)

    # ---- exact aggregate output ----
    pd.DataFrame(all_rows).to_csv(
        OUT / "a3_baseline_pressure.csv", index=False)

    all_fid_pass = all(
        v["pass"] for v in fidelity_results.values()
        if v["pass"] is not None)

    a3_summary = {
        "module": "A3_baseline_pressure",
        "stop_line_unchanged": (
            "max(A2,A3) elimination > 80% → STOP_COMPLEX_MODEL（不改）"),
        "daily_share_fidelity": fidelity_results,
        "daily_share_fidelity_all_pass": bool(all_fid_pass),
        "splits": all_rows,
        "note": (
            "station exposure = set membership diagnostic，不报可加总 "
            "station energy。A0=0 → NA + evaluable=False。"
            "daily_candidate_energy_share 用 E3/K1 exact evaluable-day 口径。"
            "post-hoc month >80% ≠ formal STOP_COMPLEX_MODEL triggered。"),
    }
    (OUT / "a3_baseline_pressure.json").write_text(
        json.dumps(a3_summary, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return a3_summary


# ---- A4: 跨域定位（修正） ----


def _check_s1(row: pd.Series, s1_set: set) -> bool:
    """S1 cycle membership check（避免 lambda-in-loop B023）。"""
    return (row["site"], row["cycle"]) in s1_set


def _cycle_observables(tm: pd.DataFrame) -> pd.DataFrame:
    """pool×cycle 级在线可观测量。

    审查结论39 §5: 先聚合到 5min cycle，再 session×run 组内 shift(1)+rolling。
    审查结论39 §6: rolling 不跨 run/gap（冷启动）。
    审查结论39 §8: 用 severe_gap_before（pre-action 可知），不用 gap_flag。
    审查结论39 §9: pilot_actual_ratio → lagged。
    """
    tm = tm.copy()
    tm["cycle"] = tm["timestamp_utc"].dt.floor("5min")
    tm["active"] = (tm["actual_power_kw"] >= 0.5).astype(float)
    tm["has_pilot"] = tm["pilot_power_kw"].notna().astype(float)

    # 1) 先聚合到 session×cycle 级
    sess_cycle = tm.groupby(
        ["site", "session_id", "cycle"], sort=False
    ).agg(
        actual_mean=("actual_power_kw", "mean"),
        pilot_mean=("pilot_power_kw", "mean"),
        pilot_available_frac=("has_pilot", "mean"),
        elapsed_min=("connected_elapsed_min", "min"),
        severe_gap_any=("severe_gap_before", "max"),
        gap_any=("gap_flag", "max"),
        n_active_min=("active", "sum"),
    ).reset_index()

    # 2) session×run 组内 shift(1) + rolling（不跨 run/gap）
    sess_cycle = sess_cycle.sort_values(["session_id", "cycle"])
    # run boundary: actual_mean NaN 或 cycle gap > 5min → 冷启动
    sess_cycle["_gap"] = sess_cycle["actual_mean"].isna()
    sess_cycle["_prev_cycle"] = sess_cycle.groupby(
        "session_id", sort=False)["cycle"].shift(1)
    sess_cycle["_cycle_gap"] = (
        sess_cycle["cycle"] - sess_cycle["_prev_cycle"]
    ).dt.total_seconds() / 60.0
    sess_cycle["_break"] = (
        sess_cycle["_gap"].fillna(True)
        | (sess_cycle["_cycle_gap"] > 5.0).fillna(True)
    )
    sess_cycle["_run"] = sess_cycle.groupby(
        "session_id", sort=False)["_break"].cumsum()
    run_key = ["session_id", "_run"]

    sess_cycle["actual_lag1"] = sess_cycle.groupby(
        run_key, sort=False)["actual_mean"].shift(1)
    sess_cycle["pilot_lag1"] = sess_cycle.groupby(
        run_key, sort=False)["pilot_mean"].shift(1)
    sess_cycle["recent_actual_q90"] = sess_cycle.groupby(
        run_key, sort=False)["actual_mean"].transform(
        lambda s: s.shift(1).rolling(12, min_periods=2).quantile(0.90))
    sess_cycle["recent_actual_var"] = sess_cycle.groupby(
        run_key, sort=False)["actual_mean"].transform(
        lambda s: s.shift(1).rolling(12, min_periods=2).var())
    sess_cycle["response_change"] = (
        sess_cycle["actual_mean"] - sess_cycle["actual_lag1"]
    ).abs()
    sess_cycle["lagged_pilot_actual_ratio"] = (
        sess_cycle["pilot_lag1"]
        / sess_cycle["actual_lag1"].clip(lower=1e-6)
    )
    sess_cycle["history_supported"] = sess_cycle[
        "recent_actual_q90"].notna()

    # 3) 聚合到 pool×cycle 级
    obs = sess_cycle.groupby(["site", "cycle"]).agg(
        n_active_sessions=(
            "session_id",
            lambda s: sess_cycle.loc[
                s.index, "n_active_min"
            ].gt(0).sum()),
        n_connected=("session_id", "nunique"),
        median_elapsed=("elapsed_min", "median"),
        median_actual_kw=("actual_mean", "median"),
        std_actual_kw=("actual_mean", "std"),
        pilot_coverage=("pilot_available_frac", "mean"),
        median_pilot_kw=("pilot_mean", "median"),
        median_recent_actual_q90=("recent_actual_q90", "median"),
        median_recent_actual_var=("recent_actual_var", "median"),
        median_response_persistence=("response_change", "median"),
        median_lagged_pilot_actual_ratio=(
            "lagged_pilot_actual_ratio", "median"),
        severe_gap_fraction=("severe_gap_any", "mean"),
        history_coverage=("history_supported", "mean"),
    ).reset_index()
    obs["pilot_actual_ratio"] = (
        obs["median_pilot_kw"]
        / obs["median_actual_kw"].clip(lower=1e-6))
    return obs


def run_a4(
    cands: dict[str, dict[str, pd.DataFrame]],
    minutes: dict[str, dict[str, pd.DataFrame]],
    e1_events: dict[str, pd.DataFrame],
) -> dict:
    """A4: 跨域定位（修正：concurrency / S1-S2-S3 非互斥 / lagged / NaN / test_not_reversed）。"""
    OBS_COLS = [k for k in OBS_CLASS.keys()]
    all_bucket_rows: list[dict[str, Any]] = []
    results: dict[str, Any] = {}
    e1_mapping: dict[str, Any] = {}

    for pool in POOLS:
        results[pool] = {}
        for split in SPLITS:
            cand = cands[pool][split]
            tm = minutes[pool][split]
            if len(cand) == 0:
                continue

            obs = _cycle_observables(tm)
            # P0: concurrency_bucket 用 frozen candidate table n_active
            merged = cand.merge(
                obs, on=["site", "cycle"], how="left",
                suffixes=("", "_obs"))
            merged["concurrency_bucket"] = pd.cut(
                merged["n_active"],
                bins=CONCURRENCY_BUCKETS,
                labels=CONCURRENCY_LABELS,
                right=False,
                include_lowest=True).astype(str)
            merged["is_candidate"] = merged["candidate_A2_prev_actual"]

            # ---- S1/S2/S3 非互斥（审查结论39 §3）----
            # S1 = E1-core event-start cycle（不展开 duration，审查结论39 §4）
            s1_cycle_set: set[tuple[str, pd.Timestamp]] = set()
            n_e1_core = 0
            n_e1_core_sessions = 0
            if pool == "caltech" and split in e1_events:
                e1 = e1_events[split]
                core = e1[e1["event_phase"] == "core_run_segment"]
                n_e1_core = int(len(core))
                n_e1_core_sessions = int(core["session_id"].nunique())
                for _, ev in core.iterrows():
                    c_start = pd.to_datetime(
                        ev["start_utc"]).floor("5min")
                    s1_cycle_set.add((ev["site"], c_start))
            # S1 = E1-core event-start cycle（vectorized set lookup，避免 B023）
            if s1_cycle_set:
                merged["is_e1_core"] = merged.apply(
                    _check_s1, axis=1, args=(s1_cycle_set,))
            else:
                merged["is_e1_core"] = False
            merged["is_e3_valid"] = True  # candidate table 行都是 valid
            merged["is_e3_candidate_A2"] = merged["is_candidate"]
            # S1 ∩ S2, S1 ∩ S3 都允许存在
            e1_mapping[f"{pool}_{split}"] = {
                "n_e1_core_events": n_e1_core,
                "n_e1_core_sessions": n_e1_core_sessions,
                "n_unique_event_start_cycles": int(len(s1_cycle_set)),
                "n_mapped_to_e3_valid": int(merged["is_e1_core"].sum()),
                "n_S1_and_S2": int(
                    (merged["is_e1_core"] & merged["is_e3_candidate_A2"]).sum()),
                "n_S1_and_S3": int(
                    (merged["is_e1_core"] & ~merged["is_e3_candidate_A2"]).sum()),
            }

            # ---- 同 concurrency bucket candidate=True vs False ----
            for bucket in CONCURRENCY_LABELS:
                sub = merged[merged["concurrency_bucket"] == bucket]
                if len(sub) == 0:
                    continue
                true_g = sub[sub["is_candidate"]]
                false_g = sub[~sub["is_candidate"]]
                row: dict[str, Any] = {
                    "pool": pool, "split": split,
                    "concurrency_bucket": bucket,
                    "n_candidate_true": int(len(true_g)),
                    "n_candidate_false": int(len(false_g)),
                }
                for col in OBS_COLS:
                    if col not in sub.columns:
                        continue
                    t_med = true_g[col].median()
                    f_med = false_g[col].median()
                    t_val = (
                        round(float(t_med), 6)
                        if len(true_g) and pd.notna(t_med) else None)
                    f_val = (
                        round(float(f_med), 6)
                        if len(false_g) and pd.notna(f_med) else None)
                    row[f"median_{col}_true"] = t_val
                    row[f"median_{col}_false"] = f_val
                    if t_val is not None and f_val is not None:
                        if t_med > f_med:
                            row[f"direction_{col}"] = "true>false"
                        elif t_med < f_med:
                            row[f"direction_{col}"] = "true<false"
                        else:
                            row[f"direction_{col}"] = "equal"
                    else:
                        row[f"direction_{col}"] = "nan"
                    row[f"obs_class_{col}"] = OBS_CLASS.get(col, "unknown")
                all_bucket_rows.append(row)
            results[pool][split] = {
                "n_valid_cycles": int(len(merged)),
                "n_candidate_true": int(merged["is_candidate"].sum()),
                "n_candidate_false": int(
                    (~merged["is_candidate"]).sum()),
                "n_S1_e1_core": int(merged["is_e1_core"].sum()),
                "n_S2_e3_opp": int(merged["is_e3_candidate_A2"].sum()),
                "n_S3_valid_no_opp": int(
                    (~merged["is_e3_candidate_A2"]).sum()),
            }

    # ---- exact aggregate output ----
    bucket_df = pd.DataFrame(all_bucket_rows)
    bucket_df.to_csv(OUT / "a4_cross_domain.csv", index=False)
    for pool in POOLS:
        for split in SPLITS:
            sub = bucket_df[
                (bucket_df["pool"] == pool)
                & (bucket_df["split"] == split)]
            if len(sub):
                sub.to_csv(
                    OUT / f"a4_{pool}_{split}_bucket_comparison.csv",
                    index=False)

    # ---- 方向一致性 + test_not_reversed（审查结论39 §11/§12）----
    consistency: dict[str, Any] = {}
    a5_candidates: list[dict[str, Any]] = []
    for pool in POOLS:
        consistency[pool] = {}
        for bucket in CONCURRENCY_LABELS:
            consistency[pool][bucket] = {}
            for col in OBS_COLS:
                dkey = f"direction_{col}"
                dirs_by_split: dict[str, str] = {}
                for split in SPLITS:
                    sub = bucket_df[
                        (bucket_df["pool"] == pool)
                        & (bucket_df["split"] == split)
                        & (bucket_df["concurrency_bucket"] == bucket)]
                    if len(sub) and dkey in sub.columns:
                        dirs_by_split[split] = str(sub[dkey].iloc[0])
                    else:
                        dirs_by_split[split] = "missing"

                # train+val consistent（审查结论39 §12）
                tv_dirs = [dirs_by_split.get("train", "missing"),
                           dirs_by_split.get("validation", "missing")]
                tv_consistent = (
                    len(set(tv_dirs)) == 1
                    and tv_dirs[0] in VALID_DIRECTIONS)
                # test direction
                test_dir = dirs_by_split.get("test", "missing")
                test_not_reversed = True
                if tv_consistent and test_dir in VALID_DIRECTIONS:
                    tv_dir = tv_dirs[0]
                    # reversed = test 方向与 train/val 相反
                    test_not_reversed = (
                        test_dir == tv_dir
                        or test_dir == "missing")
                    # 如果 test 方向相反 → not_reversed = False
                    opposite = (
                        "true<false" if tv_dir == "true>false"
                        else "true>false")
                    if test_dir == opposite:
                        test_not_reversed = False
                elif tv_consistent and test_dir in ("missing", "nan"):
                    test_not_reversed = True  # unresolved
                elif not tv_consistent:
                    test_not_reversed = False

                is_consistent = bool(
                    tv_consistent and test_not_reversed)
                obs_cls = OBS_CLASS.get(col, "unknown")
                # A5 准入（审查结论39 §13）
                a5_eligible = bool(
                    is_consistent
                    and obs_cls in A5_ELIGIBLE_CLASSES
                    and test_dir != "missing")
                row_info = {
                    "direction_train": dirs_by_split.get("train"),
                    "direction_validation": dirs_by_split.get("validation"),
                    "direction_test": test_dir,
                    "train_validation_consistent": bool(tv_consistent),
                    "test_not_reversed": bool(test_not_reversed),
                    "consistent_across_splits": is_consistent,
                    "obs_class": obs_cls,
                    "a5_eligible": a5_eligible,
                }
                consistency[pool][bucket][col] = row_info
                if a5_eligible:
                    # 检查样本充足
                    for split in SPLITS:
                        sub = bucket_df[
                            (bucket_df["pool"] == pool)
                            & (bucket_df["split"] == split)
                            & (bucket_df["concurrency_bucket"] == bucket)]
                        if len(sub):
                            n_t = int(sub["n_candidate_true"].iloc[0])
                            n_f = int(sub["n_candidate_false"].iloc[0])
                            if n_t < 5 or n_f < 5:
                                a5_eligible = False
                    if a5_eligible:
                        a5_candidates.append({
                            "pool": pool, "bucket": bucket,
                            "observable": col,
                            "obs_class": obs_cls,
                            "direction": dirs_by_split["train"],
                            **row_info,
                        })

    a4_summary = {
        "module": "A4_cross_domain_localization",
        "design": (
            "concurrency = frozen candidate table n_active（EV nunique）；"
            "S1/S2/S3 非互斥；lagged observables（cycle-level shift+rolling，"
            "不跨 run/gap）；observable 三类；NaN→consistent=False；"
            "train+val consistent + test_not_reversed 分开报告"),
        "e1_cycle_mapping": e1_mapping,
        "by_pool_split": results,
        "direction_consistency": consistency,
        "a5_candidates": a5_candidates,
        "a5_entry_gate": {
            "A5_ENTRY": bool(len(a5_candidates) > 0),
            "criteria": (
                "非 definitional + pre-action + train稳定 + val同向 + "
                "test不反向 + true/false样本≥5 + 非纯 n_active 结构要求"),
            "n_candidates": int(len(a5_candidates)),
            "if_zero": "A5 = SKIP → Final R1 Gate Review",
        },
        "note": (
            "tautological obs（median_actual_kw）不单独进 A5。"
            "test 只产假设，不训练 classifier，不宣称已验证。"),
    }
    (OUT / "a4_cross_domain.json").write_text(
        json.dumps(a4_summary, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return a4_summary


# ---- manifest + main ----


def run_batch2() -> dict:
    prov = _git_prov(REPO)
    registry = pd.read_parquet(REG)
    cands = _load_candidates()
    minutes = _load_minutes(registry)
    e1_events = _load_e1_events()

    a3 = run_a3(cands, minutes)
    a4 = run_a4(cands, minutes, e1_events)

    outputs: dict[str, Any] = {}
    for p in sorted(OUT.glob("a3_*.csv")):
        outputs[str(p.relative_to(IMPL))] = {
            "sha256": _sha256_file(p),
            "rows": int(len(pd.read_csv(p)))}
    for p in sorted(OUT.glob("a4_*.csv")):
        outputs[str(p.relative_to(IMPL))] = {
            "sha256": _sha256_file(p),
            "rows": int(len(pd.read_csv(p)))}
    for p in sorted(OUT.glob("a3_*.json")) + sorted(
        OUT.glob("a4_*.json")
    ):
        if p.name == "batch2_manifest.json":
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
                "path": str(p.relative_to(IMPL)),
                "sha256": _sha256_file(p),
                "rows": int(len(pd.read_parquet(p)))}
    for split in SPLITS:
        p = E1_DIR / f"e1_full_{split}_event_table.parquet"
        if p.exists():
            input_provs[f"e1_{split}_events"] = {
                "path": str(p.relative_to(IMPL)),
                "sha256": _sha256_file(p),
                "rows": int(len(pd.read_parquet(p)))}
    for pool in POOLS:
        for split in SPLITS:
            input_provs[f"minutes_{pool}_{split}"] = {
                "rows": int(len(minutes[pool][split])),
                "sessions": int(
                    minutes[pool][split]["session_id"].nunique())}

    manifest = {
        "batch": "batch_2_1",
        "preregister": str(PREREG.relative_to(IMPL)),
        "preregister_sha256": _sha256_file(PREREG),
        "analysis_code_sha": prov["code_sha"],
        "worktree_clean": prov["worktree_clean"],
        "inputs": {
            "split_registry": {
                "path": str(REG.relative_to(IMPL)),
                "sha256": _sha256_file(REG),
                "rows": int(len(registry))},
            **input_provs,
        },
        "outputs": outputs,
        "a3_summary": a3,
        "a4_summary": a4,
        "discipline": (
            "只读 frozen evidence + registry + minute table；"
            "不重跑 formal；不调参；deterministic"),
    }
    (OUT / "batch2_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps({
        "batch": "batch_2_1",
        "daily_share_fidelity_all_pass": a3.get(
            "daily_share_fidelity_all_pass"),
        "a5_entry": a4["a5_entry_gate"]["A5_ENTRY"],
        "a5_n_candidates": a4["a5_entry_gate"]["n_candidates"],
        "a5_candidates": a4["a5_candidates"],
        "manifest_written": True,
    }, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    run_batch2()
