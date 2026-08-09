"""E0F-05 数据链验收审计器（D0）：对 E0F-01..04 冻结产物做只读验收审计。

审查结论 14（E0F-05）：在测试集冻结后、进入 E0F-06/R1 前，对所有已冻结产物
运行 10 个验收门，任何一门不通过则 STOP（不更新 baseline、不得进入 E0F-06/R1）：

  1. input_traceability    输入可追溯（manifest/源码哈希与 baseline 一致）
  2. output_traceability   输出可追溯（baseline output_manifest 全部存在）
  3. uniqueness            会话分钟主键全局唯一（分区路径/治理/覆盖三腿）
  4. completeness          数据覆盖与字段覆盖完整（期望值由 sha 冻结的 manifest/
                           baseline 推导，不写死 magic number）
  5. energy_consistency    能量一致性分层审计（site×月×split×field_mode）
  6. gold_consistency      gold 池一致性（per-pool gate + 月度集中度 + 加权 total）
  7. split_safety          切分安全（值域/单会话单 split/外部应力隔离/60-20-20 +
                           复用 E0F-02 assign_split 重算会话级分配，mismatch=0）
  8. leak_safety           泄漏安全（实际产物列不得命中在线禁止特征）
  9. determinism           确定性（含 pool_state_1min/5min 实际 parquet 逐位核验）
 10. evaluable_aggregation evaluable 机制核查（不发明样本量数值门限）

语义护栏：
  - pilot_coverage==0 行：pilot_upper_kw_total 必须为 0，且 0 不得解释为
    "真实 pilot=0"（无导引可用 ≠ 允许电流为 0）。硬护栏（FAIL 即 STOP）。
  - 5min 池表：报告每桶 n_minutes_observed / complete_5min 审计，R1 不得把
    不完整桶当作完整控制周期。仅报告（不完整桶是自然边界状态）。

数据口径（AGENTS.md / V2.0 §4.3）：
  - 门线用原始中位，round 只用于显示；caltech/office001 中位 |dev| >=
    tolerance 即 FAIL（等值也 FAIL）。
  - jpl 聚合可用、会话级离群另报（不做门）；不删除高偏差会话。
  - 测试集冻结后不逐图调参；失败即 STOP，需新版本 + 新测试协议。

D0 只读：不写任何 data_registry/数据集产物，唯一写的是自身报告与
d0_registry.json（两者都会进入 git 与 baseline output_manifest）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
import yaml

from patent_preexperiment.e0_full import pool_state, session_response
from patent_preexperiment.e0_full.baseline import _git_commit, _git_dirty_code, _sha256
from patent_preexperiment.e0_full.input_audit import manifest_hash
from patent_preexperiment.e0_full.split import assign_split
from patent_preexperiment.io.paths import acn_project_dir

_REPO_ROOT = Path(__file__).resolve().parents[4]
_IMPL_ROOT = Path(__file__).resolve().parents[3]

GATE_NAMES = (
    "input_traceability",
    "output_traceability",
    "uniqueness",
    "completeness",
    "energy_consistency",
    "gold_consistency",
    "split_safety",
    "leak_safety",
    "determinism",
    "evaluable_aggregation",
)

# 各门输出相对 impl root 的固定产物路径（用于 output_traceability/determinism）
_REGISTRY_PATHS = {
    "source_manifest": "data_registry/e0_full_source_manifest.parquet",
    "quality_summary": "data_registry/e0_full_quality_summary.json",
    "split_registry": "data_registry/e0_full_split_registry.parquet",
    "field_mode_registry": "data_registry/e0_full_field_mode_registry.parquet",
    "session_response_partitions": "data_registry/e0_full_session_response_partitions.json",
    "pool_registry": "data_registry/pool_registry.csv",
    "pool_state_registry": "data_registry/e0_full_pool_state_registry.json",
    "baseline": "data_registry/e0_full_baseline.json",
}

_D0_REPORT = "reports/E0_Full_D0_acceptance_audit.md"
_D0_REGISTRY = "data_registry/e0_full_d0_registry.json"

# 语义护栏中：FAIL 必须导致 D0 STOP 的硬护栏。pilot_zero 违背会污染 E2/R1
# 的"无导引可用 vs 真实 pilot=0"语义，必须 STOP；cycle 的不完整桶是自然边界
# 状态（2026-08 真实数据约 0.99%），只报告不 STOP。
HARD_SEMANTIC_GUARDS = ("pilot_zero",)


def _hard_semantic_failed(semantic: dict[str, Any]) -> list[str]:
    """硬语义护栏中 FAIL 的名单（审查结论23 P0-2：护栏 FAIL 必须让 D0 STOP）。"""
    return [
        name
        for name, g in semantic.items()
        if not g["pass"] and name in HARD_SEMANTIC_GUARDS
    ]


def _load_cfg() -> dict[str, Any]:
    with open(_IMPL_ROOT / "configs" / "e0_full.yaml", encoding="utf-8") as fh:
        return cast(dict[str, Any], yaml.safe_load(fh))


def _load_baseline() -> dict[str, Any]:
    p = _IMPL_ROOT / _REGISTRY_PATHS["baseline"]
    return cast(dict[str, Any], json.loads(p.read_text(encoding="utf-8")))


def _load_registry(path: str) -> pd.DataFrame:
    return pd.read_parquet(_IMPL_ROOT / path)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _partition_scan(
    out_dir: Path,
    registry: pd.DataFrame,
    frozen_parts: dict[str, Any] | None,
) -> dict[str, Any]:
    """对 session_response_1min 最终分区做单遍扫描，返回 D0 可机器核对的证据。

    - 每个分区：sha256 vs 冻结分区注册表、路径一致性、行治理列 == E0F-02 registry、
      分区内 [session_id, timestamp_utc] 重复计数、行数。
    - 覆盖集与孤儿/缺失会话集合。
    - 逐会话能量累积（integral / energy span / API kWh，与 E0F-03 同口径）。
    """
    gov = session_response._session_governance_index(registry)
    frozen: dict[tuple[str, int, int], str] = {}
    if frozen_parts:
        frozen = {
            (p["site"], int(p["year"]), int(p["month"])): p["sha256"]
            for p in frozen_parts.get("partitions", [])
        }

    files = sorted(out_dir.glob("site=*/year=*/month=*/data.parquet"))
    per_partition: list[dict[str, Any]] = []
    covered: set[str] = set()
    accs: dict[str, dict[str, Any]] = {}
    n_dup = 0
    n_rows = 0
    path_failures: list[str] = []
    gov_failures: list[str] = []

    for f in files:
        rel = f.relative_to(out_dir)
        site = rel.parts[0].split("=", 1)[1]
        year = int(rel.parts[1].split("=", 1)[1])
        month = int(rel.parts[2].split("=", 1)[1])
        df = pd.read_parquet(f, columns=list(session_response._GOVERNANCE_COLUMNS) + [
            "session_id", "timestamp_utc", "actual_power_kw", "energy_cum_kwh",
            "kwh_delivered", "energy_source",
        ])
        try:
            session_response._assert_partition_path_consistent(
                df, site, year, month, "D0"
            )
        except RuntimeError as exc:
            path_failures.append(str(exc))
        try:
            session_response._assert_session_governance(df, gov, f, "D0")
        except RuntimeError as exc:
            gov_failures.append(str(exc))
        n_dup += int(df.duplicated(subset=["session_id", "timestamp_utc"]).sum())
        n_rows += int(len(df))
        sids = df["session_id"].astype(str)
        covered.update(sids.unique())
        for sid, g in df.groupby("session_id", sort=False):
            a = accs.setdefault(
                str(sid),
                {
                    "session_id": str(sid),
                    "site": str(g["site"].iloc[0]),
                    "match_status": str(g["match_status"].iloc[0]),
                    "has_energy": str(g["energy_source"].iloc[0]) == "raw",
                    "n_minutes": 0,
                    "integral_kwh": 0.0,
                    "energy_first": None,
                    "energy_last": None,
                    "ref_api_kwh": float(g["kwh_delivered"].iloc[0])
                    if pd.notna(g["kwh_delivered"].iloc[0])
                    else None,
                },
            )
            a["n_minutes"] += int(len(g))
            a["integral_kwh"] += float(g["actual_power_kw"].sum() / 60.0)
            e = g["energy_cum_kwh"].dropna()
            if not e.empty:
                if a["energy_first"] is None:
                    a["energy_first"] = float(e.iloc[0])
                m = float(e.max())
                a["energy_last"] = m if a["energy_last"] is None else max(a["energy_last"], m)
        per_partition.append(
            {
                "site": site,
                "year": year,
                "month": month,
                "rows": int(len(df)),
                "sha256": _sha256_file(f),
                "sha_matches_frozen": _sha256_file(f) == frozen.get((site, year, month)),
            }
        )

    registry_sids = set(registry["session_id"].astype(str))
    return {
        "n_files": len(files),
        "n_rows": n_rows,
        "n_sessions_covered": len(covered),
        "covered": covered,
        "orphan_sessions": sorted(covered - registry_sids),
        "missing_sessions": sorted(registry_sids - covered),
        "duplicate_key_rows": int(n_dup),
        "path_failures": path_failures,
        "governance_failures": gov_failures,
        "per_partition": per_partition,
        "session_energy_audits": [accs[sid] for sid in sorted(accs)],
    }


def audit_input_traceability(cfg: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """输入可追溯：三个源 manifest 文件哈希 + source manifest 确定性哈希。

    code_sha 记录为 provenance 证据（不入门线）：D0 在 E0F-04 之后的提交上运行，
    HEAD 与 baseline.code_sha 不同属正常；冻结产物的完整性由 determinism 门的
    产物 sha 核对保证。manifest 文件 sha 与 source_manifest 确定性哈希必须逐位一致。
    """
    acn = acn_project_dir()
    problems: list[str] = []
    manifest_ok: dict[str, Any] = {}
    for name, expected in baseline["manifest_hashes"].items():
        p = acn / "manifests" / name
        if not p.exists():
            problems.append(f"{name}: 文件缺失")
            manifest_ok[name] = False
            continue
        sha = _sha256_file(p)
        manifest_ok[name] = {
            "sha256": sha,
            "matches_baseline": sha == expected["sha256"],
        }
        if sha != expected["sha256"]:
            problems.append(f"{name}: sha256 与 baseline 不一致")
    src = _IMPL_ROOT / _REGISTRY_PATHS["source_manifest"]
    src_hash = manifest_hash(pd.read_parquet(src))
    if src_hash != baseline["source_manifest_sha256"]:
        problems.append("e0_full_source_manifest.parquet 确定性哈希与 baseline 不一致")
    code_sha = _git_commit()
    return {
        "pass": not problems,
        "evidence": {
            "manifest_hashes": manifest_ok,
            "source_manifest_sha256": src_hash,
            "source_manifest_matches_baseline": src_hash == baseline["source_manifest_sha256"],
            "code_sha": code_sha,
            "baseline_code_sha": baseline["code_sha"],
            "code_sha_matches_baseline": code_sha == baseline["code_sha"],
            "code_sha_note": "provenance only; artifact integrity gated by determinism",
        },
        "worst": problems,
    }


def audit_output_traceability(baseline: dict[str, Any]) -> dict[str, Any]:
    """输出可追溯：baseline output_manifest 每条路径都必须存在（相对 impl root）。"""
    missing = [p for p in baseline["output_manifest"] if not (_IMPL_ROOT / p).exists()]
    return {
        "pass": not missing,
        "evidence": {"n_manifest_paths": len(baseline["output_manifest"])},
        "worst": missing,
    }


def audit_uniqueness(
    scan: dict[str, Any],
    frozen_parts: dict[str, Any],
) -> dict[str, Any]:
    """会话分钟主键全局唯一：分区内无重复 + 路径一致 + 治理一致 + 无孤儿/缺失。"""
    sha_mismatch = [
        p for p in scan["per_partition"] if not p["sha_matches_frozen"]
    ]
    missing_sha = [
        f"{p['site']}/{p['year']}-{p['month']:02d}"
        for p in frozen_parts.get("partitions", [])
        if not any(
            q["site"] == p["site"] and q["year"] == p["year"] and q["month"] == p["month"]
            for q in scan["per_partition"]
        )
    ]
    problems = []
    if scan["duplicate_key_rows"]:
        problems.append(f"分区内 [session_id, timestamp_utc] 重复 {scan['duplicate_key_rows']} 行")
    if scan["orphan_sessions"]:
        problems.append(
            f"孤儿会话 {len(scan['orphan_sessions'])} 个（在分区但不在 E0F-02 registry）"
        )
    if scan["missing_sessions"]:
        problems.append(
            f"缺失会话 {len(scan['missing_sessions'])} 个（在 registry 但无分区）"
        )
    if scan["path_failures"]:
        problems.append(f"分区路径不一致 {len(scan['path_failures'])} 处")
    if scan["governance_failures"]:
        problems.append(f"行治理列与 registry 不一致 {len(scan['governance_failures'])} 处")
    if sha_mismatch:
        problems.append(f"分区文件 sha256 与冻结注册表不一致 {len(sha_mismatch)} 个")
    if missing_sha:
        problems.append(f"冻结注册表记录的分区文件缺失 {len(missing_sha)} 个：{missing_sha[:3]}")
    return {
        "pass": not problems,
        "evidence": {
            "n_files": scan["n_files"],
            "n_rows": scan["n_rows"],
            "n_sessions_covered": scan["n_sessions_covered"],
            "duplicate_key_rows": scan["duplicate_key_rows"],
            "orphan_sessions": len(scan["orphan_sessions"]),
            "missing_sessions": len(scan["missing_sessions"]),
            "path_failures": len(scan["path_failures"]),
            "governance_failures": len(scan["governance_failures"]),
            "sha_mismatch": len(sha_mismatch),
            "frozen_partitions_missing_files": len(missing_sha),
        },
        "worst": problems[:8],
    }


def _energy_layer_stats(g: pd.DataFrame) -> dict[str, Any]:
    ok = g["dev_energy"].notna()
    if not ok.any():
        return {
            "n_sessions": int(len(g)),
            "n_evaluable": 0,
            "median_abs_dev": None,
            "n_outliers_gt_20pct": 0,
            "share_outliers_gt_20pct": None,
            "bucket": None,
        }
    dev = g.loc[ok, "dev_energy"].abs()
    med = float(dev.median())
    n_out = int((dev > 0.20).sum())
    bucket = "le_5pct" if med <= 0.05 else ("5_20pct" if med <= 0.20 else "gt_20pct")
    return {
        "n_sessions": int(len(g)),
        "n_evaluable": int(ok.sum()),
        "median_abs_dev": round(med, 6),
        "n_outliers_gt_20pct": n_out,
        "share_outliers_gt_20pct": round(float(n_out / max(ok.sum(), 1)), 4),
        "bucket": bucket,
    }


def audit_energy_layered(
    scan: dict[str, Any],
    registry: pd.DataFrame,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """能量一致性分层审计（审查结论 14 重点 1）。

    分层粒度 site × 连接月份 × split × field_mode；桶分级 ≤5% / 5–20% / >20%。
    门线：caltech/office001 会话级中位 |dev_energy| < tolerance_median_dev（原始值，
    等值即 FAIL）。jpl 聚合可用、会话级离群另报，不做门；不删除高偏差会话。
    特别关注 test split 与冻结 K1 月份分层。
    """
    audits = pd.DataFrame(scan["session_energy_audits"])
    if audits.empty:
        return {"pass": True, "evidence": {}, "worst": []}
    reg = registry.set_index("session_id")
    conn_month = (
        pd.to_datetime(reg["connection_time"], errors="coerce")
        .dt.strftime("%Y-%m").fillna("unknown").to_dict()
    )
    audits["split"] = audits["session_id"].map(reg["split"])
    audits["field_mode"] = audits["session_id"].map(reg["field_mode"])
    audits["conn_month"] = audits["session_id"].map(conn_month)
    has = audits[audits["has_energy"]].copy()
    has["energy_span"] = has["energy_last"] - has["energy_first"]
    has["dev_energy"] = (
        (has["integral_kwh"] - has["energy_span"])
        / has["energy_span"].replace(0, float("nan"))
    )
    tolerance = float(cfg["session_response"]["energy_consistency"]["tolerance_median_dev"])

    by_site: dict[str, Any] = {}
    stop_hits: list[str] = []
    for site in ("caltech", "jpl", "office001"):
        g = has[has["site"] == site]
        if g.empty:
            continue
        ok = g["dev_energy"].notna()
        med = float(g.loc[ok, "dev_energy"].abs().median()) if ok.any() else float("nan")
        by_site[site] = {
            "sessions": int(len(g)),
            "n_evaluable": int(ok.sum()),
            "median_abs_dev": med,
            "p95_abs_dev": float(g.loc[ok, "dev_energy"].abs().quantile(0.95))
            if ok.any()
            else None,
            "n_outliers_gt_20pct": int((g.loc[ok, "dev_energy"].abs() > 0.20).sum())
            if ok.any()
            else 0,
        }
        if site in ("caltech", "office001") and med >= tolerance:
            stop_hits.append(
                f"{site} 中位 |dev|={med:.6f} >= {tolerance}（冻结 tolerance_median_dev）"
            )

    layers: list[dict[str, Any]] = []
    if not has.empty:
        for key, g in has.groupby(
            ["site", "conn_month", "split", "field_mode"], sort=True
        ):
            st = _energy_layer_stats(g)
            layers.append(
                {
                    "site": key[0],
                    "month": key[1],
                    "split": key[2],
                    "field_mode": key[3],
                    **st,
                }
            )
    layer_df = pd.DataFrame(layers) if layers else pd.DataFrame()
    worst_all = _worst_layer(layer_df)
    worst_test = _worst_layer(
        layer_df[layer_df["split"] == "test"] if not layer_df.empty else layer_df
    )
    k1_months = {
        m for months in cfg["k1_role_months"].values() for m in months
    }
    worst_k1 = _worst_layer(
        layer_df[layer_df["month"].isin(k1_months)] if not layer_df.empty else layer_df
    )

    return {
        "pass": not stop_hits,
        "evidence": {
            "by_site": by_site,
            "layers": layers,
            "n_layers": len(layers),
            "bucket_counts": _bucket_counts(layer_df),
            "worst_all": worst_all,
            "worst_test": worst_test,
            "worst_k1_months": worst_k1,
            "k1_months_frozen": sorted(k1_months),
            "tolerance_median_dev": tolerance,
        },
        "worst": stop_hits,
    }


def _worst_layer(layer_df: pd.DataFrame) -> dict[str, Any] | None:
    if layer_df is None or layer_df.empty or "share_outliers_gt_20pct" not in layer_df:
        return None
    idx = layer_df["share_outliers_gt_20pct"].fillna(-1.0).idxmax()
    return cast(dict[str, Any], layer_df.loc[idx].to_dict())


def _bucket_counts(layer_df: pd.DataFrame) -> dict[str, int]:
    if layer_df is None or layer_df.empty:
        return {"le_5pct": 0, "5_20pct": 0, "gt_20pct": 0}
    counts: dict[Any, int] = {
        str(k): int(v) for k, v in layer_df["bucket"].value_counts(dropna=False).items()
    }
    return {b: counts.get(b, 0) for b in ("le_5pct", "5_20pct", "gt_20pct")}


def audit_gold_layered(
    pool_registry: pd.DataFrame,
    pool_5min: pd.DataFrame,
    cfg: dict[str, Any],
    gold_dir: Path | None = None,
) -> dict[str, Any]:
    """gold 一致性：per-pool gate（中位 |rel dev| < tolerance，机器核对）+ 月度集中度。

    审查结论 14 重点 2：JPL gold 敏感度（综合 -6.33%、p95 |rel dev| 14.26%）保留，
    并解释时间/月份集中度——输出每个池的月度 rel dev 表与最差月份。
    gold_dir 可注入（测试用临时目录），默认 acn_project/gold。
    """
    if gold_dir is None:
        gold_dir = acn_project_dir() / "gold"
    gc = pool_state.gold_consistency(pool_registry, gold_dir, cfg, pool_5min)
    gold_pools = [p["site"] + "__" + p["garage"] for p in cfg["pool"]["gold"]["pools"]]
    monthly: dict[str, Any] = {}
    for pid in gold_pools:
        gold = pool_state._read_gold_pool(gold_dir, pid, pool_registry)
        gold["month"] = gold["bucket_utc"].dt.strftime("%Y-%m")
        gold_g = gold.groupby("month")["energy_kwh"].sum().rename("gold")
        ours = pool_5min[pool_5min["pool_id"] == pid].copy()
        ours["bucket_utc"] = ours["timestamp_utc"].dt.floor("5min")
        ours["energy_kwh"] = ours["measured_kwh"] + ours["estimated_kwh"]
        ours["month"] = ours["bucket_utc"].dt.strftime("%Y-%m")
        ours_g = ours.groupby("month")["energy_kwh"].sum().rename("ours")
        m = pd.concat([gold_g, ours_g], axis=1).fillna(0.0)
        m = m[m["gold"] > 1e-9]
        if m.empty:
            monthly[pid] = {"months": [], "worst": None, "total_median_abs": None}
            continue
        dev = (m["ours"] - m["gold"]) / m["gold"]
        worst = dev.abs().idxmax()
        months_rows = []
        for mm, row in m.iterrows():
            d = float(dev.loc[mm])
            months_rows.append(
                {
                    "month": mm,
                    "gold_kwh": round(float(row["gold"]), 3),
                    "ours_kwh": round(float(row["ours"]), 3),
                    "rel_dev": round(d, 6),
                    "abs_rel_dev": round(abs(d), 6),
                }
            )
        monthly[pid] = {
            "months": months_rows,
            "worst_month": str(worst),
            "worst_abs_rel_dev": round(float(dev.abs().loc[worst]), 6),
            "total_rel_dev": round(
                float((m["ours"].sum() - m["gold"].sum()) / m["gold"].sum()), 6
            ),
            "monthly_mean_rel_dev": round(float(dev.mean()), 6),
            "total_gold_kwh": round(float(m["gold"].sum()), 3),
            "total_ours_kwh": round(float(m["ours"].sum()), 3),
        }
    return {
        "pass": gc["gold_consistency"],
        "evidence": {
            "per_pool": gc["per_pool"],
            "tolerance": gc["tolerance"],
            "monthly_per_pool": monthly,
        },
        "worst": [
            f"{pid}: 最差月 {v['worst_month']} |rel dev|={v['worst_abs_rel_dev']}"
            for pid, v in monthly.items()
            if v.get("worst_month")
        ],
    }


def audit_completeness(
    quality: dict[str, Any],
    scan: dict[str, Any],
    cfg: dict[str, Any],
    baseline: dict[str, Any],
    manifest: pd.DataFrame,
) -> dict[str, Any]:
    """数据/字段覆盖完整性：quality_summary 关键不变式 + 分区统计 + 覆盖口径。

    期望值一律由 sha 冻结的 source manifest（determinism 门已核验其 sha 与
    baseline.source_manifest_sha256 一致）与 baseline 推导，不写死 magic number，
    避免"数据版本更新、代码常量忘改"。
    """
    problems: list[str] = []
    expected_files = int(len(manifest))
    expected_rows = int(manifest["rows"].sum())
    if quality.get("files_total") != expected_files:
        problems.append(f"files_total={quality.get('files_total')} != manifest {expected_files}")
    if quality.get("rows_total") != expected_rows:
        problems.append(f"rows_total={quality.get('rows_total')} != manifest Σrows {expected_rows}")
    if quality.get("read_fail", 0) != 0:
        problems.append(f"read_fail={quality.get('read_fail')} != 0")
    coverage = quality.get("coverage", {})
    for field in ("current", "pilot", "state", "power"):
        n = int(manifest[f"has_{field}"].sum())
        expected_ratio = round(n / max(expected_files, 1), 4)
        got = coverage.get(field, {}).get("ratio")
        if got is None or abs(float(got) - expected_ratio) > 1e-4:
            problems.append(
                f"coverage.{field}.ratio={got} 偏离 manifest 推导值 {expected_ratio}"
            )
    by_site = quality.get("by_site", {})
    jpl = manifest[manifest["site"] == "jpl"]
    expected_jpl_est = int((jpl["has_current"] & ~jpl["has_voltage"]).sum())
    jpl_est = by_site.get("jpl", {}).get("estimated_current_only")
    if jpl_est != expected_jpl_est:
        problems.append(
            f"jpl estimated_current_only={jpl_est} != manifest 推导 {expected_jpl_est}"
            "（current-only 回退必备路径）"
        )
    sr = baseline.get("session_response", {}).get("partition_registry", {})
    expected_sr_rows = sr.get("n_rows")
    expected_sr_sessions = sr.get("n_sessions")
    if expected_sr_rows is not None and scan["n_rows"] != expected_sr_rows:
        problems.append(
            f"session_response n_rows={scan['n_rows']} != baseline {expected_sr_rows}"
        )
    if expected_sr_sessions is not None and scan["n_sessions_covered"] != expected_sr_sessions:
        problems.append(
            f"covered 会话数={scan['n_sessions_covered']} != baseline {expected_sr_sessions}"
        )
    return {
        "pass": not problems,
        "evidence": {
            "quality_summary": {
                k: quality[k] for k in ("files_total", "rows_total", "read_fail")
                if k in quality
            },
            "expected_derived_from": {
                "files_total": expected_files,
                "rows_total": expected_rows,
                "session_response_n_rows": expected_sr_rows,
                "session_response_n_sessions": expected_sr_sessions,
            },
            "session_partitions": {
                "n_files": scan["n_files"],
                "n_rows": scan["n_rows"],
                "n_sessions_covered": scan["n_sessions_covered"],
            },
        },
        "worst": problems[:8],
    }


def _recompute_split_assignment(registry: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """复用 E0F-02 生产切分实现 assign_split，重算会话级 split 并与冻结 registry 比对。

    返回 (expected, mismatch_count)。用 registry 的 site_canonical /
    connection_time_canonical / external / stress 重建 assign_split 输入，
    assign_split 内部按 (connection_time, session_id) 排序后 60/20/20。
    只查比例不查顺序会漏掉"未来会话进 train / 早期会话进 test"的造假，
    mismatch=0 才证明冻结切分正是时间顺序切出来的。
    """
    sessions = pd.DataFrame(
        {
            "session_id": registry["session_id"],
            "site": registry["site_canonical"]
            if "site_canonical" in registry.columns
            else registry["site"],
            "connection_time": registry["connection_time_canonical"]
            if "connection_time_canonical" in registry.columns
            else registry["connection_time"],
            "is_external": registry["external"].astype(bool),
            "is_stress": registry["stress"].astype(bool),
        }
    )
    expected = assign_split(sessions)
    expected_split = cast(pd.Series, expected["split"]).reset_index(drop=True)
    actual = cast(pd.Series, registry["split"]).reset_index(drop=True)
    mismatch = int((expected_split != actual).sum())
    return expected, mismatch


def audit_split_safety(registry: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    """切分安全：值域、单会话单 split、外部/应力隔离、60/20/20、时间顺序重算。"""
    problems: list[str] = []
    evid: dict[str, Any] = {}
    for col, allowed in (
        ("split", {"train", "validation", "test", "external", "stress"}),
        ("field_mode", {"measured_pilot", "measured_no_pilot", "computed_pilot",
                        "computed_no_pilot", "current_only"}),
        ("role", {"main", "boundary", "current_only_fallback", "external_only"}),
        ("sample_layer", {"L1_strict_matched", "L0_static_extension"}),
        ("match_status", {"matched", "static_only"}),
    ):
        bad = set(registry[col].dropna().unique()) - allowed
        if bad:
            problems.append(f"{col} 出现冻结值域外取值：{sorted(bad)}")
        evid[col] = sorted(registry[col].dropna().unique().tolist())

    if registry["session_id"].duplicated().any():
        problems.append("session_id 重复（单会话必须单 split）")

    ext_stress = registry[registry["split"].isin(["external", "stress"])]
    flags_present = {"external": "external" in registry.columns,
                     "stress": "stress" in registry.columns}
    if flags_present["external"] and flags_present["stress"]:
        leaked = registry[
            registry["split"].isin(["train", "validation", "test"]) & (
                registry["external"].fillna(False) | registry["stress"].fillna(False)
            )
        ]
        if not leaked.empty:
            problems.append(f"主 split 中混入 external/stress 会话 {len(leaked)} 个")
    else:
        problems.append(f"registry 缺 external/stress 列：{flags_present}")
    if ext_stress.empty:
        problems.append("registry 缺少 external/stress 会话（外部验证/应力切分缺失）")

    main = registry[registry["split"].isin(["train", "validation", "test"])]
    by_site = {}
    for site, g in main.groupby("site"):
        n = len(g)
        ratios = {
            s: round(float((g["split"] == s).sum() / n), 4) for s in ("train", "validation", "test")
        }
        by_site[site] = {"n": n, "ratios": ratios}
        if not (0.55 <= ratios["train"] <= 0.65):
            problems.append(f"{site} train 占比 {ratios['train']} 偏离 60%±5%")
        if not (0.18 <= ratios["validation"] <= 0.22):
            problems.append(f"{site} validation 占比 {ratios['validation']} 偏离 20%±2%")
        if not (0.18 <= ratios["test"] <= 0.22):
            problems.append(f"{site} test 占比 {ratios['test']} 偏离 20%±2%")
    evid["per_site_602020"] = by_site
    evid["n_main"] = int(len(main))
    evid["n_external_stress"] = int(len(ext_stress))

    expected, mismatch = _recompute_split_assignment(registry)
    split_rule = cfg.get("split", {})
    if mismatch:
        problems.append(
            f"冻结 split 与时间顺序重算不一致 {mismatch} 个会话"
            "（未来会话进 train / 早期会话进 test 等造假如有，此处必命中）"
        )
    evid["recomputed_split"] = {
        "n_recomputed": int(len(registry)),
        "split_assignment_mismatch": int(mismatch),
        "rule": split_rule.get("rule", ""),
        "rule_version": split_rule.get("rule_version", ""),
    }

    return {
        "pass": not problems,
        "evidence": evid,
        "worst": problems[:8],
    }


def audit_leak_safety(
    scan: dict[str, Any],
    pool_1min: pd.DataFrame,
    pool_5min: pd.DataFrame,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """泄漏安全：实际产物列不得命中在线禁止特征（离线标签列除外）。"""
    with open(_IMPL_ROOT / "configs" / "forbidden_features.yaml", encoding="utf-8") as fh:
        forbidden = set(yaml.safe_load(fh)["forbidden_features"])
    offline = set(cfg["session_response"]["offline_labels"])
    schema = json.loads(
        (_IMPL_ROOT / "data_registry" / "e0_full_session_response_1min.schema.json")
        .read_text(encoding="utf-8")
    )
    session_cols = set(schema["columns"]) | set(schema.get("unique_columns", []))
    hit_cols: set[str] = set()
    for frame_cols in (session_cols, set(pool_1min.columns), set(pool_5min.columns)):
        for col in frame_cols:
            if col in forbidden and col not in offline:
                hit_cols.add(col)
    return {
        "pass": not hit_cols,
        "evidence": {
            "n_forbidden": len(forbidden),
            "offline_labels_exempt": sorted(offline),
            "forbidden_hits_in_products": sorted(hit_cols),
        },
        "worst": sorted(hit_cols)[:8],
    }


def _verify_pool_state_files(
    frozen: dict[str, Any],
    pool_1min_dir: Path,
    pool_5min_file: Path,
) -> tuple[dict[str, Any], list[str]]:
    """对 E0F-04 冻结 pool_state registry 与实际 parquet 做逐位核验（审查结论23 P0-1）。

    返回 (evidence, problems)。registry 只哈希了 e0_full_pool_state_registry.json 本身，
    必须同时核验 registry 指向的实际 parquet，否则"registry hash 对、数据已改"会漏判：
    - pool_state_1min：期望分区路径集合 == 实际集合（缺/多分区均拦）；
      每个实际分区 sha256 == 冻结 sha256、rows == 冻结 rows；总行数 == 冻结 n_rows。
    - pool_state_5min：文件存在、sha256 == 冻结 sha256、n_rows == 冻结 n_rows。
    """
    problems: list[str] = []
    frozen_1min = frozen.get("pool_state_1min", {}) or {}
    frozen_parts = frozen_1min.get("partitions", []) or []
    frozen_map: dict[tuple[str, int, int], dict[str, Any]] = {
        (p["site"], int(p["year"]), int(p["month"])): p for p in frozen_parts
    }
    expected_set = set(frozen_map)

    actual_files = sorted(pool_1min_dir.glob("site=*/year=*/month=*/data.parquet"))
    actual_keys: set[tuple[str, int, int]] = set()
    actual_rows = 0
    for f in actual_files:
        rel = f.relative_to(pool_1min_dir)
        key = (
            rel.parts[0].split("=", 1)[1],
            int(rel.parts[1].split("=", 1)[1]),
            int(rel.parts[2].split("=", 1)[1]),
        )
        actual_keys.add(key)
        n = len(pd.read_parquet(f, columns=["pool_id"]))
        actual_rows += n

    missing = expected_set - actual_keys
    extra = actual_keys - expected_set
    if missing:
        problems.append(f"pool_state_1min 缺 {len(missing)} 个冻结分区：{sorted(missing)[:5]}")
    if extra:
        problems.append(f"pool_state_1min 多出 {len(extra)} 个未冻结分区：{sorted(extra)[:5]}")

    sha_mismatch: list[str] = []
    rows_mismatch: list[str] = []
    for f in actual_files:
        rel = f.relative_to(pool_1min_dir)
        key = (
            rel.parts[0].split("=", 1)[1],
            int(rel.parts[1].split("=", 1)[1]),
            int(rel.parts[2].split("=", 1)[1]),
        )
        frozen_p = frozen_map.get(key)
        if frozen_p is None:
            continue
        label = f"{key[0]}/y={key[1]}/m={key[2]:02d}"
        if _sha256_file(f) != frozen_p["sha256"]:
            sha_mismatch.append(label)
        n = len(pd.read_parquet(f, columns=["pool_id"]))
        if n != frozen_p["rows"]:
            rows_mismatch.append(f"{label}: rows={n} != 冻结 {frozen_p['rows']}")
    if sha_mismatch:
        problems.append(
            f"pool_state_1min 分区 sha 不一致 {len(sha_mismatch)} 个：{sha_mismatch[:5]}"
        )
    if rows_mismatch:
        problems.append(
            f"pool_state_1min 分区行数不一致 {len(rows_mismatch)} 个：{rows_mismatch[:3]}"
        )

    frozen_total_rows = frozen_1min.get("n_rows")
    if frozen_total_rows is not None and actual_rows != frozen_total_rows:
        problems.append(f"pool_state_1min 总行数 {actual_rows} != 冻结 {frozen_total_rows}")

    frozen_5 = frozen.get("pool_state_5min", {}) or {}
    five_ev: dict[str, Any] = {
        "exists": pool_5min_file.exists(),
        "frozen_sha256": frozen_5.get("sha256"),
        "frozen_n_rows": frozen_5.get("n_rows"),
    }
    if not pool_5min_file.exists():
        problems.append(f"pool_state_5min 文件缺失：{pool_5min_file}")
    else:
        five_ev["actual_sha256"] = _sha256_file(pool_5min_file)
        five_ev["actual_n_rows"] = len(pd.read_parquet(pool_5min_file))
        if not frozen_5.get("sha256"):
            problems.append("pool_state_5min：冻结 registry 未记录 sha256")
        elif five_ev["actual_sha256"] != frozen_5["sha256"]:
            problems.append("pool_state_5min sha256 与冻结 registry 不一致")
        if frozen_5.get("n_rows") is not None and five_ev["actual_n_rows"] != frozen_5["n_rows"]:
            problems.append(
                f"pool_state_5min n_rows={five_ev['actual_n_rows']} != 冻结 {frozen_5['n_rows']}"
            )

    evidence = {
        "pool_state_1min": {
            "expected_partitions": len(frozen_parts),
            "actual_partitions": len(actual_files),
            "missing_partitions": len(missing),
            "extra_partitions": len(extra),
            "sha_mismatch": len(sha_mismatch),
            "rows_mismatch": len(rows_mismatch),
            "n_rows_matches_frozen": (
                actual_rows == frozen_total_rows if frozen_total_rows is not None else None
            ),
        },
        "pool_state_5min": five_ev,
    }
    return evidence, problems


def audit_determinism(
    baseline: dict[str, Any],
    scan: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    pool_state_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """确定性：冻结产物哈希逐位复现（E0F-03/04 已冻结结果在 D0 时点仍成立）。

    门线只看数据产物 sha：split/field_mode/pool registry、source manifest、session
    分区，以及 E0F-04 pool_state_1min/5min 实际 parquet（审查结论23 P0-1）。
    code_sha 与 e0_full.yaml sha 记录为 provenance 证据，不入门线——D0 在
    E0F-04 之后的提交上运行、且 E0F-05 会向 yaml 增配 d0 输出路径，二者与 baseline
    不同属正常，不影响已冻结数据产物的完整性。
    """
    if cfg is None:
        cfg = _load_cfg()
    problems: list[str] = []

    def check(name: str, expected: str | None, actual: str) -> None:
        if expected is None:
            problems.append(f"{name}: baseline 未记录哈希")
        elif actual != expected:
            problems.append(f"{name}: 哈希不一致（产物被改动或 baseline 缺记录）")

    check("split_registry.sha256",
          baseline.get("split_registry", {}).get("split_registry", {}).get("sha256"),
          _sha256_file(_IMPL_ROOT / _REGISTRY_PATHS["split_registry"]))
    check("field_mode_registry.sha256",
          baseline.get("split_registry", {}).get("field_mode_registry", {}).get("sha256"),
          _sha256_file(_IMPL_ROOT / _REGISTRY_PATHS["field_mode_registry"]))
    check("pool_registry.sha256",
          baseline.get("pool_state", {}).get("pool_registry", {}).get("sha256"),
          _sha256_file(_IMPL_ROOT / _REGISTRY_PATHS["pool_registry"]))
    check("pool_state_registry.sha256",
          baseline.get("pool_state", {}).get("pool_state_registry", {}).get("sha256"),
          _sha256_file(_IMPL_ROOT / _REGISTRY_PATHS["pool_state_registry"]))

    if pool_state_registry is None:
        pool_state_registry = json.loads(
            (_IMPL_ROOT / _REGISTRY_PATHS["pool_state_registry"]).read_text(encoding="utf-8")
        )
    pool_ev, pool_problems = _verify_pool_state_files(
        pool_state_registry,
        _IMPL_ROOT / cfg["outputs"]["pool_state_1min"],
        _IMPL_ROOT / cfg["outputs"]["pool_state_5min"] / "pool_state_5min.parquet",
    )
    problems.extend(pool_problems)

    src_hash = manifest_hash(pd.read_parquet(_IMPL_ROOT / _REGISTRY_PATHS["source_manifest"]))
    if src_hash != baseline.get("source_manifest_sha256"):
        problems.append("source_manifest 确定性哈希与 baseline 不一致")

    mismatched = [p for p in scan["per_partition"] if not p["sha_matches_frozen"]]
    if mismatched:
        problems.append(f"session 分区文件 sha256 与冻结注册表不一致 {len(mismatched)} 个")

    yaml_sha = _sha256(_IMPL_ROOT / "configs" / "e0_full.yaml")
    code_sha = _git_commit()
    return {
        "pass": not problems,
        "evidence": {
            "artifact_sha_all_match": not problems,
            "session_partition_sha_match": len(scan["per_partition"]) - len(mismatched),
            "n_session_partitions": len(scan["per_partition"]),
            "pool_state": pool_ev,
            "e0_full_yaml_sha256": yaml_sha,
            "yaml_sha_matches_baseline": yaml_sha == baseline.get("e0_full_yaml_sha256"),
            "code_sha": code_sha,
            "baseline_code_sha": baseline.get("code_sha"),
            "code_sha_matches_baseline": code_sha == baseline.get("code_sha"),
            "provenance_note": "code_sha/yaml_sha 为 provenance，不入门线；产物 sha 才是完整性证明",
        },
        "worst": problems[:8],
    }


def audit_evaluable_aggregation(cfg: dict[str, Any]) -> dict[str, Any]:
    """evaluable 聚合机制核查（审查结论 14 重点 3）。

    只核查机制（excluded 记录不进均值、0.0 不算真实 0、非评估池分开报告、覆盖率），
    不发明数值门限（min_sessions / min_n 之类的样本量数字一律不得出现）。
    """
    ev = cfg["evaluable"]
    problems: list[str] = []
    assert_vals = {
        "exclude_not_evaluable_from_mean": True,
        "zero_not_real_zero": True,
        "report_non_evaluable_separately": True,
        "report_evaluable_coverage": True,
    }
    for k, want in assert_vals.items():
        got = ev.get(k)
        if got is not want:
            problems.append(f"evaluable.{k}={got} 期望 {want}")
    if ev.get("reasons") != ["no_core_sessions", "insufficient_core_sessions"]:
        problems.append(f"evaluable.reasons={ev.get('reasons')} 与冻结原因列表不符")
    invented = [k for k in ev if any(
        n in k.lower() for n in ("min_", "n_sessions", "threshold", "min_samples")
    )]
    if invented:
        problems.append(f"出现疑似样本量数值门限键：{invented}")
    if any(not isinstance(v, (bool, list, str)) for v in ev.values()):
        problems.append("evaluable 配置含非布尔/列表/字符串值（疑似发明数值门限）")
    return {
        "pass": not problems,
        "evidence": {"config": ev},
        "worst": problems[:8],
    }


def audit_5min_cycle(pool_1min: pd.DataFrame, pool_5min: pd.DataFrame) -> dict[str, Any]:
    """5min 周期完整性审计：pool_1min 逐桶 n_minutes_observed 分布。

    R1 不得把不完整桶（<5 分钟）当作完整控制周期；complete_5min 由 n_minutes_observed
    派生（边界处池内活跃分钟不足属自然状态，须报告）。
    """
    g = pool_1min.groupby(["pool_id", pool_1min["timestamp_utc"].dt.floor("5min")])[
        "timestamp_utc"
    ].nunique().rename("n_minutes_observed").reset_index()
    complete = int((g["n_minutes_observed"] == 5).sum())
    incomplete = int((g["n_minutes_observed"] < 5).sum())
    vc = g["n_minutes_observed"].value_counts().sort_index()
    dist = {int(cast(Any, k)): int(v) for k, v in vc.items()}
    worst_pool = (
        g[g["n_minutes_observed"] < 5].groupby("pool_id")["n_minutes_observed"].count()
    )
    return {
        "pass": True,
        "evidence": {
            "n_buckets": int(len(g)),
            "n_complete_5min": complete,
            "n_incomplete": incomplete,
            "share_incomplete": round(float(incomplete / max(len(g), 1)), 4),
            "minutes_distribution": {int(k): int(v) for k, v in dist.items()},
            "incomplete_buckets_by_pool": {
                pid: int(v) for pid, v in worst_pool.items()
            },
            "n_pool_5min_rows": int(len(pool_5min)),
        },
        "worst": [],
    }


def audit_pilot_zero_guard(pool_5min: pd.DataFrame) -> dict[str, Any]:
    """pilot_coverage==0 语义护栏：pilot_upper_kw_total 必须为 0；该 0 不得解释为真实 pilot=0。"""
    zero_cov = pool_5min[pool_5min["pilot_coverage"].fillna(1.0) == 0]
    nonzero_upper = zero_cov[zero_cov["pilot_upper_kw_total"].fillna(0.0) != 0]
    by_pool = zero_cov.groupby("pool_id")["timestamp_utc"].count().to_dict()
    return {
        "pass": bool(nonzero_upper.empty),
        "evidence": {
            "n_pilot_coverage_zero_rows": int(len(zero_cov)),
            "share_of_pool_minutes": round(
                float(len(zero_cov) / max(len(pool_5min), 1)), 6
            ),
            "rows_pilot_zero_but_upper_nonzero": int(len(nonzero_upper)),
            "by_pool": {pid: int(v) for pid, v in by_pool.items()},
        },
        "worst": (
            [f"pilot_coverage==0 但 pilot_upper_kw_total!=0 共 {len(nonzero_upper)} 行"]
            if not nonzero_upper.empty
            else []
        ),
    }


def _build_report(
    gates: dict[str, dict[str, Any]],
    semantic: dict[str, Any],
    frozen_artifacts: dict[str, Any],
) -> str:
    lines: list[str] = [
        "# E0F-05 数据链验收审计（D0）报告",
        "",
        "## 口径声明",
        "",
        "D0 是对 E0F-01..04 冻结产物的只读验收审计：任何门不通过即 STOP，"
        "不更新 baseline、不得进入 E0F-06/R1。门线用原始中位，round 只用于显示；"
        "测试集冻结后不逐图调参。",
        "",
        "## 十门判定",
        "",
        "| 门 | 结果 | 关键证据 |",
        "|---|---|---|",
    ]
    for name in GATE_NAMES:
        g = gates[name]
        status = "PASS" if g["pass"] else "FAIL"
        ev = g.get("evidence", {})
        lines.append(f"| {name} | {status} | {json.dumps(ev, ensure_ascii=False)[:120]} |")
    lines.append("")
    lines.append("## 每门关键证据与最坏情况")
    lines.append("")
    for name in GATE_NAMES:
        g = gates[name]
        lines.append(f"### {name} — {'PASS' if g['pass'] else 'FAIL'}")
        ev = g.get("evidence", {})
        if ev:
            lines.append(f"- 证据：`{json.dumps(ev, ensure_ascii=False)}`")
        worst = g.get("worst")
        if worst:
            joined = "; ".join(str(w) for w in worst)
            lines.append(f"- 最坏情况/问题：{joined}")
        else:
            lines.append("- 最坏情况：无")
        lines.append("")
    lines.append("## 语义护栏")
    lines.append("")
    lines.append(
        "- pilot_coverage==0 行：pilot_upper_kw_total 必须为 0，且 0 只表示"
        "\"无导引可用\"，不得解释为真实 pilot=0（供 E2/R1 消费）。"
        "  [硬护栏：FAIL 即 STOP]"
    )
    pz = semantic["pilot_zero"]["evidence"]
    lines.append(
        f"  - 命中行数：{pz['n_pilot_coverage_zero_rows']}，"
        f"其中 pilot_upper 非 0 行：{pz['rows_pilot_zero_but_upper_nonzero']}"
        f"（护栏判定：{'PASS' if semantic['pilot_zero']['pass'] else 'FAIL'}）"
    )
    cyc = semantic["cycle"]["evidence"]
    lines.append(
        "- 5min 池表：每桶 n_minutes_observed 分布"
        f" {json.dumps(cyc['minutes_distribution'], ensure_ascii=False)}，"
        f"完整桶 {cyc['n_complete_5min']}，"
        f"不完整桶占比 {cyc['share_incomplete']}；"
        "R1 不得把不完整桶当完整控制周期。[仅报告：不完整桶为自然边界状态]"
    )
    lines.append("")
    lines.append("## 冻结产物时点")
    lines.append("")
    lines.append(f"- created_at_utc：{frozen_artifacts['created_at_utc']}")
    code_sha = frozen_artifacts["code_sha"]
    lines.append(f"- 冻结时点 code_sha（provenance，E0F-04 冻结提交）：`{code_sha}`")
    sr = frozen_artifacts.get("session_response", {}).get("partition_registry", {})
    if sr:
        lines.append(f"- E0F-03 分区：{sr.get('n_partitions')} 个分区，"
                     f"{sr.get('n_rows'):,} 行，{sr.get('n_sessions'):,} 会话")
    return "\n".join(lines)


def run_e0f05(
    require_clean: bool = True,
) -> dict[str, Any]:
    """执行 D0 十门验收并写报告 + d0_registry.json（唯一写出的两个产物）。

    require_clean=True（正式门）：存在未提交代码（git_dirty_code 非空）则拒绝审计。
    """
    cfg = _load_cfg()
    baseline = _load_baseline()
    dirty = _git_dirty_code()
    if require_clean and dirty:
        raise RuntimeError(
            "E0F-05 D0 拒绝运行：存在未提交代码（git_dirty_code 非空）。"
            "请先提交代码再在 clean worktree 上运行；"
            f"dirty files: {dirty}"
        )

    reg = _load_registry(_REGISTRY_PATHS["split_registry"])
    pool_registry = pd.read_csv(_IMPL_ROOT / _REGISTRY_PATHS["pool_registry"])
    frozen_parts = json.loads(
        (_IMPL_ROOT / _REGISTRY_PATHS["session_response_partitions"]).read_text(
            encoding="utf-8"
        )
    )
    quality = json.loads(
        (_IMPL_ROOT / _REGISTRY_PATHS["quality_summary"]).read_text(encoding="utf-8")
    )
    manifest = pd.read_parquet(_IMPL_ROOT / _REGISTRY_PATHS["source_manifest"])
    pool_state_registry = json.loads(
        (_IMPL_ROOT / _REGISTRY_PATHS["pool_state_registry"]).read_text(encoding="utf-8")
    )
    out_dir = _IMPL_ROOT / cfg["outputs"]["session_minute_1min"]
    pool_1min = pd.concat(
        [pd.read_parquet(p) for p in sorted(
            (_IMPL_ROOT / cfg["outputs"]["pool_state_1min"]).glob(
                "site=*/year=*/month=*/data.parquet"
            )
        )],
        ignore_index=True,
    )
    pool_5min = pd.read_parquet(_IMPL_ROOT / cfg["outputs"]["pool_state_5min"])

    scan = _partition_scan(out_dir, reg, frozen_parts)

    gates: dict[str, dict[str, Any]] = {
        "input_traceability": audit_input_traceability(cfg, baseline),
        "output_traceability": audit_output_traceability(baseline),
        "uniqueness": audit_uniqueness(scan, frozen_parts),
        "completeness": audit_completeness(quality, scan, cfg, baseline, manifest),
        "energy_consistency": audit_energy_layered(scan, reg, cfg),
        "gold_consistency": audit_gold_layered(pool_registry, pool_5min, cfg),
        "split_safety": audit_split_safety(reg, cfg),
        "leak_safety": audit_leak_safety(scan, pool_1min, pool_5min, cfg),
        "determinism": audit_determinism(baseline, scan, cfg, pool_state_registry),
        "evaluable_aggregation": audit_evaluable_aggregation(cfg),
    }
    semantic = {
        "cycle": audit_5min_cycle(pool_1min, pool_5min),
        "pilot_zero": audit_pilot_zero_guard(pool_5min),
    }

    failed = [name for name, g in gates.items() if not g["pass"]]
    hard_semantic_failed = _hard_semantic_failed(semantic)
    if failed or hard_semantic_failed:
        report = _build_report(gates, semantic, baseline)
        (_IMPL_ROOT / _D0_REPORT).parent.mkdir(parents=True, exist_ok=True)
        (_IMPL_ROOT / _D0_REPORT).write_text(report, encoding="utf-8")
        msg = (
            "E0F-05 D0 STOP：下列门未通过，不更新 baseline、不得进入 E0F-06/R1："
            f"{failed}"
        )
        if hard_semantic_failed:
            msg += f"；硬语义护栏未通过：{hard_semantic_failed}"
        raise RuntimeError(msg)

    d0 = {
        "schema": "e0_full_d0_registry",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_version": cfg["protocol_version"],
        "experiment_id": cfg["experiment_id"],
        "baseline_path": _REGISTRY_PATHS["baseline"],
        "baseline_code_sha": baseline["code_sha"],
        "gates": {
            name: {**gates[name]["evidence"], "pass": gates[name]["pass"]} for name in GATE_NAMES
        },
        "semantic_guards": {
            k: {
                **v["evidence"],
                "pass": v["pass"],
                "hard": k in HARD_SEMANTIC_GUARDS,
            }
            for k, v in semantic.items()
        },
        "report": _D0_REPORT,
        "d0_pass": True,
    }
    reg_path = _IMPL_ROOT / _D0_REGISTRY
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps(d0, ensure_ascii=False, indent=2), encoding="utf-8")
    report = _build_report(gates, semantic, baseline)
    (_IMPL_ROOT / _D0_REPORT).write_text(report, encoding="utf-8")
    return d0
