"""JPL 外部边界分钟表 + current-only 保护回退统计（K1 冻结样本角色，2026-08-06）。

- 边界集：jpl 2020-06/07 matched 且 pilot-rich 会话 → datasets/lite_jpl_boundary_minute.parquet
- 回退集：jpl current-only matched 会话抽样 → 无 pilot 下功率衰减状态频率（不触响应效果差异）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.io.paths import acn_project_dir, resolve_static
from patent_preexperiment.io.static import read_static_csv
from patent_preexperiment.response.build_minutes import _to_ts
from patent_preexperiment.response.session import aggregate_session_minute

REPO = Path(__file__).resolve().parents[3]
IMPL = REPO / "patent_preexperiment"
CONFIG = IMPL / "configs" / "k1_preregister.yaml"
BOUNDARY_OUT = IMPL / "datasets" / "lite_jpl_boundary_minute.parquet"
FALLBACK_OUT = IMPL / "results" / "raw" / "E1L" / "current_only_fallback.json"
BOUNDARY_MONTHS = ["2020-06", "2020-07"]
FALLBACK_SAMPLE = 400


def select_boundary(cfg: dict) -> pd.DataFrame:
    s = cfg["sample_roles"]["external_boundary"]
    acn = acn_project_dir()
    idx = pd.read_csv(acn / "manifests" / "static_file_index.csv", dtype={"stationID": str, "file": str})
    mapf = pd.read_csv(acn / "manifests" / "static_api_mapping.csv", dtype={"stationID": str, "static_file": str})
    m = mapf[mapf["match_status"] == "matched"].copy()
    m["month"] = m["connection_time"].str[:7]
    m = m[(m["site_static"] == "jpl") & (m["month"].isin(BOUNDARY_MONTHS))].copy()
    m = m.drop(columns=["garage", "rows", "stationID"], errors="ignore")
    idx2 = idx[["file", "site", "garage", "stationID", "rows", "has_pilot", "has_power", "has_voltage"]]
    m = m.merge(idx2, left_on="static_file", right_on="file", how="inner")
    pilot_ok = m["has_pilot"] & (m["has_power"] | m["has_voltage"])
    m = m[pilot_ok].copy()
    api = pd.read_csv(acn / "manifests" / "api_metadata_index.csv", dtype={"stationID": str})
    m = m.merge(api[["sessionID", "disconnectTime", "doneChargingTime", "kWhDelivered"]], on="sessionID", how="left")
    return m


def build_boundary_minutes() -> pd.DataFrame:
    cfg = load_yaml(CONFIG)
    reg = select_boundary(cfg)
    rated_v = cfg["rated_voltage"]["jpl"]
    frames: list[pd.DataFrame] = []
    fails = 0
    for _, r in reg.iterrows():
        try:
            raw = read_static_csv(resolve_static(r["static_file"]))
            f = aggregate_session_minute(
                raw, rated_v,
                session_id=r["sessionID"], station_id=r["stationID"], site="jpl",
                garage=r["garage"], disconnect_time=_to_ts(r["disconnectTime"]),
                done_charging_time=_to_ts(r["doneChargingTime"]),
            )
            frames.append(f)
        except Exception:  # noqa: BLE001
            fails += 1
    df = pd.concat(frames, ignore_index=True)
    BOUNDARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(BOUNDARY_OUT, index=False)
    print(f"[boundary] sessions={df['session_id'].nunique()} rows={len(df)} parse_fails={fails}")
    return df


def current_only_fallback_metric() -> dict:
    """JPL current-only 会话的功率衰减状态频率（保护型回退，无 pilot 要求）。"""
    cfg = load_yaml(CONFIG)
    s = cfg["sample_roles"]["current_only_fallback"]
    acn = acn_project_dir()
    idx = pd.read_csv(acn / "manifests" / "static_file_index.csv", dtype={"stationID": str, "file": str})
    mapf = pd.read_csv(acn / "manifests" / "static_api_mapping.csv", dtype={"stationID": str, "static_file": str})
    api = pd.read_csv(acn / "manifests" / "api_metadata_index.csv", dtype={"stationID": str})
    m = mapf[mapf["match_status"] == "matched"].copy()
    m["month"] = m["connection_time"].str[:7]
    jpl = idx[(idx["site"] == "jpl") & (idx["has_pilot"] == False) & (idx["has_current"] == True)]  # noqa: E712
    m = m[(m["site_static"] == "jpl") & (m["static_file"].isin(set(jpl["file"])))].sample(
        min(FALLBACK_SAMPLE, len(m[(m["site_static"] == "jpl") & (m["static_file"].isin(set(jpl["file"])))])),
        random_state=7,
    )
    m = m.merge(api[["sessionID", "disconnectTime", "doneChargingTime"]], on="sessionID", how="left")
    rated_v = cfg["rated_voltage"]["jpl"]
    low_power_minutes = 0
    valid_minutes = 0
    sessions = 0
    idle_sessions = 0
    for _, r in m.iterrows():
        try:
            raw = read_static_csv(resolve_static(r["static_file"]))
        except Exception:  # noqa: BLE001
            continue
        raw = raw.dropna(subset=["current_a"]).copy()
        if raw.empty:
            continue
        raw["actual_power_kw"] = raw["current_a"] * rated_v / 1000.0
        raw["ts_min"] = pd.to_datetime(raw["timestamp"]).dt.floor("min")
        g = raw.groupby("ts_min")["actual_power_kw"].mean()
        sessions += 1
        n = len(g)
        if n < 10:
            continue
        first = g.index[0]
        ramp = (g.index - first).total_seconds() // 60 < 5
        disc = pd.Timestamp(r["disconnectTime"]) if pd.notna(r["disconnectTime"]) else g.index[-1]
        tail = (disc - g.index).total_seconds() / 60.0 <= 10
        valid = ~ramp & ~tail
        low = (g < 0.5) & valid
        low_power_minutes += int(low.sum())
        valid_minutes += int(valid.sum())
        if low.any():
            idle_sessions += 1
    result = {
        "role": "current_only_fallback",
        "sessions_sampled": sessions,
        "valid_minutes": valid_minutes,
        "low_power_minutes": low_power_minutes,
        "low_power_state_frequency": round(low_power_minutes / max(valid_minutes, 1), 6),
        "idle_sessions_share": round(idle_sessions / max(sessions, 1), 4),
        "note": "current-only 无 pilot：低功率状态频率为保护型回退可行性指标，不构成 E1 响应差证据",
    }
    FALLBACK_OUT.parent.mkdir(parents=True, exist_ok=True)
    FALLBACK_OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    build_boundary_minutes()
    current_only_fallback_metric()
    sys.exit(0)
