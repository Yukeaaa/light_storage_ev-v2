"""K0-04：K1 最小样本选择（V2.1 §5.2，规则冻结后读取测试结果）。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.io.paths import acn_project_dir

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "k1_preregister.yaml"


def _read(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    acn = acn_project_dir()
    idx = pd.read_csv(acn / "manifests" / "static_file_index.csv", dtype={"stationID": str, "file": str})
    mapf = pd.read_csv(acn / "manifests" / "static_api_mapping.csv", dtype={"stationID": str, "static_file": str})
    api = pd.read_csv(acn / "manifests" / "api_metadata_index.csv", dtype={"stationID": str})
    return idx, mapf, api


def _cluster_rank(df: pd.DataFrame, sites: list[str]) -> list[tuple[str, str, float]]:
    """站点内按 matched 会话数排序 garage，pilot 覆盖作 tie-break（冻结规则）。"""
    g = df.groupby(["site", "garage"]).agg(
        n_matched=("sessionID", "size"),
        pilot_ratio=("has_pilot", "mean"),
    )
    g = g.sort_values(["n_matched", "pilot_ratio"], ascending=False)
    return [(site, garage, row.n_matched) for (site, garage), row in g.iterrows() if site in sites]


def select_sample(cfg: dict | None = None) -> pd.DataFrame:
    cfg = cfg or load_yaml(CONFIG)
    s = cfg["sample"]
    idx, mapf, api = _read(cfg)

    idx = idx[idx["site"].isin(s["sites"])]
    idx = idx[idx["gzip_ok"] == True]  # noqa: E712
    idx = idx[idx["read_ok"] == True]  # noqa: E712
    idx = idx[idx["rows"] >= s["min_rows_per_file"]]

    m = mapf[mapf["match_status"] == "matched"].copy()
    m["month"] = m["connection_time"].str[:7]
    idx2 = idx[["file", "site", "garage", "stationID", "rows", "has_pilot", "has_power", "has_voltage"]]
    m = m.drop(columns=["garage", "rows", "stationID"], errors="ignore")
    m = m.merge(idx2, left_on="static_file", right_on="file", how="inner")

    ranked = _cluster_rank(m, s["sites"])
    keep: set[tuple[str, str]] = set()
    for site in s["sites"]:
        cnt = 0
        for st, ga, _ in ranked:
            if st != site:
                continue
            if cnt >= s["clusters_per_site"]:
                break
            keep.add((st, ga))
            cnt += 1
    m = m[[(r.site, r.garage) in keep for r in m.itertuples()]]

    excl = set(s["exclude_months"])
    m = m[~m["month"].isin(excl)]
    month_tot = m.groupby("month").size().sort_values(ascending=False)
    top_months = sorted(month_tot.head(s["n_months"]).index.tolist())
    m = m[m["month"].isin(top_months)]

    api_cols = ["sessionID", "disconnectTime", "doneChargingTime", "kWhDelivered"]
    m = m.merge(api[api_cols], on="sessionID", how="left")

    m["sample_role"] = "E3_pool"
    pilot_ok = m["has_pilot"] & (m["has_power"] | m["has_voltage"])
    m.loc[pilot_ok, "sample_role"] = "E1_pilot_rich_and_E3_pool"
    out = m[["site", "garage", "stationID", "connection_time", "static_file", "sessionID", "rows",
             "has_pilot", "has_power", "has_voltage", "month", "disconnectTime", "doneChargingTime",
             "kWhDelivered", "sample_role"]].copy()
    return out


def build_sample_registry(out: str | Path) -> dict:
    cfg = load_yaml(CONFIG)
    reg = select_sample(cfg)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    reg.to_csv(out, index=False)
    summary = {
        "selected_clusters": sorted(reg[["site", "garage"]].drop_duplicates().values.tolist()),
        "selected_months": sorted(reg["month"].unique().tolist()),
        "n_matched_sessions": int(len(reg)),
        "n_pilot_rich_sessions": int((reg["sample_role"] == "E1_pilot_rich_and_E3_pool").sum()),
        "n_stations": int(reg["stationID"].nunique()),
        "sessions_per_cluster_month": {
            f"{k[0]}/{k[1]}/{k[2]}": int(v) for k, v in reg.groupby(["site", "garage", "month"]).size().items()
        },
    }
    side = str(out).replace("k1_sample_registry.csv", "k1_sample_summary.json")
    Path(side).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    import sys

    cfg = load_yaml(CONFIG)
    print(json.dumps(build_sample_registry(Path(__file__).resolve().parents[3] / "data_registry" / "k1_sample_registry.csv"), ensure_ascii=False, indent=2))
    sys.exit(0)
