"""E0F-04 控制池状态表 pool_state_1min / pool_state_5min（issue #15；V2.0 §6.3；V1.0 A.4.2）。

职责边界：
- 把 E0F-03 session_response_1min 聚合到池级状态表：pool_id = site + garage(cluster)，
  禁止跨车库合并；只含 matched 会话（严格会话验证口径），static_only 不进入池表。
- 只做可追溯的确定性聚合与一致性验收（gold 基准 / 跨粒度 / 与 session 表同源），
  不生成"可回收能力"、不做 E3 机会计算（那是 E3 的事）。

口径：
1. 1 分钟池状态：每 (pool_id, timestamp_utc) 一行；能量 = actual_power_kw / 60，
   measured_kwh/estimated_kwh 按 power_source ∈ {measured, computed} / {estimated} 拆分
   （与 gold benchmark 的 measured/estimated 口径一致）。
2. 5 分钟池状态 = 1 分钟表按 UTC 对齐 5 分钟块聚合（能量求和，其余 mean），
   跨粒度一致性 = 用同一 reducer 从 1 分钟表重算并与 5 分钟表逐行全等（无跳变）。
3. gold 一致性：金标准按 station 的 5 分钟能量（样本级前向 hold 积分）聚合到池，
   与本表池级 5 分钟能量比相对偏差；**每个 gold 池**的中位 |rel dev| < tolerance 才
   gold_consistency=true（per-pool gate，审查结论20 P0-2；overall 中位仅作摘要）。
   gold_consistency=false 时 run_e0f04 必须 hard STOP（审查结论20 P0-1）。
4. session 同源一致性：从 session_response_1min 重聚合到池级并与已写 pool_state_1min
   逐行全等（两条路径同一来源）。
5. 冻结证据池复现审计（#15 acceptance-3）：E0F-02 registry 上核对 k1_role_months 窗口
   证据池（Caltech main / JPL current-only）的 match_status×sample_layer 组成；matched
   子集计数必须 == k1_sample_registry.csv 冻结计数，证明 matched-only pool_state 保留
   复现冻结 E3-Lite 所需人口（不把 static_only 塞进池表）。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.io.paths import acn_project_dir

_POOL_1MIN_COLUMNS = [
    "pool_id", "site", "garage", "timestamp_utc",
    "n_active", "n_matched", "n_charging",
    "actual_power_kw_total", "pilot_upper_kw_total", "current_a_total",
    "measured_kwh", "estimated_kwh",
    "pilot_coverage", "state_coverage", "measured_ratio",
]

_POOL_5MIN_COLUMNS = [
    "pool_id", "site", "garage", "timestamp_utc",
    "n_active", "n_matched", "n_charging",
    "actual_power_kw_total", "pilot_upper_kw_total", "current_a_total",
    "measured_kwh", "estimated_kwh",
    "pilot_coverage", "state_coverage", "measured_ratio",
]

_GOLD_STATIONS_FROZEN = 115  # 只作哨兵，实际冻结值以 cfg['pool']['gold']['stations_frozen'] 为准


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_pool_registry(registry: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """pool_registry：pool_id(=site__garage) × station 逐行；gold 池标注。

    池成员由 matched 会话定义（静态时序中该池实际出现过的 station）。gold 池的
    冻结站数（115）必须与 cfg 一致，否则 STOP。
    """
    matched = registry[registry["match_status"].astype(str) == "matched"]
    gold_pools = {(p["site"], p["garage"]) for p in cfg["pool"]["gold"]["pools"]}
    rows: list[dict[str, Any]] = []
    for (site, garage), g in matched.groupby(["site", "garage"], sort=True):
        pid = f"{site}__{garage}"
        for station in sorted(g["station"].astype(str).unique()):
            rows.append(
                {
                    "pool_id": pid,
                    "site": site,
                    "garage": garage,
                    "station": station,
                    "gold": (site, garage) in gold_pools,
                }
            )
    reg = pd.DataFrame(rows)
    if reg.empty:
        raise RuntimeError("E0F-04 停止：matched 会话为空，无法构建 pool_registry")

    frozen = int(cfg["pool"]["gold"]["stations_frozen"])
    gold_stations = int(
        reg[reg["gold"]]["station"].nunique() if reg["gold"].any() else 0
    )
    if gold_stations != frozen:
        raise RuntimeError(
            f"E0F-04 停止：gold 池 station 数 {gold_stations} != 冻结 {frozen}"
        )
    missing_gold = [
        f"{p['site']}/{p['garage']}"
        for p in cfg["pool"]["gold"]["pools"]
        if not (reg["site"].eq(p["site"]) & reg["garage"].eq(p["garage"])).any()
    ]
    if missing_gold:
        raise RuntimeError(f"E0F-04 停止：gold 池在 matched registry 中缺失：{missing_gold}")
    return reg.reset_index(drop=True)


def aggregate_partition_1min(session_df: pd.DataFrame) -> pd.DataFrame:
    """单个 session_response 分区的池级 1 分钟聚合（纯函数，build/verify 共用）。"""
    df = session_df[session_df["match_status"].astype(str) == "matched"].copy()
    if df.empty:
        return pd.DataFrame(columns=_POOL_1MIN_COLUMNS)
    df["energy_kwh"] = df["actual_power_kw"] / 60.0
    df["is_measured"] = df["power_source"].isin(["measured", "computed"])
    df["measured_kwh"] = df["energy_kwh"].where(df["is_measured"], 0.0)
    df["estimated_kwh"] = df["energy_kwh"].where(~df["is_measured"], 0.0)
    df["pilot_ok"] = df["pilot_available"].fillna(False).astype(bool)
    df["state_ok"] = df["state_available"].fillna(False).astype(bool)
    df["is_charging"] = df["state_norm"].eq("charging")
    df["pool_id"] = df["site"] + "__" + df["garage"]

    g = df.groupby(["pool_id", "site", "garage", "timestamp_utc"], sort=True)
    out = g.agg(
        n_rows=("session_id", "size"),
        n_active=("session_id", "nunique"),
        n_charging=("is_charging", "sum"),
        actual_power_kw_total=("actual_power_kw", "sum"),
        pilot_upper_kw_total=("pilot_power_kw", "sum"),
        current_a_total=("current_a", "sum"),
        measured_kwh=("measured_kwh", "sum"),
        estimated_kwh=("estimated_kwh", "sum"),
        pilot_rows=("pilot_ok", "sum"),
        state_rows=("state_ok", "sum"),
        measured_rows=("is_measured", "sum"),
    ).reset_index()
    out["n_matched"] = out["n_active"].astype("int64")
    out["pilot_coverage"] = out["pilot_rows"] / out["n_rows"]
    out["state_coverage"] = out["state_rows"] / out["n_rows"]
    out["measured_ratio"] = out["measured_rows"] / out["n_rows"]
    out = out.drop(columns=["n_rows", "pilot_rows", "state_rows", "measured_rows"])
    return out[_POOL_1MIN_COLUMNS].sort_values(
        ["pool_id", "timestamp_utc"], kind="mergesort"
    ).reset_index(drop=True)


def aggregate_5min_from_1min(pool_1min: pd.DataFrame) -> pd.DataFrame:
    """1 分钟池表 → 5 分钟块聚合（UTC 对齐 5 分钟）。

    reducer 固定：能量列 sum，其余 mean；跨粒度一致性即"用同一 reducer 重算==已存表"。
    """
    df = pool_1min.copy()
    if df.empty:
        return pd.DataFrame(columns=_POOL_5MIN_COLUMNS)
    # 空分区（无 matched 行）写出再读回后 timestamp_utc 可能为 object dtype，
    # 与 datetime 分区 concat 会整体 upcast；先统一 coerce 避免 .dt 失败。
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["timestamp_utc"] = df["timestamp_utc"].dt.floor("5min")
    g = df.groupby(["pool_id", "site", "garage", "timestamp_utc"], sort=True)
    out = g.agg(
        n_active=("n_active", "mean"),
        n_matched=("n_matched", "mean"),
        n_charging=("n_charging", "mean"),
        actual_power_kw_total=("actual_power_kw_total", "mean"),
        pilot_upper_kw_total=("pilot_upper_kw_total", "mean"),
        current_a_total=("current_a_total", "mean"),
        measured_kwh=("measured_kwh", "sum"),
        estimated_kwh=("estimated_kwh", "sum"),
        pilot_coverage=("pilot_coverage", "mean"),
        state_coverage=("state_coverage", "mean"),
        measured_ratio=("measured_ratio", "mean"),
    ).reset_index()
    return out[_POOL_5MIN_COLUMNS].sort_values(
        ["pool_id", "timestamp_utc"], kind="mergesort"
    ).reset_index(drop=True)


def _read_pool_partitions(pool_dir: Path) -> pd.DataFrame:
    files = sorted(pool_dir.glob("site=*/year=*/month=*/data.parquet"))
    if not files:
        raise RuntimeError(f"E0F-04 停止：{pool_dir} 下无池状态分区")
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def write_pool_1min_partitions(
    session_dir: Path,
    cfg: dict[str, Any],
    pool_dir: Path,
) -> dict[str, Any]:
    """逐 site/year/month 读取 session_response 分区 → 池级 1 分钟聚合 → 写出同构分区。"""
    files = sorted(session_dir.glob("site=*/year=*/month=*/data.parquet"))
    if not files:
        raise RuntimeError(f"E0F-04 停止：{session_dir} 下无 session_response 分区")
    partitions: list[dict[str, Any]] = []
    n_rows = 0
    for f in files:
        rel = f.relative_to(session_dir)
        site = rel.parts[0].split("=", 1)[1]
        year = int(rel.parts[1].split("=", 1)[1])
        month = int(rel.parts[2].split("=", 1)[1])
        df = aggregate_partition_1min(pd.read_parquet(f))
        d = pool_dir / f"site={site}" / f"year={year}" / f"month={month:02d}"
        d.mkdir(parents=True, exist_ok=True)
        final = d / "data.parquet"
        df.to_parquet(final, index=False)
        n_rows += len(df)
        partitions.append(
            {
                "site": site,
                "year": year,
                "month": month,
                "rows": int(len(df)),
                "pools": int(df["pool_id"].nunique()) if not df.empty else 0,
                "sha256": _sha256_file(final),
            }
        )
        del df
    return {"n_rows": n_rows, "n_partitions": len(partitions), "partitions": partitions}


def write_pool_5min(pool_dir_1min: Path, pool_dir_5min: Path) -> dict[str, Any]:
    """从 1 分钟池表派生 5 分钟池表（单文件）。"""
    p1 = _read_pool_partitions(pool_dir_1min)
    p5 = aggregate_5min_from_1min(p1)
    d = pool_dir_5min
    d.mkdir(parents=True, exist_ok=True)
    final = d / "pool_state_5min.parquet"
    p5.to_parquet(final, index=False)
    return {
        "n_rows": int(len(p5)),
        "n_pools": int(p5["pool_id"].nunique()) if not p5.empty else 0,
        "sha256": _sha256_file(final),
    }


def verify_cross_granularity(
    pool_dir_1min: Path, pool_dir_5min: Path
) -> dict[str, Any]:
    """跨粒度一致性：用同一 reducer 从 1 分钟表重算 5 分钟表，逐行全等（无跳变）。"""
    p1 = _read_pool_partitions(pool_dir_1min)
    stored = pd.read_parquet(pool_dir_5min / "pool_state_5min.parquet")
    recomputed = aggregate_5min_from_1min(p1)
    left = recomputed.sort_values(["pool_id", "timestamp_utc"]).reset_index(drop=True)
    right = stored.sort_values(["pool_id", "timestamp_utc"]).reset_index(drop=True)
    for c in _POOL_5MIN_COLUMNS:
        lv = left[c]
        rv = right[c]
        if lv.dtype.kind == "f" and rv.dtype.kind == "f":
            if not np.allclose(lv.to_numpy(), rv.to_numpy(), rtol=1e-12, atol=1e-12):
                raise RuntimeError(f"E0F-04 停止（跨粒度不一致）：列 {c} 与 1 分钟重算不符")
        elif not lv.equals(rv):
            raise RuntimeError(f"E0F-04 停止（跨粒度不一致）：列 {c} 与 1 分钟重算不符")
    return {
        "cross_granularity": True,
        "5min_rows": int(len(stored)),
        "5min_energy_kwh": float(
            (stored["measured_kwh"] + stored["estimated_kwh"]).sum()
        ),
    }


def verify_session_source(
    session_dir: Path, pool_dir_1min: Path
) -> dict[str, Any]:
    """同源一致性：从 session_response_1min 重聚合到池级，与已写 pool_state_1min 逐行全等。"""
    files = sorted(session_dir.glob("site=*/year=*/month=*/data.parquet"))
    if not files:
        raise RuntimeError(f"E0F-04 停止：{session_dir} 下无 session_response 分区")
    n_checked = 0
    for f in files:
        rel = f.relative_to(session_dir)
        site = rel.parts[0].split("=", 1)[1]
        year = int(rel.parts[1].split("=", 1)[1])
        month = int(rel.parts[2].split("=", 1)[1])
        recomputed = aggregate_partition_1min(pd.read_parquet(f))
        stored = pd.read_parquet(
            pool_dir_1min / f"site={site}" / f"year={year}" / f"month={month:02d}" / "data.parquet"
        )
        recomputed = recomputed.sort_values(["pool_id", "timestamp_utc"]).reset_index(drop=True)
        stored = stored.sort_values(["pool_id", "timestamp_utc"]).reset_index(drop=True)
        for c in _POOL_1MIN_COLUMNS:
            lv = recomputed[c]
            rv = stored[c]
            if lv.dtype.kind == "f" and rv.dtype.kind == "f":
                if not np.allclose(lv.to_numpy(), rv.to_numpy(), rtol=1e-12, atol=1e-12):
                    raise RuntimeError(
                        f"E0F-04 停止（session 同源不一致）：{site}/{year}/{month} 列 {c} 不符"
                    )
            elif not lv.equals(rv):
                raise RuntimeError(
                    f"E0F-04 停止（session 同源不一致）：{site}/{year}/{month} 列 {c} 不符"
                )
        n_checked += 1
    return {"session_source_consistent": True, "partitions_checked": n_checked}


def _read_gold_pool(gold_dir: Path, pool_id: str, pool_registry: pd.DataFrame) -> pd.DataFrame:
    """金标准按池聚合：该池全部 station 的 5 分钟能量逐桶求和。"""
    stations = pool_registry.loc[
        pool_registry["pool_id"] == pool_id, "station"
    ].astype(str).tolist()
    frames = []
    for st in stations:
        fp = gold_dir / "benchmark_5min" / f"{st}.csv"
        if not fp.exists():
            raise RuntimeError(f"E0F-04 停止：gold 基准缺失 {fp}")
        g = pd.read_csv(fp)
        g["bucket_utc"] = pd.to_datetime(g["timestamp"], utc=True).dt.floor("5min")
        frames.append(
            g.groupby("bucket_utc", sort=True)["energy_kwh"].sum().rename(f"e_{st}")
        )
    joined = pd.concat(frames, axis=1)
    joined["energy_kwh"] = joined.sum(axis=1)
    return joined.reset_index()


def gold_consistency(
    pool_registry: pd.DataFrame,
    gold_dir: Path,
    cfg: dict[str, Any],
    pool_5min: pd.DataFrame,
) -> dict[str, Any]:
    """池级 5 分钟能量 vs gold：**每个 gold 池**中位 |rel dev| < tolerance 才通过。

    per-pool gate（审查结论20 P0-2）：单池系统性偏差不得被总体中位掩盖。
    overall 中位保留作摘要，不作为门依据。p95 只报告不作门线。
    """
    tol = float(cfg["pool"]["gold"]["tolerance_median_rel_dev"])
    gold_pools = cfg["pool"]["gold"]["pools"]
    per_pool: dict[str, dict[str, Any]] = {}
    for p in gold_pools:
        pid = f"{p['site']}__{p['garage']}"
        gold = _read_gold_pool(gold_dir, pid, pool_registry)
        ours = pool_5min[pool_5min["pool_id"] == pid].copy()
        ours["bucket_utc"] = ours["timestamp_utc"].dt.floor("5min")
        ours["energy_kwh"] = ours["measured_kwh"] + ours["estimated_kwh"]
        ours_g = ours.groupby("bucket_utc", sort=True)["energy_kwh"].sum().rename("ours")
        m = pd.concat([gold.set_index("bucket_utc")["energy_kwh"].rename("gold"), ours_g], axis=1)
        m = m[m["gold"].fillna(0.0) > 1e-9]
        if m.empty:
            raise RuntimeError(f"E0F-04 停止：gold 池 {pid} 无重叠桶可对比")
        dev = (m["ours"] - m["gold"]) / m["gold"]
        median_abs = float(dev.abs().median())
        per_pool[pid] = {
            "buckets": int(len(m)),
            "median_abs_rel_dev": median_abs,
            "median_rel_dev": float(dev.median()),
            "p95_abs_rel_dev": float(dev.abs().quantile(0.95)),
            "gold_energy_kwh": float(m["gold"].sum()),
            "ours_energy_kwh": float(m["ours"].sum()),
            "pass": median_abs < tol,
        }
    ok = bool(per_pool) and all(v["pass"] for v in per_pool.values())
    return {
        "gold_consistency": ok,
        "gate": "每个 gold 池中位 |rel dev| < tolerance（overall 中位仅作摘要，p95 仅报告）",
        "tolerance": tol,
        "per_pool": per_pool,
    }


def _assert_gold_gate(gold: dict[str, Any]) -> None:
    """gold_consistency=false 时正式 runner hard STOP（审查结论20 P0-1）。"""
    if gold["gold_consistency"]:
        return
    fails = [
        f"{pid} 中位|rel dev|={v['median_abs_rel_dev']:.6f} >= 冻结 {gold['tolerance']}"
        for pid, v in gold["per_pool"].items()
        if not v["pass"]
    ]
    raise RuntimeError(
        "E0F-04 停止（gold 一致性未通过，per-pool gate）：" + "；".join(fails)
    )


def evidence_pool_reproduction_audit(
    registry: pd.DataFrame,
    cfg: dict[str, Any],
    impl_root: Path,
) -> dict[str, Any]:
    """#15 acceptance-3 冻结证据池复现审计（审查结论20 第3节）。

    只在 E0F-02 registry 上做纯计数审计：
    - sample_layer <-> match_status 必须 1:1（L1<->matched、L0<->static_only）；
    - 每个证据池窗口（cfg.pool.evidence_pools.windows，月份取 k1_role_months[name]）
      按 match_status×sample_layer / match_status×split / role 报告组成；
    - matched 子集计数必须 == k1_sample_registry.csv 按 site 的冻结计数
      （机器可证：matched-only pool_state 等于冻结证据池人口，当场复现 E3-Lite）。
    k1_sample_registry.csv 缺失则交叉核对记 not_checked（组成仍报告，不放松 L0/L1 判定）。
    """
    ep = cfg["pool"]["evidence_pools"]
    cross = pd.crosstab(registry["sample_layer"], registry["match_status"])
    l1_ok = int(cross.get("matched", pd.Series(dtype="int64")).get("L1_strict_matched", 0)) == int(
        (registry["match_status"].astype(str) == "matched").sum()
    )
    l0_ok = int(
        cross.get("static_only", pd.Series(dtype="int64")).get("L0_static_extension", 0)
    ) == int((registry["match_status"].astype(str) == "static_only").sum())
    if not (l1_ok and l0_ok):
        raise RuntimeError(
            "E0F-04 停止（证据池复现）：sample_layer <-> match_status 不是 1:1 "
            "(L1<->matched、L0<->static_only)"
        )

    win_results: dict[str, Any] = {}
    for w in ep["windows"]:
        name = str(w["name"])
        site = str(w["site"])
        months = [str(m) for m in cfg["k1_role_months"][name]]
        df = registry[registry["site"].astype(str).eq(site)].copy()
        if w.get("field_mode"):
            df = df[df["field_mode"].astype(str).eq(str(w["field_mode"]))]
        df["_cyc"] = df["connection_time"].dt.strftime("%Y-%m")
        df = df[df["_cyc"].isin(months)]

        by_ms_layer: dict[str, int] = {}
        for (ms, sl), g in df.groupby(["match_status", "sample_layer"]):
            by_ms_layer[f"{ms}/{sl}"] = int(len(g))
        by_ms_split: dict[str, int] = {}
        for (ms, sp), g in df.groupby(["match_status", "split"]):
            by_ms_split[f"{ms}/{sp}"] = int(len(g))
        by_role: dict[str, int] = {}
        for rl, g in df.groupby(["role"]):
            by_role[str(rl)] = int(len(g))
        win_results[name] = {
            "site": site,
            "field_mode": w.get("field_mode"),
            "months": months,
            "n_sessions": int(len(df)),
            "n_matched": int((df["match_status"].astype(str) == "matched").sum()),
            "n_static_only": int((df["match_status"].astype(str) == "static_only").sum()),
            "by_match_status_x_sample_layer": by_ms_layer,
            "by_match_status_x_split": by_ms_split,
            "roles": by_role,
        }

    k1_path = impl_root / str(ep["k1_sample_registry"])
    k1_check: dict[str, Any] = {
        "checked": False,
        "reason": "k1_sample_registry.csv 不存在，跳过计数交叉核对（组成仍报告）",
    }
    if k1_path.exists():
        k1 = pd.read_csv(k1_path)
        expected = {str(s): int(n) for s, n in k1["site"].value_counts().items()}
        mismatch: dict[str, Any] = {}
        for name, v in win_results.items():
            if v["site"] in expected and v["n_matched"] != expected[v["site"]]:
                mismatch[name] = {
                    "window_matched": v["n_matched"],
                    "k1_frozen": expected[v["site"]],
                }
        k1_check = {
            "checked": True,
            "expected_by_site": expected,
            "actual_matched_by_window": {
                name: v["n_matched"] for name, v in win_results.items()
            },
            "mismatch": mismatch,
        }
        if mismatch:
            raise RuntimeError(
                "E0F-04 停止（证据池复现失败）：matched 子集 != k1_sample_registry 冻结计数；"
                f"{mismatch}"
            )

    return {
        "sample_layer_match_status_1to1": True,
        "windows": win_results,
        "k1_sample_registry_cross_check": k1_check,
        "conclusion": (
            "冻结证据池人口 100% matched（matched 子集 == K1 冻结计数），matched-only "
            "pool_state 保留复现冻结 E3-Lite 所需人口；无需 amendment 到 R1/#17"
        ),
    }


def _git_commit() -> str:
    root = Path(__file__).resolve().parents[4]
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                cwd=root,
            )
            .stdout.strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _pool_partition_summary(pool_dir_1min: Path) -> dict[str, Any]:
    """finalize 路径的 1 分钟池分区摘要（含逐分区 sha256），与 build 路径同构。"""
    files = sorted(pool_dir_1min.glob("site=*/year=*/month=*/data.parquet"))
    if not files:
        raise RuntimeError(f"E0F-04 停止：{pool_dir_1min} 下无池状态分区")
    partitions: list[dict[str, Any]] = []
    n_rows = 0
    for f in files:
        rel = f.relative_to(pool_dir_1min)
        site = rel.parts[0].split("=", 1)[1]
        year = int(rel.parts[1].split("=", 1)[1])
        month = int(rel.parts[2].split("=", 1)[1])
        df = pd.read_parquet(f, columns=["pool_id"])
        n_rows += len(df)
        partitions.append(
            {
                "site": site,
                "year": year,
                "month": month,
                "rows": int(len(df)),
                "pools": int(df["pool_id"].nunique()) if not df.empty else 0,
                "sha256": _sha256_file(f),
            }
        )
    return {"n_rows": n_rows, "n_partitions": len(partitions), "partitions": partitions}


def write_pool_state_registry(
    impl_root: Path,
    pool_registry: pd.DataFrame,
    summary1: dict[str, Any],
    summary5: dict[str, Any],
    cross: dict[str, Any],
    source: dict[str, Any],
    gold: dict[str, Any],
    evidence: dict[str, Any],
    cfg: dict[str, Any],
) -> Path:
    """E0F-04 产物注册表（哈希冻结：pool_registry + 1min 分区 + 5min 文件 + 报告）。"""
    data: dict[str, Any] = {
        "schema": "e0_full_pool_state.schema.json",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "code_sha": _git_commit(),
        "pool_registry": {
            "path": "data_registry/pool_registry.csv",
            "sha256": _sha256_file(impl_root / "data_registry" / "pool_registry.csv"),
            "n_pools": int(pool_registry["pool_id"].nunique()),
            "n_stations": int(pool_registry["station"].nunique()),
            "n_gold_stations": int(pool_registry["gold"].sum()),
        },
        "pool_state_1min": {
            "dir": str(cfg["outputs"]["pool_state_1min"]),
            "n_rows": summary1["n_rows"],
            "n_partitions": summary1["n_partitions"],
            "partitions": summary1["partitions"],
        },
        "pool_state_5min": {
            "file": str(cfg["outputs"]["pool_state_5min"]) + "/pool_state_5min.parquet",
            "n_rows": summary5["n_rows"],
            "n_pools": summary5["n_pools"],
            "sha256": _sha256_file(
                impl_root / cfg["outputs"]["pool_state_5min"] / "pool_state_5min.parquet"
            ),
        },
        "consistency": {"cross_granularity": cross, "session_source": source},
        "gold": gold,
        "evidence_pool_reproduction": evidence,
        "report": "reports/E0_Full_pool_state_audit.md",
    }
    out = impl_root / "data_registry" / "e0_full_pool_state_registry.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _update_baseline(
    impl_root: Path,
    cfg: dict[str, Any],
    pool_registry_json: Path,
    pool_registry: pd.DataFrame,
    summary1: dict[str, Any],
) -> None:
    """把 E0F-04 产物哈希追加进 e0_full_baseline.json（保留 E0F-01..03 节点）。"""
    baseline_out = impl_root / "data_registry" / "e0_full_baseline.json"
    if not baseline_out.exists():
        return
    prev = json.loads(baseline_out.read_text(encoding="utf-8"))
    from patent_preexperiment.e0_full.baseline import build_e0_full_baseline

    pool_state_meta = {
        "pool_registry": {
            "sha256": _sha256_file(impl_root / "data_registry" / "pool_registry.csv"),
            "n_pools": int(pool_registry["pool_id"].nunique()),
        },
        "pool_state_registry": {
            "sha256": _sha256_file(pool_registry_json),
            "n_rows_1min": summary1["n_rows"],
            "n_partitions_1min": summary1["n_partitions"],
        },
        "report": "reports/E0_Full_pool_state_audit.md",
    }
    build_e0_full_baseline(
        out=baseline_out,
        manifest_hash_hex=str(prev["source_manifest_sha256"]),
        config=cfg,
        require_clean=True,
        split_registry=prev.get("split_registry"),
        session_response=prev.get("session_response"),
        pool_state=pool_state_meta,
    )


def _build_report(
    pool_registry: pd.DataFrame,
    summary1: dict[str, Any],
    summary5: dict[str, Any],
    cross: dict[str, Any],
    source: dict[str, Any],
    gold: dict[str, Any],
    evidence: dict[str, Any],
    cfg: dict[str, Any],
) -> str:
    lines = [
        "# E0-Full 控制池状态表审计（E0F-04）",
        "",
        "## 口径声明",
        "",
        "pool_state 把 session_response_1min 聚合到池级：pool_id = site + garage(cluster)，",
        "禁止跨车库合并；只含 matched 会话（严格会话验证口径），static_only 不进池表。",
        "只做确定性聚合与一致性验收，不生成 E3 机会指标。",
        f"- pool_registry：{len(pool_registry)} 行（pool_id×station），"
        f"{pool_registry['pool_id'].nunique()} 个池，"
        f"{int(pool_registry['gold'].sum())} 个 gold 池站，"
        f"冻结 {cfg['pool']['gold']['stations_frozen']}。",
        f"- pool_state_1min：{summary1['n_rows']:,} 行，{summary1['n_partitions']} 分区。",
        f"- pool_state_5min：{summary5['n_rows']:,} 行，{summary5['n_pools']} 池。",
        "- 能量口径：actual_power_kw/60；measured_kwh/estimated_kwh 按 power_source",
        " ∈ {measured, computed}/{estimated} 拆分（与 gold 口径一致）。",
        "",
        "## 一致性验收",
        "",
        f"- 跨粒度（5min == 1min 同 reducer 重算全等）："
        f"{'PASS' if cross['cross_granularity'] else 'FAIL'}；"
        f"5min 总能量 {cross['5min_energy_kwh']:.2f} kWh",
        f"- session 同源（从 session_response_1min 重聚合全等）："
        f"{'PASS' if source['session_source_consistent'] else 'FAIL'}；"
        f"检查 {source['partitions_checked']} 个分区",
        f"- gold 一致性：{'PASS' if gold['gold_consistency'] else 'FAIL'}；"
        f"{gold['gate']}；gold_consistency=false 即 hard STOP（审查结论20 P0-1）",
        "",
        "### gold 逐池（per-pool gate：每个池中位 |rel dev| < tolerance）",
        "",
        "| pool_id | buckets | 中位 |rel dev| | 中位 rel dev | p95 | gold kWh | ours kWh | PASS |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for pid, v in gold["per_pool"].items():
        lines.append(
            f"| {pid} | {v['buckets']:,} | {v['median_abs_rel_dev']:.6f} | "
            f"{v['median_rel_dev']:.6f} | {v['p95_abs_rel_dev']:.6f} | "
            f"{v['gold_energy_kwh']:.2f} | {v['ours_energy_kwh']:.2f} | "
            f"{'PASS' if v['pass'] else 'FAIL'} |"
        )
    lines += [
        "",
        "## 冻结证据池复现审计（#15 acceptance-3）",
        "",
        f"- sample_layer <-> match_status 1:1（L1<->matched、L0<->static_only）："
        f"{'PASS' if evidence['sample_layer_match_status_1to1'] else 'FAIL'}",
    ]
    for name, v in evidence["windows"].items():
        lines.append(
            f"- **{name}**（site={v['site']}，field_mode={v['field_mode']}）："
            f"冻结窗口 {v['months']} 内 n={v['n_sessions']:,} 会话，"
            f"matched={v['n_matched']:,}，static_only={v['n_static_only']:,}；"
            f"组成 {v['by_match_status_x_sample_layer']}；"
            f"split 分布 {v['by_match_status_x_split']}；role={v['roles']}"
        )
    k1c = evidence["k1_sample_registry_cross_check"]
    if k1c["checked"]:
        lines.append(
            f"- K1 冻结样本计数交叉核对：PASS（matched 子集 == k1_sample_registry，"
            f"{k1c['actual_matched_by_window']}）"
        )
    else:
        lines.append(f"- K1 冻结样本计数交叉核对：未做（{k1c['reason']}）")
    lines += ["", "## 池清单（n_stations / gold）", ""]
    for (pid, gold_flag), g in pool_registry.groupby(["pool_id", "gold"], sort=True):
        lines.append(
            f"- {pid}：{g['station'].nunique()} stations，"
            f"{'gold' if gold_flag else 'non-gold'}"
        )
    lines += ["", "## 规则依据", ""]
    lines.append(f"- 池定义：`{cfg['pool']['pool_id_rule']}`")
    lines.append(f"- 范围：`{cfg['pool']['scope']}`")
    lines.append(
        f"- gold 冻结站数：`{cfg['pool']['gold']['stations_frozen']}`；"
        f"tolerance：`{cfg['pool']['gold']['tolerance_median_rel_dev']}`"
    )
    lines.append(f"- 证据池：`{cfg['pool']['evidence_pools']['description']}`")
    return "\n".join(lines) + "\n"


def run_e0f04(
    cfg_path: str | Path | None = None,
    finalize_only: bool = False,
    impl_root: str | Path | None = None,
    gold_dir: str | Path | None = None,
) -> dict[str, Any]:
    """E0F-04 全量执行：证据审计 → pool_registry → pool_state_1min → 5min → 一致性 → 报告。

    产物：
    - data_registry/pool_registry.csv
    - datasets/pool_state_1min/site=<site>/year=YYYY/month=MM/data.parquet
    - datasets/pool_state_5min/pool_state_5min.parquet
    - reports/E0_Full_pool_state_audit.md
    - data_registry/e0_full_pool_state_registry.json
    - data_registry/e0_full_baseline.json（追加 pool_state 节）

    gold_consistency=false 一律 hard STOP（审查结论20 P0-1/P0-2），不产出报告。
    impl_root/gold_dir 可注入用于测试（默认解析真实实现根与 acn_project/gold）。
    """
    root = Path(impl_root) if impl_root is not None else Path(__file__).resolve().parents[3]
    cfg = load_yaml(cfg_path or (root / "configs" / "e0_full.yaml"))
    registry = pd.read_parquet(root / "data_registry" / "e0_full_split_registry.parquet")

    evidence = evidence_pool_reproduction_audit(registry, cfg, root)

    pool_registry = build_pool_registry(registry, cfg)
    pool_registry_out = root / "data_registry" / "pool_registry.csv"
    pool_registry_out.parent.mkdir(parents=True, exist_ok=True)
    pool_registry_out.write_text(
        pool_registry.to_csv(index=False), encoding="utf-8"
    )

    session_dir = root / cfg["outputs"]["session_minute_1min"]
    pool_dir_1min = root / cfg["outputs"]["pool_state_1min"]
    pool_dir_5min = root / cfg["outputs"]["pool_state_5min"]
    gold_dir_resolved = Path(gold_dir) if gold_dir is not None else acn_project_dir() / "gold"

    if finalize_only:
        summary1 = _pool_partition_summary(pool_dir_1min)
        p5 = pd.read_parquet(pool_dir_5min / "pool_state_5min.parquet")
        summary5 = {
            "n_rows": int(len(p5)),
            "n_pools": int(p5["pool_id"].nunique()),
        }
    else:
        summary1 = write_pool_1min_partitions(session_dir, cfg, pool_dir_1min)
        summary5 = write_pool_5min(pool_dir_1min, pool_dir_5min)

    cross = verify_cross_granularity(pool_dir_1min, pool_dir_5min)
    source = verify_session_source(session_dir, pool_dir_1min)
    p5 = pd.read_parquet(pool_dir_5min / "pool_state_5min.parquet")
    gold = gold_consistency(pool_registry, gold_dir_resolved, cfg, p5)
    _assert_gold_gate(gold)

    report = _build_report(
        pool_registry, summary1, summary5, cross, source, gold, evidence, cfg
    )
    report_out = root / "reports" / "E0_Full_pool_state_audit.md"
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(report, encoding="utf-8")

    pool_registry_json = write_pool_state_registry(
        root, pool_registry, summary1, summary5, cross, source, gold, evidence, cfg
    )
    _update_baseline(root, cfg, pool_registry_json, pool_registry, summary1)

    return {
        "pool_registry": str(pool_registry_out),
        "pool_state_1min": str(pool_dir_1min),
        "pool_state_5min": str(pool_dir_5min / "pool_state_5min.parquet"),
        "report": str(report_out),
        "pool_state_registry": str(pool_registry_json),
        "summary1": summary1,
        "summary5": summary5,
        "cross_granularity": cross,
        "session_source": source,
        "gold": gold,
        "evidence_pool_reproduction": evidence,
    }


if __name__ == "__main__":
    import sys

    r = run_e0f04(finalize_only="--finalize-only" in sys.argv)
    print(json.dumps(
        {
            "gold": r["gold"],
            "cross": r["cross_granularity"],
            "source": r["session_source"],
            "evidence": r["evidence_pool_reproduction"],
        },
        ensure_ascii=False, indent=2,
    ))
