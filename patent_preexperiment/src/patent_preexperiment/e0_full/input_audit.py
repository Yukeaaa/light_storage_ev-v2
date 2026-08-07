"""E0F-01 全量输入 manifest 与数据质量审计（V2.1 §10；审查结论7 §5；审查结论9）。

职责（E0F-01 只读输入，read_only=true，禁止原地清洗）：
1. 独立全量扫描 ACN 静态时序文件，构建确定性 source manifest：
   logical_path/site/garage/station/file_size/rows/time_min/time_max/read_ok/gzip_ok/sha256，
   加上 pilot/current/power/voltage/state/energy 覆盖、短文件、重复/倒序、严重缺口。
2. 用冻结的 static_file_index.csv 做交叉校验（rows/time 范围/覆盖/哈希一致性）。
3. connectionTime 只审计不切分：matched 会话按
   API connectionTime 可解析且不矛盾 → api_metadata；
   缺失/无法解析 → first_observation_fallback（允许自动回退）；
   可解析但与首条观测明显矛盾 → 只登记 anomaly，禁止自动替换（审查结论9 强制）。
4. 汇总数据质量（覆盖/功率优先级可用性/能量一致性/缺口），并给出 stop-line 判定。

manifest 确定性要求：同输入重复运行产物完全一致（固定排序 + 纯字节哈希）。
"""

from __future__ import annotations

import hashlib
import json
import zlib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.io.paths import acn_project_dir, static_root_dir

_COL_KEY = {
    "Charging Current (A)": "current",
    "Actual Pilot (A)": "pilot",
    "Voltage (V)": "voltage",
    "Charging State": "state",
    "Energy Delivered (kWh)": "energy",
    "Power (kW)": "power",
}


@dataclass(frozen=True)
class ScanConfig:
    """逐文件扫描阈值（从 e0_full.yaml 冻结值构造）。"""

    min_rows_per_file: int = 10          # 短文件阈值
    severe_gap_min: float = 20.0         # 严重缺口阈值（分钟）

    @classmethod
    def from_cfg(cls, cfg: dict[str, Any]) -> ScanConfig:
        return cls(
            min_rows_per_file=int(cfg["short_files"]["min_rows_per_file"]),
            severe_gap_min=float(cfg["gaps"]["severe_gap_min"]),
        )


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _decompress_first_gzip_member(raw: bytes) -> bytes:
    """解压第一个 gzip 成员，忽略尾部垃圾字节（acn_project 7 文件场景）。"""
    d = zlib.decompressobj(zlib.MAX_WBITS | 16)
    chunks: list[bytes] = []
    while not d.eof:
        chunk = d.decompress(raw, 1 << 20)
        if not chunk:
            break
        chunks.append(chunk)
        raw = d.unconsumed_tail + d.unused_data
    return b"".join(chunks)


def scan_static_file(path: str | Path) -> dict[str, Any]:
    """独立扫描单个静态 csv.gz，返回确定性逐文件记录（不依赖冻结 index）。

    字段：sha256、read_ok、gzip_ok、trailing_garbage、rows、time_min、time_max、
    has_*（列存在且有非空值）、n_dup_ts、n_reversed、max_gap_min。
    """
    path = Path(path)
    raw = path.read_bytes()
    sha256 = _sha256_bytes(raw)

    read_ok = False
    gzip_ok = False
    trailing_garbage = False
    text = b""

    try:
        d = zlib.decompressobj(zlib.MAX_WBITS | 16)
        out = d.decompress(raw)
        if d.unconsumed_tail:
            out += d.unconsumed_tail
        text = out
        gzip_ok = d.eof and not d.unused_data      # 完整单成员、无尾部垃圾
        trailing_garbage = d.eof and bool(d.unused_data)  # 干净流但带尾部字节
    except zlib.error:
        try:
            text = _decompress_first_gzip_member(raw)
            gzip_ok = False
            trailing_garbage = True
        except zlib.error:
            gzip_ok = False

    rows = 0
    time_min: datetime | None = None
    time_max: datetime | None = None
    has: dict[str, bool] = {k: False for k in _COL_KEY.values()}
    seen: set[str] = set()
    n_dup_ts = 0
    n_reversed = 0
    max_gap_min = 0.0
    prev: datetime | None = None

    if text:
        try:
            header = text.split(b"\n", 1)[0]
            cols = header.decode("utf-8", errors="replace").strip().split(",")
            col_idx: dict[str, int] = {}
            for i, c in enumerate(cols):
                key = c.strip()
                if key in _COL_KEY:
                    col_idx[_COL_KEY[key]] = i
            data_lines = text.split(b"\n")[1:]
            for line in data_lines:
                if not line.strip():
                    continue
                parts = line.split(b",")
                try:
                    ts = datetime.fromisoformat(parts[0].decode("ascii"))
                except (ValueError, UnicodeDecodeError):
                    continue
                rows += 1
                ts_iso = parts[0].decode("ascii")
                if ts_iso in seen:
                    n_dup_ts += 1
                seen.add(ts_iso)
                if time_min is None or ts < time_min:
                    time_min = ts
                if time_max is None or ts > time_max:
                    time_max = ts
                if prev is not None:
                    if ts < prev:
                        n_reversed += 1
                    gap_min = (ts - prev).total_seconds() / 60.0
                    if gap_min > max_gap_min:
                        max_gap_min = gap_min
                prev = ts
                for key, idx in col_idx.items():
                    if not has[key] and idx < len(parts) and parts[idx].strip():
                        has[key] = True
            read_ok = True
        except Exception:  # noqa: BLE001
            read_ok = False

    return {
        "logical_path": str(path),
        "sha256": sha256,
        "read_ok": read_ok,
        "gzip_ok": gzip_ok,
        "trailing_garbage": trailing_garbage,
        "rows": rows,
        "time_min": time_min.isoformat() if time_min else None,
        "time_max": time_max.isoformat() if time_max else None,
        "n_dup_ts": n_dup_ts,
        "n_reversed": n_reversed,
        "max_gap_min": round(max_gap_min, 2),
        **{f"has_{k}": v for k, v in has.items()},
    }


def _manifest_row(
    index_row: dict[str, Any], scan: dict[str, Any], cfg: ScanConfig
) -> dict[str, Any]:
    rows = int(scan["rows"])
    return {
        "logical_path": index_row["logical_path"],
        "site": index_row["site"],
        "garage": index_row["garage"],
        "station": index_row["station"],
        "file_size": int(index_row["file_size"]),
        "rows": rows,
        "time_min": scan["time_min"],
        "time_max": scan["time_max"],
        "read_ok": scan["read_ok"],
        "gzip_ok": scan["gzip_ok"],
        "trailing_garbage": scan["trailing_garbage"],
        "sha256": scan["sha256"],
        **{f"has_{k}": scan[f"has_{k}"] for k in _COL_KEY.values()},
        "short_file": bool(rows < cfg.min_rows_per_file),
        "n_dup_ts": int(scan["n_dup_ts"]),
        "n_reversed": int(scan["n_reversed"]),
        "max_gap_min": float(scan["max_gap_min"]),
        "severe_gap": bool(float(scan["max_gap_min"]) >= cfg.severe_gap_min),
    }


def _scan_worker(args: tuple[dict[str, Any], str, ScanConfig]) -> dict[str, Any]:
    """进程池工作函数（模块级，保证 Windows spawn 可 pickle）：扫描单文件。"""
    index_row, static_root, cfg = args
    abs_path = Path(static_root) / index_row["logical_path"]
    return _manifest_row(index_row, scan_static_file(abs_path), cfg)


def build_source_manifest(
    index_df: pd.DataFrame,
    static_root: str | Path,
    cfg: ScanConfig | None = None,
    workers: int = 1,
) -> pd.DataFrame:
    """基于冻结 static_file_index 的逻辑路径，独立全量扫描并构建确定性 manifest。

    注意：index 只提供 logical_path/site/garage/station/file_size 作为定位与交叉校验基准；
    rows/time/覆盖/哈希全部由独立扫描得出（不信任 index 的 rows/first_ts/has_*）。
    workers>1 时用 ProcessPoolExecutor；map 保持输入顺序 → 输出确定性。
    """
    cfg = cfg or ScanConfig()
    index_rows: list[dict[str, Any]] = []
    for _, r in index_df.iterrows():
        index_rows.append(
            {
                "logical_path": str(r["file"]).replace("\\", "/"),
                "site": str(r["site"]),
                "garage": str(r["garage"]),
                "station": str(r["stationID"]),
                "file_size": int(r["file_size"]),
                "index_rows": int(r["rows"]),
            }
        )

    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            scan_rows = list(
                ex.map(
                    _scan_worker,
                    [(r, str(static_root), cfg) for r in index_rows],
                )
            )
    else:
        scan_rows = [_scan_worker((r, str(static_root), cfg)) for r in index_rows]

    df = pd.DataFrame(scan_rows)
    df = df.sort_values("logical_path").reset_index(drop=True)
    # 交叉校验列：index 的 rows 与独立扫描 rows 的一致性
    index_rows_by_path = {r["logical_path"]: r["index_rows"] for r in index_rows}
    df["index_rows"] = df["logical_path"].map(index_rows_by_path)
    df["rows_match_index"] = df["rows"] == df["index_rows"]
    return df


def manifest_hash(df: pd.DataFrame) -> str:
    """确定性 manifest 哈希：固定列序 + 按 logical_path 排序后序列化取 sha256。"""
    cols = sorted(df.columns)
    buf = df[cols].to_csv(index=False)
    return _sha256_bytes(buf.encode("utf-8"))


def _index_manifest_hash(acn: Path) -> dict[str, dict[str, Any]]:
    """三个冻结 manifest 的 sha256/rows/exists（baseline 与审计共用）。"""
    result: dict[str, dict[str, Any]] = {}
    for name in ("static_file_index.csv", "api_metadata_index.csv", "static_api_mapping.csv"):
        p = acn / "manifests" / name
        if not p.exists():
            result[name] = {"sha256": None, "rows": None, "exists": False}
            continue
        result[name] = {
            "sha256": _sha256_bytes(p.read_bytes()),
            "rows": sum(1 for _ in p.open("r", encoding="utf-8", errors="replace")) - 1,
            "exists": True,
        }
    return result


def _power_source_stats(manifest: pd.DataFrame) -> dict[str, dict[str, int]]:
    """按站点的功率可用性统计（E0F-01 只判可用性，不生成 field_mode_registry）。"""
    sites: list[str] = sorted(manifest["site"].unique().tolist())
    result: dict[str, dict[str, int]] = {}
    for site in sites:
        m = manifest[manifest["site"] == site]
        result[site] = {
            "files": int(len(m)),
            "measured_power": int(m["has_power"].sum()),          # power_kw 实测可用
            "computed_voltage_current": int((m["has_voltage"] & m["has_current"]).sum()),
            "estimated_current_only": int((m["has_current"] & ~m["has_voltage"]).sum()),
            "pilot_available": int(m["has_pilot"].sum()),
            "state_available": int(m["has_state"].sum()),
        }
    return result


def audit_connection_time(
    mapping: pd.DataFrame,
    api_meta: pd.DataFrame,
    manifest: pd.DataFrame,
    cfg: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """connectionTime 只审计不切分（审查结论9 强制）。

    matched 会话分类：
    - API connectionTime 可解析且不矛盾 → api_metadata
    - API connectionTime 缺失/无法解析 → first_observation_fallback（允许自动回退）
    - API connectionTime 可解析但与首条观测明显矛盾 → anomaly（只登记，禁止自动替换）

    返回 (逐会话审计表, 汇总统计)。
    """
    audit_cfg = cfg["session_join"]["connection_time"]["audit"]
    tol_ahead_min = float(audit_cfg["contradiction_tolerance_ahead_min"])
    tol_behind_h = float(audit_cfg["contradiction_tolerance_behind_h"])

    matched = mapping[mapping["match_status"] == "matched"].copy()
    if matched.empty:
        return pd.DataFrame(), {"matched": 0, "api_metadata": 0, "fallback": 0, "anomaly": 0}

    first_obs = manifest[["logical_path", "time_min"]].dropna(subset=["time_min"])
    first_map = dict(zip(first_obs["logical_path"], first_obs["time_min"], strict=False))
    api_ct = api_meta[["sessionID", "connectionTime"]].drop_duplicates(subset=["sessionID"])
    api_lookup: dict[str, Any] = {
        str(row.sessionID): row.connectionTime for row in api_ct.itertuples(index=False)
    }

    rows: list[dict[str, Any]] = []
    for _, r in matched.iterrows():
        session = str(r["sessionID"])
        static_file = str(r["static_file"]).replace("\\", "/")
        first_ts = first_map.get(static_file)
        api_raw = api_lookup.get(session)
        api_ts: datetime | None = None
        source = None
        anomaly_reason = None

        if api_raw is not None and not pd.isna(api_raw):
            try:
                api_ts = datetime.fromisoformat(str(api_raw))
            except ValueError:
                api_ts = None

        if api_ts is None or first_ts is None:
            source = "first_observation_fallback"
        else:
            first_dt = datetime.fromisoformat(first_ts)
            diff_min = (api_ts - first_dt).total_seconds() / 60.0
            if diff_min > tol_ahead_min or diff_min < -tol_behind_h * 60.0:
                source = "anomaly"
                anomaly_reason = (
                    f"api_ct-first_obs={diff_min:+.1f}min 超出容差 "
                    f"(ahead>{tol_ahead_min}min / behind>{tol_behind_h}h)"
                )
            else:
                source = "api_metadata"

        rows.append(
            {
                "session_id": session,
                "site": r["site_static"],
                "garage": r["garage"],
                "station": r["stationID"],
                "static_file": static_file,
                "first_observation_utc": first_ts,
                "api_connection_time_raw": api_raw,
                "api_connection_time_utc": api_ts.isoformat() if api_ts else None,
                "connection_time_source": source,
                "anomaly_reason": anomaly_reason,
            }
        )

    audit = pd.DataFrame(rows).sort_values(["site", "session_id"]).reset_index(drop=True)
    summary = {
        "matched": int(len(audit)),
        "api_metadata": int((audit["connection_time_source"] == "api_metadata").sum()),
        "fallback": int((audit["connection_time_source"] == "first_observation_fallback").sum()),
        "anomaly": int((audit["connection_time_source"] == "anomaly").sum()),
        "rule": audit_cfg["rule"],
    }
    return audit, summary


def build_quality_summary(
    manifest: pd.DataFrame,
    index_df: pd.DataFrame,
    conn_summary: dict[str, Any],
    audit_df: pd.DataFrame,
    acn: Path,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """聚合数据质量 + stop-line 判定（E0F-01 只审计，不出模型特征/field_mode_registry/pool 表）。"""
    files = len(manifest)
    rows_total = int(manifest["rows"].sum())
    read_fail = int((~manifest["read_ok"]).sum())
    gzip_fail = int((~manifest["gzip_ok"]).sum())
    trailing = int(manifest["trailing_garbage"].sum())
    short = int(manifest["short_file"].sum())
    dup_files = int((manifest["n_dup_ts"] > 0).sum())
    reversed_files = int((manifest["n_reversed"] > 0).sum())
    severe = int(manifest["severe_gap"].sum())

    # 交叉校验：与冻结 index 的一致性
    cross = {
        "rows_match": int(manifest["rows_match_index"].sum()),
        "rows_mismatch": int((~manifest["rows_match_index"]).sum()),
    }
    # 覆盖汇总
    coverage: dict[str, Any] = {}
    for key in _COL_KEY.values():
        col = f"has_{key}"
        n = int(manifest[col].sum())
        coverage[key] = {"files": n, "ratio": round(n / max(files, 1), 4)}
    coverage["short_files"] = {"files": short, "ratio": round(short / max(files, 1), 4)}

    energy = _energy_consistency_audit(acn)
    power_stats = _power_source_stats(manifest)

    stop_lines = _stop_line_verdict(
        manifest=manifest,
        index_df=index_df,
        read_fail=read_fail,
        gzip_fail=gzip_fail,
        dup_files=dup_files,
        severe=severe,
        energy=energy,
        cfg=cfg,
    )

    summary = {
        "audit_scope": "input_quality_only_no_split_no_field_registry",
        "files_total": files,
        "rows_total": rows_total,
        "read_ok": files - read_fail,
        "read_fail": read_fail,
        "gzip_ok": files - gzip_fail,
        "gzip_fail": gzip_fail,
        "trailing_garbage_files": trailing,
        "short_files": short,
        "dup_ts_files": dup_files,
        "reversed_ts_files": reversed_files,
        "severe_gap_files": severe,
        "by_site": power_stats,
        "coverage": coverage,
        "energy_consistency": energy,
        "cross_check_vs_index": cross,
        "connection_time": conn_summary,
        "connection_time_anomalies": _anomaly_list(audit_df),
        "stop_lines": stop_lines,
    }
    return summary


def _anomaly_list(audit_df: pd.DataFrame) -> list[dict[str, Any]]:
    if audit_df.empty:
        return []
    anom = audit_df[audit_df["connection_time_source"] == "anomaly"]
    cols = [
        "session_id", "site", "static_file", "api_connection_time_raw",
        "first_observation_utc", "anomaly_reason",
    ]
    return [
        {str(k): v for k, v in rec.items()}
        for rec in anom[cols].to_dict("records")
    ]


def _energy_consistency_audit(acn: Path) -> dict[str, Any]:
    """能量一致性：聚合可用性 + 中位偏差（caltech/office001 高可信；jpl 会话级离群过滤）。"""
    ecr = acn / "quality" / "energy_consistency_report.csv"
    if not ecr.exists():
        return {"available": False, "reason": "missing energy_consistency_report.csv"}
    df = pd.read_csv(ecr)
    df["rel_dev"] = (
        (df["integrated_kwh"] - df["api_kwh"]).abs() / df["api_kwh"].replace(0, pd.NA)
    ).astype(float)
    by_site: dict[str, Any] = {}
    for site, grp in df.groupby("site"):
        vals = grp["rel_dev"].dropna()
        by_site[str(site)] = {
            "sessions": int(len(grp)),
            "median_rel_dev": round(float(vals.median()), 4) if not vals.empty else None,
            "p95_rel_dev": round(float(vals.quantile(0.95)), 4) if not vals.empty else None,
        }
    return {"available": True, "by_site": by_site}


def _stop_line_verdict(
    manifest: pd.DataFrame,
    index_df: pd.DataFrame,
    read_fail: int,
    gzip_fail: int,
    dup_files: int,
    severe: int,
    energy: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """停止线判定（e0_full.yaml stop_lines 冻结条件转布尔检查；触发则停，不继续后续任务）。"""
    files = len(manifest)
    checks: dict[str, Any] = {}

    # 1) manifest 数量与哈希：index 行数必须等于冻结值
    expected = cfg["inputs"]["manifests"]["static_file_index_rows"]
    checks["manifest_count"] = {
        "ok": files == expected,
        "actual": files,
        "expected": expected,
    }

    # 2) 大规模文件读取失败：失败率 <= 1%
    fail_rate = (read_fail + gzip_fail) / max(files, 1)
    checks["read_failure_rate"] = {
        "ok": fail_rate <= 0.01,
        "actual": round(fail_rate, 5),
        "rule": "read_fail+gzip_fail <= 1%",
    }

    # 3) 同一会话存在无法解释的重叠记录：文件内重复时间戳必须为 0
    checks["dup_ts_within_file"] = {
        "ok": dup_files == 0,
        "actual": dup_files,
        "rule": "文件内重复时间戳 == 0",
    }

    # 4) 数据缺失集中在关键站点/月份：严重缺口文件占比 <= 5%
    severe_rate = severe / max(files, 1)
    checks["severe_gap_rate"] = {
        "ok": severe_rate <= 0.05,
        "actual": round(severe_rate, 5),
        "rule": "严重缺口文件占比 <= 5%",
    }

    # 5) 能量积分偏差系统性漂移：caltech/office001 中位偏差 < 1%
    energy_ok = True
    energy_detail: dict[str, Any] = {}
    if energy.get("available"):
        for site in ("caltech", "office001"):
            m = energy["by_site"].get(site, {}).get("median_rel_dev")
            energy_detail[site] = m
            if m is not None and m >= 0.01:
                energy_ok = False
    checks["energy_drift"] = {
        "ok": energy_ok,
        "detail": energy_detail,
        "rule": "caltech/office001 中位偏差 < 1%",
    }

    passed = all(v.get("ok", False) for v in checks.values())
    return {"passed": passed, "checks": checks}


def _decompress_text(raw: bytes) -> bytes:
    """zlib 解压（兼容尾部垃圾文件），供重复时间戳分类复用。"""
    d = zlib.decompressobj(zlib.MAX_WBITS | 16)
    try:
        out = d.decompress(raw)
        if d.unconsumed_tail:
            out += d.unconsumed_tail
        return out
    except zlib.error:
        return _decompress_first_gzip_member(raw)


def classify_dup_ts(
    manifest: pd.DataFrame,
    static_root: str | Path,
    out_csv: str | Path | None = None,
) -> dict[str, Any]:
    """重复时间戳分类：同秒多次采样（可解释） vs 逐字节相同行（可疑重叠）。

    输入 manifest 的 n_dup_ts 只标记"存在重复"，本函数重读含重复的文件做精细分类：
    - 相同 timestamp 的若干行若逐字节不同 → 亚秒级采样（可解释，信息性指标）；
    - 相同 timestamp 的若干行存在逐字节相同 → 可疑重叠（报告但不删除，只读输入）。
    返回汇总 dict；out_csv 给出逐文件 identical_dup_rows 明细（可复现）。
    """
    dup = manifest[manifest["n_dup_ts"] > 0]
    root = Path(static_root)
    rows_out: list[dict[str, Any]] = []
    extra_identical = 0
    extra_distinct = 0
    files_with_identical = 0
    for _, r in dup.iterrows():
        text = _decompress_text((root / r["logical_path"]).read_bytes())
        lines = text.decode("utf-8", errors="replace").splitlines()
        data = [ln for ln in lines[1:] if ln.strip()]
        seen: dict[str, list[str]] = {}
        for ln in data:
            seen.setdefault(ln.split(",", 1)[0], []).append(ln)
        file_identical = 0
        file_distinct = 0
        for group in seen.values():
            if len(group) < 2:
                continue
            n_unique = len(set(group))
            file_identical += len(group) - n_unique
            file_distinct += n_unique - 1
        extra_identical += file_identical
        extra_distinct += file_distinct
        if file_identical:
            files_with_identical += 1
        rows_out.append(
            {
                "logical_path": r["logical_path"],
                "n_dup_ts": int(r["n_dup_ts"]),
                "identical_dup_rows": file_identical,
                "same_second_distinct_samples": file_distinct,
            }
        )

    if out_csv is not None:
        Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows_out).to_csv(out_csv, index=False)
    return {
        "dup_ts_files": int(len(dup)),
        "identical_dup_rows": extra_identical,
        "identical_dup_files": files_with_identical,
        "same_second_distinct_samples": extra_distinct,
        "classification_rule": "逐字节相同行 → 可疑重叠；同秒不同值 → 亚秒采样（可解释）",
    }


def run_e0f01(
    cfg_path: str | Path | None = None,
    workers: int = 1,
    reuse_manifest: bool = False,
) -> dict[str, Any]:
    """E0F-01 全量执行：构建 manifest → 质量汇总 → 连接时间审计 → 冻结四个产物。

    产物：
    - data_registry/e0_full_source_manifest.parquet
    - data_registry/e0_full_quality_summary.json
    - data_registry/e0_full_baseline.json
    - reports/E0_Full_input_audit.md

    reuse_manifest=True 时复用已存在的 manifest（迭代用），默认全量重扫保证确定性。
    """
    cfg = load_yaml(cfg_path or (Path(__file__).resolve().parents[3] / "configs" / "e0_full.yaml"))
    acn = acn_project_dir()
    static_root = static_root_dir()
    impl_root = Path(__file__).resolve().parents[3]

    index_df = pd.read_csv(acn / "manifests" / "static_file_index.csv", dtype=str)
    api_meta = pd.read_csv(acn / "manifests" / "api_metadata_index.csv", dtype=str)
    mapping = pd.read_csv(acn / "manifests" / "static_api_mapping.csv", dtype=str)

    manifest_out = impl_root / "data_registry" / "e0_full_source_manifest.parquet"
    if reuse_manifest and manifest_out.exists():
        manifest = pd.read_parquet(manifest_out)
    else:
        manifest = build_source_manifest(
            index_df, static_root, cfg=ScanConfig.from_cfg(cfg), workers=workers
        )
        manifest_out.parent.mkdir(parents=True, exist_ok=True)
        manifest.to_parquet(manifest_out, index=False)

    audit_df, conn_summary = audit_connection_time(mapping, api_meta, manifest, cfg)
    audit_out = impl_root / "data_registry" / "e0_full_connection_time_audit.parquet"
    audit_out.parent.mkdir(parents=True, exist_ok=True)
    if not audit_df.empty:
        audit_df.to_parquet(audit_out, index=False)

    quality = build_quality_summary(manifest, index_df, conn_summary, audit_df, acn, cfg)
    quality["manifest_sha256"] = manifest_hash(manifest)

    dup_cls = classify_dup_ts(
        manifest,
        static_root,
        out_csv=impl_root / "data_registry" / "e0_full_dup_ts_classification.csv",
    )
    quality["dup_ts_classification"] = dup_cls

    quality_out = impl_root / "data_registry" / "e0_full_quality_summary.json"
    quality_out.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")

    from patent_preexperiment.e0_full.baseline import build_e0_full_baseline

    baseline_out = impl_root / "data_registry" / "e0_full_baseline.json"
    build_e0_full_baseline(
        out=baseline_out,
        manifest_hash_hex=quality["manifest_sha256"],
        config=cfg,
    )

    _write_audit_report(quality, impl_root / "reports" / "E0_Full_input_audit.md", cfg)

    return {
        "manifest": str(manifest_out),
        "quality": str(quality_out),
        "baseline": str(baseline_out),
    }


def _write_audit_report(quality: dict[str, Any], out: Path, cfg: dict[str, Any]) -> None:
    lines = [
        "# E0-Full 输入数据审计（E0F-01）",
        "",
        f"- 审计范围：{quality['audit_scope']}",
        f"- 文件总数：{quality['files_total']}，数据行：{quality['rows_total']:,}",
        f"- read_ok：{quality['read_ok']} / fail {quality['read_fail']}"
        f"；gzip_ok：{quality['gzip_ok']} / fail {quality['gzip_fail']}",
        f"- 短文件：{quality['short_files']}；文件内重复时间戳文件：{quality['dup_ts_files']}；",
        f"  倒序文件：{quality['reversed_ts_files']}；严重缺口文件：{quality['severe_gap_files']}",
        f"- manifest_sha256：{quality['manifest_sha256']}",
        "",
        "## 字段覆盖",
        "",
        "| 字段 | 文件数 | 比例 |",
        "|---|---|---|",
    ]
    for key, v in quality["coverage"].items():
        lines.append(f"| {key} | {v['files']} | {v['ratio']:.2%} |")
    lines += [
        "",
        "## 站点功率可用性（measured/computed/estimated 判定）",
        "",
        "| site | files | measured_power | voltage×current | current_only(est) | pilot | state |",
        "|---|---|---|---|---|---|---|",
    ]
    for site, v in quality["by_site"].items():
        lines.append(
            f"| {site} | {v['files']} | {v['measured_power']} | {v['computed_voltage_current']} | "
            f"{v['estimated_current_only']} | {v['pilot_available']} | {v['state_available']} |"
        )
    lines += ["", "## 能量一致性（中位相对偏差）", ""]
    if quality["energy_consistency"].get("available"):
        for site, v in quality["energy_consistency"]["by_site"].items():
            lines.append(
                f"- {site}：median={v['median_rel_dev']} "
                f"p95={v['p95_rel_dev']}（{v['sessions']} 会话）"
            )
    else:
        lines.append(f"- 不可用：{quality['energy_consistency'].get('reason')}")
    lines += ["", "## connectionTime 审计（只审计不切分）", ""]
    ct = quality["connection_time"]
    lines.append(
        f"- matched {ct['matched']}：api_metadata={ct['api_metadata']}，"
        f"first_observation_fallback={ct['fallback']}，anomaly={ct['anomaly']}"
    )
    lines.append(f"- 规则：{ct['rule']}")
    dup = quality.get("dup_ts_classification")
    if dup:
        lines += ["", "## 重复时间戳分类（对冻结 stop-line 的证据补充）", ""]
        lines.append(
            f"- 含重复时间戳文件：{dup['dup_ts_files']}；"
            f"同秒不同值（亚秒采样，可解释）：{dup['same_second_distinct_samples']} 行；"
            f"逐字节相同行（可疑重叠）：{dup['identical_dup_rows']} 行"
            f"（分布于 {dup['identical_dup_files']} 个文件）"
        )
        lines.append(f"- 规则：{dup['classification_rule']}")
    lines += ["", "## 停止线判定", ""]
    for name, check in quality["stop_lines"]["checks"].items():
        lines.append(f"- {name}：{'PASS' if check['ok'] else 'FAIL'}（{check}）")
    lines.append("")
    lines.append(f"## 总体：{'PASS' if quality['stop_lines']['passed'] else 'STOP'}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
