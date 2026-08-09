"""R1 最终收敛审计 Batch_2 确定性生成器（审查结论37；A3+A4，不重跑 formal）。

A3: 强简单基线压力审计（Caltech train/val/test × month × station exposure；
    JPL train/val/test × month；A0/A2/A3 rate/elimination/daily share/concentration/
    valid+candidate counts；不改 80% 线）。
    station 维度用 exposure diagnostic（n_valid/n_candidate/fraction_exposed），
    不报可加总 station energy（审查结论37 P1）。

A4: 跨域定位（S1 E1-core / S2 E3-opp / S3 valid-no-opp / JPL opp vs non-opp；
    在线可观测量 separation train/val/test 方向一致性）。
    对照组：同 n_active bucket 内 candidate=True vs candidate=False
    （不把 candidate 定义的结构条件误当 support predictor）。

只读 frozen evidence + registry + minute table；不调用 formal runner；
不重算事件/candidate 定义；只 groupby/join/slice；deterministic rerun。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

IMPL = Path(__file__).resolve().parents[2]  # patent_preexperiment
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

MINUTE_COLS = [
    "session_id", "site", "station_id", "timestamp_utc",
    "connected_elapsed_min", "field_mode",
    "actual_power_kw", "pilot_power_kw",
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
    """读 E3 候选表：test from raw/E3F，train/val from work/E3F_pretest。"""
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
                    f"候选表不存在 {p}；{'run --pretest first' if split != 'test' else 'check E3F'}"
                )
            cands[pool][split] = pd.read_parquet(p)
    return cands


def _load_minutes(registry: pd.DataFrame) -> dict[str, dict[str, pd.DataFrame]]:
    """读分钟表（caltech + jpl，各 split）。"""
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


# ---- A3: 强简单基线压力审计 ----


def run_a3(
    cands: dict[str, dict[str, pd.DataFrame]],
    minutes: dict[str, dict[str, pd.DataFrame]],
) -> dict:
    """A3: rate/elimination/share/concentration by split×month + station exposure。"""
    results: dict[str, Any] = {}

    for pool in POOLS:
        results[pool] = {}
        for split in SPLITS:
            cand = cands[pool][split].copy()
            if len(cand) == 0:
                continue
            proxies = ["A0_avg", "A2_prev_actual", "A3_rolling_quantile"] \
                if pool == "caltech" else ["A2_prev_actual", "A3_rolling_quantile"]

            # ---- by month ----
            month_rows = []
            for month, gm in cand.groupby("month"):
                row: dict[str, Any] = {"month": month}
                row["n_valid_cycles"] = int(len(gm))
                for p in proxies:
                    col_c = f"candidate_{p}"
                    col_e = f"candidate_energy_{p}_kwh"
                    if col_c in gm.columns:
                        row[f"rate_{p}"] = round(float(gm[col_c].mean()), 6)
                        row[f"n_candidate_{p}"] = int(gm[col_c].sum())
                        row[f"energy_{p}_kwh"] = round(float(gm[col_e].sum()), 6)
                if "rate_A0_avg" in row and "rate_A2_prev_actual" in row:
                    row["elimination_A2_vs_A0"] = round(
                        float(1 - row["rate_A2_prev_actual"]
                              / max(row["rate_A0_avg"], 1e-9)), 6)
                if "rate_A0_avg" in row and "rate_A3_rolling_quantile" in row:
                    row["elimination_A3_vs_A0"] = round(
                        float(1 - row["rate_A3_rolling_quantile"]
                              / max(row["rate_A0_avg"], 1e-9)), 6)
                month_rows.append(row)
            month_df = pd.DataFrame(month_rows)
            month_df.to_csv(
                OUT / f"a3_{pool}_{split}_by_month.csv", index=False)

            # ---- split-level summary ----
            summary: dict[str, Any] = {
                "n_valid_cycles": int(len(cand)),
                "n_months": int(cand["month"].nunique()),
            }
            for p in proxies:
                col_c = f"candidate_{p}"
                if col_c in cand.columns:
                    summary[f"rate_{p}"] = round(float(cand[col_c].mean()), 6)
                    summary[f"n_candidate_{p}"] = int(cand[col_c].sum())
            if "rate_A0_avg" in summary:
                for p in ("A2_prev_actual", "A3_rolling_quantile"):
                    if f"rate_{p}" in summary:
                        summary[f"elimination_{p}_vs_A0"] = round(
                            float(1 - summary[f"rate_{p}"]
                                  / max(summary["rate_A0_avg"], 1e-9)), 6)

            # concentration
            opp = cand[cand["candidate_A2_prev_actual"]] \
                if "candidate_A2_prev_actual" in cand.columns \
                else pd.DataFrame()
            if len(opp):
                opp_eng = opp.groupby("month")["candidate_energy_A2_prev_actual_kwh"].sum()
                summary["top_month_share_opp_energy"] = round(
                    float(opp_eng.max() / max(opp_eng.sum(), 1e-9)), 6)
                summary["top_month"] = str(opp_eng.idxmax())
            results[pool][split] = summary

            # ---- station exposure（仅 caltech；exposure diagnostic，不可加总 energy）----
            if pool == "caltech":
                tm = minutes[pool][split].copy()
                tm["cycle"] = tm["timestamp_utc"].dt.floor("5min")
                cycle_stations = tm.groupby(["site", "cycle"])[
                    "station_id"].apply(lambda s: sorted(set(s))
                                        ).reset_index(name="stations")
                cand_with_stations = cand.merge(
                    cycle_stations, on=["site", "cycle"], how="left")
                total_cand_cycles = int(
                    cand["candidate_A2_prev_actual"].sum()
                ) if "candidate_A2_prev_actual" in cand.columns else 0
                # explode stations → groupby station（避免 lambda-in-loop B023）
                exploded = cand_with_stations.explode("stations")
                exploded = exploded.dropna(subset=["stations"])
                st_valid = exploded.groupby("stations").size().reset_index(
                    name="n_valid_cycles_exposed")
                st_cand = exploded[
                    exploded["candidate_A2_prev_actual"]
                    if "candidate_A2_prev_actual" in exploded.columns else False
                ].groupby("stations").size().reset_index(
                    name="n_candidate_cycles_exposed")
                st_df = st_valid.merge(
                    st_cand, on="stations", how="left").fillna(0)
                st_df["n_candidate_cycles_exposed"] = st_df[
                    "n_candidate_cycles_exposed"].astype(int)
                st_df["fraction_of_pool_candidate_exposed"] = st_df[
                    "n_candidate_cycles_exposed"] / max(total_cand_cycles, 1)
                st_df = st_df.rename(columns={"stations": "station"})
                st_df.to_csv(
                    OUT / f"a3_{pool}_{split}_station_exposure.csv",
                    index=False)

    # ---- A3 summary JSON ----
    a3_summary = {
        "module": "A3_baseline_pressure",
        "stop_line_unchanged": "max(A2,A3) elimination > 80% → STOP_COMPLEX_MODEL（不改）",
        "by_pool_split": results,
        "note": (
            "station exposure = set membership diagnostic，"
            "不报可加总 station opportunity energy（审查结论37 P1）"
        ),
    }
    (OUT / "a3_baseline_pressure.json").write_text(
        json.dumps(a3_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return a3_summary


# ---- A4: 跨域定位 ----


def _cycle_observables(tm: pd.DataFrame) -> pd.DataFrame:
    """分钟表 → pool×cycle 级在线可观测量。"""
    tm = tm.copy()
    tm["cycle"] = tm["timestamp_utc"].dt.floor("5min")
    tm["active"] = (tm["actual_power_kw"] >= 0.5).astype(float)
    tm["has_pilot"] = tm["pilot_power_kw"].notna().astype(float)
    obs = tm.groupby(["site", "cycle"]).agg(
        n_active=("active", "sum"),
        n_connected=("session_id", "nunique"),
        median_elapsed=("connected_elapsed_min", "median"),
        median_actual_kw=("actual_power_kw", "median"),
        std_actual_kw=("actual_power_kw", "std"),
        pilot_coverage=("has_pilot", "mean"),
        median_pilot_kw=("pilot_power_kw", "median"),
    ).reset_index()
    obs["pilot_actual_ratio"] = (
        obs["median_pilot_kw"] / obs["median_actual_kw"].clip(lower=1e-6))
    obs["concurrency_bucket"] = pd.cut(
        obs["n_active"], bins=CONCURRENCY_BUCKETS, labels=CONCURRENCY_LABELS,
        right=False, include_lowest=True).astype(str)
    return obs


def run_a4(
    cands: dict[str, dict[str, pd.DataFrame]],
    minutes: dict[str, dict[str, pd.DataFrame]],
    e1_events: dict[str, pd.DataFrame],
) -> dict:
    """A4: 跨域定位 + 同 n_active bucket candidate=True vs False 对照。"""
    OBS_COLS = [
        "n_active", "median_elapsed", "median_actual_kw",
        "std_actual_kw", "pilot_coverage", "pilot_actual_ratio",
    ]
    results: dict[str, Any] = {}

    for pool in POOLS:
        results[pool] = {}
        for split in SPLITS:
            cand = cands[pool][split]
            tm = minutes[pool][split]
            if len(cand) == 0:
                continue
            obs = _cycle_observables(tm)
            merged = cand.merge(obs, on=["site", "cycle"], how="left",
                                suffixes=("", "_obs"))
            merged["concurrency_bucket"] = merged["concurrency_bucket"].fillna("1")
            merged["is_candidate"] = merged["candidate_A2_prev_actual"]

            # ---- 同 n_active bucket 内 candidate=True vs False ----
            bucket_rows = []
            for bucket in CONCURRENCY_LABELS:
                sub = merged[merged["concurrency_bucket"] == bucket]
                if len(sub) == 0:
                    continue
                true_g = sub[sub["is_candidate"]]
                false_g = sub[~sub["is_candidate"]]
                row: dict[str, Any] = {
                    "concurrency_bucket": bucket,
                    "n_candidate_true": int(len(true_g)),
                    "n_candidate_false": int(len(false_g)),
                }
                for col in OBS_COLS:
                    if col in sub.columns:
                        row[f"median_{col}_true"] = round(
                            float(true_g[col].median()), 6) if len(true_g) else None
                        row[f"median_{col}_false"] = round(
                            float(false_g[col].median()), 6) if len(false_g) else None
                        if len(true_g) and len(false_g):
                            row[f"direction_{col}"] = (
                                "true>false" if true_g[col].median() > false_g[col].median()
                                else "true<false" if true_g[col].median() < false_g[col].median()
                                else "equal")
                bucket_rows.append(row)
            bucket_df = pd.DataFrame(bucket_rows)
            bucket_df.to_csv(
                OUT / f"a4_{pool}_{split}_bucket_comparison.csv", index=False)
            results[pool][split] = {
                "n_valid_cycles": int(len(merged)),
                "n_candidate_true": int(merged["is_candidate"].sum()),
                "n_candidate_false": int((~merged["is_candidate"]).sum()),
                "bucket_summary": bucket_df.to_dict("records"),
            }

    # ---- 方向一致性检查（train/val/test 同 bucket 同 observable 方向是否一致）----
    consistency: dict[str, Any] = {}
    for pool in POOLS:
        consistency[pool] = {}
        for bucket in CONCURRENCY_LABELS:
            consistency[pool][bucket] = {}
            for col in OBS_COLS:
                dkey = f"direction_{col}"
                directions = []
                for split in SPLITS:
                    df_path = OUT / f"a4_{pool}_{split}_bucket_comparison.csv"
                    if df_path.exists():
                        df = pd.read_csv(df_path)
                        row = df[df["concurrency_bucket"] == bucket]
                        if len(row) and dkey in row.columns:
                            directions.append(str(row[dkey].iloc[0]))
                if len(set(directions)) == 1 and directions[0] != "equal":
                    consistency[pool][bucket][col] = {
                        "direction": directions[0],
                        "consistent_across_splits": True,
                        "splits": directions,
                    }
                else:
                    consistency[pool][bucket][col] = {
                        "direction": "mixed" if len(set(directions)) > 1 else "n/a",
                        "consistent_across_splits": False,
                        "splits": directions,
                    }

    a4_summary = {
        "module": "A4_cross_domain_localization",
        "design": (
            "同 n_active bucket 内 candidate=True vs candidate=False 对照"
            "（不把 candidate 定义的结构条件误当 support predictor）"
        ),
        "by_pool_split": {p: {s: r for s, r in results[p].items()} for p in POOLS},
        "direction_consistency": consistency,
        "note": (
            "direction consistent = train/val/test 同 bucket 同 observable 方向一致；"
            "仅 consistent 的 observable 才值得进入 A5 support-domain hypothesis。"
            "test 只产假设，不训练 classifier，不宣称已验证。"
        ),
    }
    (OUT / "a4_cross_domain.json").write_text(
        json.dumps(a4_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return a4_summary


# ---- manifest + main ----


from typing import Any  # noqa: E402


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
            "sha256": _sha256_file(p), "rows": int(len(pd.read_csv(p)))}
    for p in sorted(OUT.glob("a4_*.csv")):
        outputs[str(p.relative_to(IMPL))] = {
            "sha256": _sha256_file(p), "rows": int(len(pd.read_csv(p)))}
    for p in sorted(OUT.glob("a3_*.json")) + sorted(OUT.glob("a4_*.json")):
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
                "rows": int(len(pd.read_parquet(p))),
            }
    for split in SPLITS:
        p = E1_DIR / f"e1_full_{split}_event_table.parquet"
        if p.exists():
            input_provs[f"e1_{split}_events"] = {
                "path": str(p.relative_to(IMPL)),
                "sha256": _sha256_file(p),
                "rows": int(len(pd.read_parquet(p))),
            }
    for pool in POOLS:
        for split in SPLITS:
            input_provs[f"minutes_{pool}_{split}"] = {
                "rows": int(len(minutes[pool][split])),
                "sessions": int(minutes[pool][split]["session_id"].nunique()),
            }

    manifest = {
        "batch": "batch_2",
        "preregister": str(PREREG.relative_to(IMPL)),
        "preregister_sha256": _sha256_file(PREREG),
        "analysis_code_sha": prov["code_sha"],
        "worktree_clean": prov["worktree_clean"],
        "inputs": {
            "split_registry": {
                "path": str(REG.relative_to(IMPL)),
                "sha256": _sha256_file(REG),
                "rows": int(len(registry)),
            },
            **input_provs,
        },
        "outputs": outputs,
        "a3_summary": a3,
        "a4_summary": a4,
        "discipline": (
            "只读 frozen evidence + registry + minute table；"
            "不重跑 formal；不调参；deterministic"
        ),
    }
    (OUT / "batch2_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "a3_pools": list(a3["by_pool_split"].keys()),
        "a4_consistent_observables": {
            p: {b: {c: v["direction"] for c, v in items.items()
                    if v["consistent_across_splits"]}
                for b, items in a4["direction_consistency"][p].items()
                if any(v["consistent_across_splits"] for v in items.values())}
            for p in POOLS
        },
        "manifest_written": True,
    }, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    run_batch2()
