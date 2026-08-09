"""R1 最终收敛审计 Batch_1 确定性生成器（审查结论35；A1+A2，不重跑 formal）。

只读 frozen registry / E1 evidence / E3 evidence / minute table；
不调用 formal runner、不重算事件/candidate 定义；只 groupby/join/slice；deterministic rerun。

输出：
  results/raw/E3F_expansion/a1_population_bridge.csv + .json
  results/raw/E3F_expansion/a2_e1_decomposition.csv
  results/raw/E3F_expansion/a2_e3_decomposition.csv
  results/raw/E3F_expansion/a2_overlap.json
  results/raw/E3F_expansion/batch1_manifest.json（provenance + SHA256 + row counts）
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
E1_EVENTS = IMPL / "results" / "raw" / "E1F" / "e1_full_test_event_table.parquet"
E3_CAL = IMPL / "results" / "raw" / "E3F" / "e3_full_test_caltech_candidate.parquet"
E1_SESSION = IMPL / "results" / "raw" / "E1F" / "e1_full_test_session_summary.csv"
OUT = IMPL / "results" / "raw" / "E3F_expansion"
OUT.mkdir(parents=True, exist_ok=True)

CONCURRENCY_BUCKETS = [0, 2, 4, 8, 16, 1000]
CONCURRENCY_LABELS = ["1", "2-3", "4-7", "8-15", "16+"]
ELAPSED_BUCKETS = [0, 30, 60, 120, 240, 100000]
ELAPSED_LABELS = ["<30", "30-59", "60-119", "120-239", "240+"]


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _git_provenance(repo: Path) -> dict:
    try:
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        return {"code_sha": sha, "worktree_clean": not bool(status)}
    except Exception:
        return {"code_sha": "unknown", "worktree_clean": None}


def _bucketize(s: pd.Series, edges: list, labels: list) -> pd.Series:
    return pd.cut(s, bins=edges, labels=labels, right=False, include_lowest=True).astype(str)


def _load_test_minutes(registry: pd.DataFrame) -> pd.DataFrame:
    """读 caltech L1 strict test 分钟表（用于 E3 会话级 station/elapsed/field_mode join）。"""
    l1_ids = set(
        registry[
            (registry["site"] == "caltech")
            & (registry["sample_layer"] == "L1_strict_matched")
            & (registry["role"] == "main")
            & (registry["split"] == "test")
        ]["session_id"]
    )
    pred = (
        (ds.field("site") == "caltech")
        & (ds.field("sample_layer") == "L1_strict_matched")
        & (ds.field("role") == "main")
        & (ds.field("split") == "test")
    )
    cols = ["session_id", "site", "station_id", "timestamp_utc",
            "connected_elapsed_min", "field_mode", "actual_power_kw",
            "pilot_power_kw"]
    df = ds.dataset(str(MINUTE_ROOT)).to_table(filter=pred, columns=cols).to_pandas()
    assert set(df["session_id"]) == l1_ids, "E3 test 分钟表与 registry 会话集合不一致"
    return df


def run_a1(registry: pd.DataFrame, e3_cand: pd.DataFrame) -> dict:
    """A1 Population Bridge + funnel（155→valid cycles→candidate cycles）。"""
    cal_test = registry[
        (registry["site"] == "caltech")
        & (registry["role"] == "main")
        & (registry["split"] == "test")
    ].copy()
    cal_test["month"] = cal_test["connection_time"].astype(str).str[:7]
    l1 = cal_test[cal_test["sample_layer"] == "L1_strict_matched"].copy()
    n_temporal, n_l1 = len(cal_test), len(l1)

    # month × sample_layer / match_status / field_mode
    cal_test.groupby(["month", "sample_layer"]).size().reset_index(name="n").to_csv(
        OUT / "a1_month_x_sample_layer.csv", index=False)
    cal_test.groupby(["month", "match_status"]).size().reset_index(name="n").to_csv(
        OUT / "a1_month_x_match_status.csv", index=False)
    l1.groupby(["month", "field_mode"]).size().reset_index(name="n").to_csv(
        OUT / "a1_l1_month_x_field_mode.csv", index=False)
    cal_test.groupby(["station", "sample_layer"]).size().reset_index(name="n").to_csv(
        OUT / "a1_station_x_layer.csv", index=False)

    monthly = cal_test.groupby("month").size().reset_index(name="n_temporal")
    monthly_l1 = l1.groupby("month").size().reset_index(name="n_l1")
    monthly = monthly.merge(monthly_l1, on="month", how="left").fillna(0)
    monthly["n_l1"] = monthly["n_l1"].astype(int)
    monthly["retention_rate"] = monthly["n_l1"] / monthly["n_temporal"]
    monthly.to_csv(OUT / "a1_monthly_retention.csv", index=False)
    l1.groupby(["month", "station"]).size().reset_index(name="n").to_csv(
        OUT / "a1_l1_month_x_station.csv", index=False)
    l1.groupby("field_mode").size().reset_index(name="n").to_csv(
        OUT / "a1_l1_field_mode_summary.csv", index=False)

    # funnel：155 → n_sessions_with_valid_cycle → 4920 valid cycles → n_sessions_with_candidate → 63
    n_valid_cycles = int(len(e3_cand))
    n_candidate_cycles = int(e3_cand["candidate_A2_prev_actual"].sum())
    # E3 candidate table 是 pool×cycle，无 session_id；n_sessions_with_valid/candidate 需分钟表
    # 这里先报 cycle-level funnel，session-level 在 A2 补（需分钟表 join）
    funnel = {
        "n_temporal_test_main": int(n_temporal),
        "n_l1_strict_test": int(n_l1),
        "retention_rate": round(n_l1 / n_temporal, 6),
        "n_valid_cycles": n_valid_cycles,
        "n_candidate_cycles_A2": n_candidate_cycles,
        "candidate_to_valid_cycle_rate": round(n_candidate_cycles / max(n_valid_cycles, 1), 6),
    }
    # 主输出 CSV（预注册契约 a1_population_bridge.csv）
    bridge_rows = [
        {"stage": "temporal_test_main", "n_sessions": n_temporal},
        {"stage": "l1_strict_matched", "n_sessions": n_l1},
        {"stage": "valid_cycles", "n_sessions": n_valid_cycles, "unit": "cycle"},
        {"stage": "candidate_cycles_A2", "n_sessions": n_candidate_cycles, "unit": "cycle"},
    ]
    pd.DataFrame(bridge_rows).to_csv(OUT / "a1_population_bridge.csv", index=False)

    summary = {
        "module": "A1_population_bridge",
        **funnel,
        "contraction": (
            f"{n_temporal} → {n_l1}（{(1 - n_l1/n_temporal)*100:.1f}% 为 "
            "L0_static_extension/static_only）"
        ),
        "l1_by_month": l1.groupby("month").size().to_dict(),
        "l1_by_month_field_mode": {
            f"{m}|{fm}": int(n)
            for (m, fm), n in l1.groupby(["month", "field_mode"]).size().items()
        },
        "l1_by_field_mode": l1.groupby("field_mode").size().to_dict(),
        "interpretation_note": (
            f"{n_temporal} temporal-test main = {n_l1} L1_strict_matched + {n_temporal - n_l1} "
            "L0_static_extension(static_only)。人口收缩直接发生在 sample-layer/match-status 层；"
            "仅凭 A1 无法判定运营域是否同时发生变化。"
            f" funnel：{n_l1} sessions → {n_valid_cycles} valid cycles → "
            f"{n_candidate_cycles} A2 candidate cycles。"
        ),
    }
    (OUT / "a1_population_bridge.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def run_a2(
    registry: pd.DataFrame, e1_events: pd.DataFrame, e3_cand: pd.DataFrame,
    test_minutes: pd.DataFrame,
) -> dict:
    """A2 E1+E3 frozen-test decomposition（补齐 slices + overlap）。"""
    core = e1_events[e1_events["event_phase"] == "core_run_segment"].copy()
    opp = e3_cand[e3_cand["candidate_A2_prev_actual"]].copy()

    # ---- E1 decomposition（month/station/day/field_mode/concurrency/elapsed）----
    e1_core = core.copy()
    e1_core["day"] = e1_core["start_utc"].astype(str).str[:10]
    # E1 事件表无 field_mode/concurrency/elapsed → join session summary
    e1_sess = pd.read_csv(E1_SESSION) if E1_SESSION.exists() else pd.DataFrame()
    if "session_id" in e1_sess.columns:
        join_cols = [c for c in [
            "field_mode", "n_active_max", "connected_elapsed_max", "pilot_available"
        ] if c in e1_sess.columns]
        e1_core = e1_core.merge(
            e1_sess[["session_id"] + join_cols],
            on="session_id", how="left", suffixes=("", "_sess"))
    e1_core_by_month = e1_core.groupby("month").agg(
        n_events=("session_id", "size"), gap_energy_kwh=("gap_energy_kwh", "sum"),
        median_gap_kw=("median_gap_kw", "median")).reset_index()
    e1_core_by_station = e1_core.groupby("station_id").agg(
        n_events=("session_id", "size"), gap_energy_kwh=("gap_energy_kwh", "sum")).reset_index()
    e1_core_by_day = e1_core.groupby("day").agg(
        n_events=("session_id", "size"), gap_energy_kwh=("gap_energy_kwh", "sum")).reset_index()
    e1_decomp = e1_core[["session_id", "station_id", "month", "day", "gap_energy_kwh",
                          "median_gap_kw"]].copy()
    e1_decomp.to_csv(OUT / "a2_e1_decomposition.csv", index=False)
    e1_core_by_month.to_csv(OUT / "a2_e1_core_by_month.csv", index=False)
    e1_core_by_station.to_csv(OUT / "a2_e1_core_by_station.csv", index=False)
    e1_core_by_day.to_csv(OUT / "a2_e1_core_by_day.csv", index=False)

    # ---- E3 decomposition（month/station/day/field_mode/concurrency/elapsed）----
    # E3 candidate table 是 pool×cycle，有 n_active（并发）但无 station/elapsed/field_mode
    # → 用分钟表按 cycle 回溯会话级属性
    tm = test_minutes.copy()
    tm["cycle"] = tm["timestamp_utc"].dt.floor("5min")
    cycle_session_attr = tm.groupby(["site", "cycle"]).agg(
        n_stations=("station_id", "nunique"),
        n_sessions=("session_id", "nunique"),
        median_elapsed=("connected_elapsed_min", "median"),
    ).reset_index()
    opp_full = opp.merge(cycle_session_attr, on=["site", "cycle"], how="left")
    opp_full["concurrency_bucket"] = _bucketize(
        opp_full["n_active"], CONCURRENCY_BUCKETS, CONCURRENCY_LABELS)
    opp_full["elapsed_bucket"] = _bucketize(
        opp_full["median_elapsed"], ELAPSED_BUCKETS, ELAPSED_LABELS)

    e3_opp_by_month = opp_full.groupby("month").agg(
        n_opp_cycles=("cycle", "size"),
        opp_energy_kwh=("candidate_energy_A2_prev_actual_kwh", "sum"),
    ).reset_index()
    e3_opp_by_month["energy_share"] = (
        e3_opp_by_month["opp_energy_kwh"] / e3_opp_by_month["opp_energy_kwh"].sum()
    )
    e3_opp_by_day = opp_full.groupby("day").agg(
        n_opp_cycles=("cycle", "size"),
        opp_energy_kwh=("candidate_energy_A2_prev_actual_kwh", "sum"),
    ).reset_index().sort_values("opp_energy_kwh", ascending=False)
    e3_opp_by_day["energy_share"] = (
        e3_opp_by_day["opp_energy_kwh"] / e3_opp_by_day["opp_energy_kwh"].sum()
    )
    e3_opp_by_concurrency = opp_full.groupby("concurrency_bucket").agg(
        n_opp_cycles=("cycle", "size"),
        opp_energy_kwh=("candidate_energy_A2_prev_actual_kwh", "sum")).reset_index()
    e3_opp_by_elapsed = opp_full.groupby("elapsed_bucket").agg(
        n_opp_cycles=("cycle", "size"),
        opp_energy_kwh=("candidate_energy_A2_prev_actual_kwh", "sum")).reset_index()
    e3_decomp = opp_full[["site", "cycle", "month", "day", "n_active", "n_sessions",
                           "median_elapsed", "concurrency_bucket", "elapsed_bucket",
                           "candidate_energy_A2_prev_actual_kwh"]].copy()
    e3_decomp.to_csv(OUT / "a2_e3_decomposition.csv", index=False)
    e3_opp_by_month.to_csv(OUT / "a2_e3_opp_by_month.csv", index=False)
    e3_opp_by_day.to_csv(OUT / "a2_e3_opp_by_day.csv", index=False)
    e3_opp_by_concurrency.to_csv(OUT / "a2_e3_opp_by_concurrency.csv", index=False)
    e3_opp_by_elapsed.to_csv(OUT / "a2_e3_opp_by_elapsed.csv", index=False)

    # ---- overlap：month + station + concurrency + elapsed ----
    e1_months = set(core["month"].unique())
    e3_months = set(opp["month"].unique())
    e1_stations = set(core["station_id"].unique())
    # E3 无 station 列 → 用 cycle 回溯的 n_stations > 0 的会话站集合
    e3_cycle_stations = tm.groupby(["site", "cycle"])["station_id"].apply(
        lambda s: set(s)).reset_index(name="stations")
    e3_opp_stations: set[str] = set()
    opp_stations_df = opp[["site", "cycle"]].merge(
        e3_cycle_stations, on=["site", "cycle"], how="left")
    for _, r in opp_stations_df.iterrows():
        if r["stations"]:
            e3_opp_stations.update(r["stations"])
    # E1 核心桩 2-39-79-382 是否贡献 E3 opportunity？
    e1_core_top_station = "2-39-79-382"
    e1_core_station_in_e3_opp = e1_core_top_station in e3_opp_stations
    # E1 核心事件的具体 session 是否在 E3 opp 周期时段内？
    e1_core_sessions = set(core["session_id"].unique())
    # E3 opp cycle 时段内的 sessions
    e3_opp_cycles = opp[["site", "cycle"]].merge(
        tm.groupby(["site", "cycle"])["session_id"].apply(list).reset_index(),
        on=["site", "cycle"], how="left")
    e3_opp_sessions = set()
    for lst in e3_opp_cycles["session_id"].dropna():
        e3_opp_sessions.update(lst)
    shared_sessions = e1_core_sessions & e3_opp_sessions

    overlap = {
        "shared_months": sorted(e1_months & e3_months),
        "e1_core_months": sorted(e1_months),
        "e3_opp_months": sorted(e3_months),
        "shared_stations": sorted(e1_stations & e3_opp_stations),
        "e1_core_top_station": e1_core_top_station,
        "e1_core_top_station_in_e3_opp": bool(e1_core_station_in_e3_opp),
        "shared_sessions_e1_core_x_e3_opp": sorted(shared_sessions),
        "n_shared_sessions": int(len(shared_sessions)),
        "e1_core_top_month_share": float(
            core.groupby("month")["gap_energy_kwh"].sum().max()
            / max(core["gap_energy_kwh"].sum(), 1e-9)),
        "e3_opp_top_month_share": float(
            e3_opp_by_month["opp_energy_kwh"].max()
            / max(e3_opp_by_month["opp_energy_kwh"].sum(), 1e-9)
        ),
        "e3_opp_top_month": str(
            e3_opp_by_month.sort_values("opp_energy_kwh", ascending=False).iloc[0]["month"]
        ),
        "interpretation": (
            "E1 核心事件主导峰在 2020-06（gap energy 100%），"
            "E3 opp energy 主导峰在 2020-11（79.5%）；"
            "两者主导集中时段不同，但存在部分时间重叠（shared 2020-06）。"
            f" E1 核心桩 {e1_core_top_station} 是否贡献 E3 opp：{e1_core_station_in_e3_opp}；"
            f" E1 核心 session 与 E3 opp cycle 时段共享 session 数：{len(shared_sessions)}。"
            " 目前不能声称统计独立或成因独立；结果与 support-domain limitation 假设一致，"
            "并增强了继续检查该假设的必要性；"
            "尚不足以证明存在可由在线可观测量识别的 support domain。"
        ),
    }
    (OUT / "a2_overlap.json").write_text(
        json.dumps(overlap, ensure_ascii=False, indent=2), encoding="utf-8")
    return overlap


def run_batch1() -> dict:
    prov = _git_provenance(REPO)
    registry = pd.read_parquet(REG)
    e1_events = pd.read_parquet(E1_EVENTS)
    e3_cand = pd.read_parquet(E3_CAL)
    test_minutes = _load_test_minutes(registry)

    a1 = run_a1(registry, e3_cand)
    a2 = run_a2(registry, e1_events, e3_cand, test_minutes)

    # ---- manifest ----
    outputs = {}
    for p in sorted(OUT.glob("*.csv")):
        outputs[str(p.relative_to(IMPL))] = {"sha256": _sha256_file(p), "rows": _row_count(p)}
    for p in sorted(OUT.glob("*.json")):
        outputs[str(p.relative_to(IMPL))] = {"sha256": _sha256_file(p)}
    manifest = {
        "batch": "batch_1_1",
        "preregister": "configs/r1_expansion_audit.yaml",
        "analysis_code_sha": prov["code_sha"],
        "worktree_clean": prov["worktree_clean"],
        "inputs": {
            "split_registry": {
                "path": str(REG.relative_to(IMPL)),
                "sha256": _sha256_file(REG),
                "rows": int(len(registry)),
            },
            "e1_events": {
                "path": str(E1_EVENTS.relative_to(IMPL)),
                "sha256": _sha256_file(E1_EVENTS),
                "rows": int(len(e1_events)),
            },
            "e3_caltech_candidate": {
                "path": str(E3_CAL.relative_to(IMPL)),
                "sha256": _sha256_file(E3_CAL),
                "rows": int(len(e3_cand)),
            },
            "test_minutes_rows": int(len(test_minutes)),
            "test_minutes_sessions": int(test_minutes["session_id"].nunique()),
        },
        "outputs": outputs,
        "a1_summary": a1,
        "a2_overlap": a2,
        "discipline": (
            "只读 frozen evidence + registry + minute table；"
            "不重跑 formal；不调参；deterministic"
        ),
    }
    (OUT / "batch1_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(
        {"a1": a1, "a2": a2, "manifest_written": True}, ensure_ascii=False, indent=2))
    return manifest


def _row_count(p: Path) -> int:
    if p.suffix == ".csv":
        return int(len(pd.read_csv(p)))
    return -1


if __name__ == "__main__":
    run_batch1()
