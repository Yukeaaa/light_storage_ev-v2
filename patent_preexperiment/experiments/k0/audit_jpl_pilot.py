"""JPL 2020 pilot 数据质量审计（纯输入数据质量，不触响应效果，V2.1 §5.2 冻结前）。

只统计：会话量、pilot 列值覆盖率、功率/电压可用率、会话时长分布、异常月份对照。
禁止输出任何 pilot-actual 差异 / 事件率等响应效果指标。
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pandas as pd

from patent_preexperiment.io.paths import acn_project_dir, resolve_static
from patent_preexperiment.io.static import read_static_csv

REPO = Path(__file__).resolve().parents[3]
IMPL = REPO / "patent_preexperiment"
OUT = IMPL / "results" / "raw" / "K0"
SEED = 7
SAMPLE_PER_MONTH = 30


def audit_jpl_pilot(max_samples: int = SAMPLE_PER_MONTH) -> dict:
    acn = acn_project_dir()
    idx = pd.read_csv(acn / "manifests" / "static_file_index.csv", dtype={"stationID": str, "file": str})
    api = pd.read_csv(acn / "manifests" / "api_metadata_index.csv", dtype={"stationID": str})
    mapf = pd.read_csv(acn / "manifests" / "static_api_mapping.csv", dtype={"stationID": str})

    jpl = idx[(idx["site"] == "jpl") & (idx["rows"] >= 10) & (idx["gzip_ok"]) & (idx["read_ok"])].copy()
    jpl["month"] = jpl["connection_time"].str[:7]

    matched = mapf[mapf["match_status"] == "matched"]
    matched_jpl = matched[matched["site_static"] == "jpl"] if "site_static" in matched.columns else matched
    m = matched_jpl.copy()
    m["month"] = m["connection_time"].str[:7]

    rng = random.Random(SEED)
    by_month: dict[str, dict] = {}
    for month, grp in jpl[jpl["month"].between("2020-01", "2020-12")].groupby("month"):
        pilot_files = grp[grp["has_pilot"]]
        sample = pilot_files if len(pilot_files) <= max_samples else pilot_files.sample(max_samples, random_state=SEED)
        pilot_val_rows = 0
        pilot_val_files = 0
        pwr_avail_rows = 0
        dur_min: list[float] = []
        for _, r in sample.iterrows():
            try:
                raw = read_static_csv(resolve_static(r["file"]))
            except Exception:  # noqa: BLE001
                continue
            pv = raw["pilot_a"].notna()
            pilot_val_files += 1 if pv.sum() > 0 else 0
            pilot_val_rows += int(pv.sum())
            pwr_avail_rows += int(raw["power_kw"].notna().sum())
            if len(raw) > 1:
                dur_min.append((raw["timestamp"].max() - raw["timestamp"].min()).total_seconds() / 60.0)
        n_matched = int(m[m["month"] == month].shape[0])
        by_month[month] = {
            "static_files": int(len(grp)),
            "pilot_col_files": int(len(pilot_files)),
            "sampled": int(len(sample)),
            "sampled_pilot_value_files": pilot_val_files,
            "sampled_pilot_value_ratio": round(pilot_val_files / max(len(sample), 1), 4),
            "sampled_pilot_row_coverage": round(pilot_val_rows / max(int(sample["rows"].sum()), 1), 4),
            "sampled_power_row_coverage": round(pwr_avail_rows / max(int(sample["rows"].sum()), 1), 4),
            "matched_sessions": n_matched,
            "sampled_median_duration_min": round(float(pd.Series(dur_min).median()) if dur_min else -1.0, 1),
        }

    abnormal = {"2019-12", "2020-02", "2020-04", "2020-12"}
    eligible = {
        mth: v for mth, v in by_month.items()
        if mth not in abnormal and v["matched_sessions"] >= 300
        and v["sampled_pilot_value_ratio"] >= 0.8
    }
    result = {
        "audit_scope": "input_quality_only_no_response_metrics",
        "seed": SEED,
        "by_month": by_month,
        "abnormal_months": sorted(abnormal),
        "eligible_months": sorted(eligible),
        "eligibility_rule": "matched_sessions>=300 and sampled_pilot_value_ratio>=0.8 and not abnormal",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "audit_jpl_pilot_quality.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    r = audit_jpl_pilot()
    print(json.dumps({k: r[k] for k in ("eligible_months", "by_month")}, ensure_ascii=False, indent=2))
    sys.exit(0)
