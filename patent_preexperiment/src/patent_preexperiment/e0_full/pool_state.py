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
   与本表池级 5 分钟能量比相对偏差，中位 |rel dev| < tolerance 才 gold_consistency=true。
4. session 同源一致性：从 session_response_1min 重聚合到池级并与已写 pool_state_1min
   逐行全等（两条路径同一来源）。
"""

from __future__ import annotations

import hashlib
import json
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
    """池级 5 分钟能量 vs gold 中位相对偏差 < tolerance 才 gold_consistency=true。"""
    tol = float(cfg["pool"]["gold"]["tolerance_median_rel_dev"])
    gold_pools = cfg["pool"]["gold"]["pools"]
    per_pool: dict[str, dict[str, Any]] = {}
    all_devs: list[float] = []
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
        per_pool[pid] = {
            "buckets": int(len(m)),
            "median_rel_dev": float(dev.median()),
            "p95_abs_rel_dev": float(dev.abs().quantile(0.95)),
            "gold_energy_kwh": float(m["gold"].sum()),
            "ours_energy_kwh": float(m["ours"].sum()),
        }
        all_devs.extend(dev.abs().tolist())
    overall = float(np.median(all_devs)) if all_devs else float("nan")
    ok = overall < tol
    return {
        "gold_consistency": bool(ok),
        "median_abs_rel_dev": overall,
        "tolerance": tol,
        "per_pool": per_pool,
        "gate": f"池级 5min 能量 vs gold 中位 |rel dev| < {tol}",
    }


def _build_report(
    pool_registry: pd.DataFrame,
    summary1: dict[str, Any],
    summary5: dict[str, Any],
    cross: dict[str, Any],
    source: dict[str, Any],
    gold: dict[str, Any],
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
        f"中位 |rel dev| = {gold['median_abs_rel_dev']:.6f} < {gold['tolerance']}；"
        f"{gold['gate']}",
        "",
        "### gold 逐池",
        "",
        "| pool_id | buckets | 中位 |rel dev| | p95 | gold kWh | ours kWh |",
        "|---|---|---|---|---|---|",
    ]
    for pid, v in gold["per_pool"].items():
        lines.append(
            f"| {pid} | {v['buckets']:,} | {v['median_rel_dev']:.6f} | "
            f"{v['p95_abs_rel_dev']:.6f} | {v['gold_energy_kwh']:.2f} | "
            f"{v['ours_energy_kwh']:.2f} |"
        )
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
    return "\n".join(lines) + "\n"


def run_e0f04(cfg_path: str | Path | None = None, finalize_only: bool = False) -> dict[str, Any]:
    """E0F-04 全量执行：pool_registry → pool_state_1min → pool_state_5min → 一致性验收 → 报告。

    产物：
    - data_registry/pool_registry.csv
    - datasets/pool_state_1min/site=<site>/year=YYYY/month=MM/data.parquet
    - datasets/pool_state_5min/pool_state_5min.parquet
    - reports/E0_Full_pool_state_audit.md
    """
    impl_root = Path(__file__).resolve().parents[3]
    cfg = load_yaml(cfg_path or (impl_root / "configs" / "e0_full.yaml"))
    registry = pd.read_parquet(impl_root / "data_registry" / "e0_full_split_registry.parquet")

    pool_registry = build_pool_registry(registry, cfg)
    pool_registry_out = impl_root / "data_registry" / "pool_registry.csv"
    pool_registry_out.write_text(
        pool_registry.to_csv(index=False), encoding="utf-8"
    )

    session_dir = impl_root / cfg["outputs"]["session_minute_1min"]
    pool_dir_1min = impl_root / cfg["outputs"]["pool_state_1min"]
    pool_dir_5min = impl_root / cfg["outputs"]["pool_state_5min"]
    gold_dir = acn_project_dir() / "gold"

    if finalize_only:
        p1 = _read_pool_partitions(pool_dir_1min)
        summary1 = {
            "n_rows": int(len(p1)),
            "n_partitions": len(list(pool_dir_1min.glob("site=*/year=*/month=*/data.parquet"))),
        }
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
    gold = gold_consistency(pool_registry, gold_dir, cfg, p5)

    report = _build_report(pool_registry, summary1, summary5, cross, source, gold, cfg)
    report_out = impl_root / "reports" / "E0_Full_pool_state_audit.md"
    report_out.write_text(report, encoding="utf-8")

    return {
        "pool_registry": str(pool_registry_out),
        "pool_state_1min": str(pool_dir_1min),
        "pool_state_5min": str(pool_dir_5min / "pool_state_5min.parquet"),
        "report": str(report_out),
        "summary1": summary1,
        "summary5": summary5,
        "cross_granularity": cross,
        "session_source": source,
        "gold": gold,
    }


if __name__ == "__main__":
    import sys

    r = run_e0f04(finalize_only="--finalize-only" in sys.argv)
    print(json.dumps(
        {"gold": r["gold"], "cross": r["cross_granularity"], "source": r["session_source"]},
        ensure_ascii=False, indent=2,
    ))
