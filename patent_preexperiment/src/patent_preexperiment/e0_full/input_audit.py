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
import re
import zlib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.allocation.opportunity import (
    build_cycles,
    candidate_windows,
    compute_pool_stats,
    compute_proxies,
    eligible_mask,
)
from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.io.paths import acn_project_dir, static_root_dir
from patent_preexperiment.io.static import read_static_csv
from patent_preexperiment.response.session import aggregate_session_minute, derive_power

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

    site_mapping_audit = _site_mapping_audit(manifest, cfg)

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
        "site_mapping_audit": site_mapping_audit,
        "stop_lines": stop_lines,
    }
    return summary


def _site_mapping_audit(manifest: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    """site raw→canonical 映射审计（审查结论10 P1）：全部 raw site 必须能映射到 canonical。"""
    sm = cfg.get("site_mapping", {})
    table = sm.get("raw_to_canonical", {})
    raw_counts = manifest["site"].astype(str).value_counts().to_dict()
    canonical_counts: dict[str, int] = {}
    unmapped: list[str] = []
    for raw_v, n in raw_counts.items():
        raw = str(raw_v)
        canonical = site_canonical(raw, sm)
        if canonical == raw and raw not in table:
            unmapped.append(raw)
        canonical_counts[canonical] = canonical_counts.get(canonical, 0) + n
    return {
        "raw_sites": {str(k): int(v) for k, v in raw_counts.items()},
        "canonical_sites": {str(k): int(v) for k, v in canonical_counts.items()},
        "unmapped_raw": sorted(unmapped),
        "mapping_ok": not unmapped,
        "rule": sm.get(
            "rule",
            "site_canonical 经 site_mapping.raw_to_canonical 生成；"
            "registry 保留 site_raw 与 site_canonical 两列",
        ),
    }


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
    #    （审查结论10 P0-2：本检查是对该冻结条件更严格的实现解释；分类证据见 dup_ts_classification，
    #     不得删检查或改阈值，需 STOP 后的口径澄清 gate resolution 才可解锁）
    checks["dup_ts_within_file"] = {
        "ok": dup_files == 0,
        "actual": dup_files,
        "rule": "文件内重复时间戳 == 0",
        "note": "对 stop_lines 冻结条件'同一会话存在无法解释的重叠记录'的实现解释",
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


_MONTH_RE = re.compile(r"-(\d{4})-(\d{2})-(\d{2})T")


def _month_from_logical_path(logical_path: str) -> str | None:
    """从 ACN 文件名嵌入时间提取 YYYY-MM（如 1-1-178-817-2019-09-25T12-27-05-…）。"""
    m = _MONTH_RE.search(logical_path)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _is_zero_idle_row(line: str) -> bool:
    """0.0 空闲心跳行：时间戳之后所有字段为空或数值为 0（如 '2019-…,0.0,,,,,'）。"""
    for field in line.split(",")[1:]:
        field = field.strip()
        if not field:
            continue
        try:
            if float(field) != 0.0:
                return False
        except ValueError:
            return False
    return True


def site_canonical(site_raw: str, site_mapping: dict[str, Any]) -> str:
    """raw site → canonical site（审查结论10 P1；registry 保留 site_raw/site_canonical 两列）。

    映射来自 e0_full.yaml site_mapping.raw_to_canonical；未登记 raw 原样返回（上游会报警）。
    """
    table = site_mapping.get("raw_to_canonical", {})
    return str(table.get(site_raw, site_raw))


def file_role(
    site_raw: str,
    garage: str,
    month: str | None,
    site_mapping: dict[str, Any],
    role_months: dict[str, Any],
) -> str:
    """文件级 K1 role 分类（审查结论10 P0-2）：用于判断 exact duplicate 是否污染 R1 证据。

    审查结论11 P1：role 名只表述"月份窗口代理"，不直接等同"最终样本角色"——
    caltech_main_window / jpl_boundary_window / jpl_current_only_window /
    jpl_other / caltech_other / office_external / other。
    真正进入样本的 eligibility（has_current/has_pilot/…）逐文件单独登记在分类明细列。
    """
    canonical = site_canonical(site_raw, site_mapping)
    main = set(role_months.get("caltech_main_window", []))
    boundary = set(role_months.get("jpl_boundary_window", []))
    current_only = set(role_months.get("jpl_current_only_window", []))
    if canonical == "office001":
        return "office_external"
    if canonical == "caltech":
        if garage == "California_Garage_01" and month in main:
            return "caltech_main_window"
        return "caltech_other"
    if canonical == "jpl":
        if garage == "Arroyo_Garage_01" and month in boundary:
            return "jpl_boundary_window"
        if garage == "Arroyo_Garage_01" and month in current_only:
            return "jpl_current_only_window"
        return "jpl_other"
    return "other"


def classify_dup_ts(
    manifest: pd.DataFrame,
    static_root: str | Path,
    out_csv: str | Path | None = None,
    site_mapping: dict[str, Any] | None = None,
    role_months: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """重复时间戳分类（审查结论10 P0-2 措辞与结构）。

    输入 manifest 的 n_dup_ts 只标记"存在重复"，本函数只读重扫含重复的文件做精细分类：
    - 同一记录时间戳、不同观测值 → same_timestamp_distinct_rows（保留进入确定性分钟聚合；
      具体采样机制未被当前数据证明，不作"亚秒采样"断言）；
    - 同一记录时间戳、逐字节相同行 → identical_dup_rows（可疑重叠；保留不删，派生层按冻结
      规则 collapse）；再按内容分 identical_zero_idle_rows / identical_nonzero_rows。
    明细 CSV 含 site_raw/site_canonical/garage/station/month/role，并按 role×month 汇总。
    审查结论11 P1：明细逐文件登记 eligibility（has_current/has_pilot/has_voltage/has_power），
    role 仅作"月份窗口"代理，不直接等同"最终样本角色"。
    """
    mapping = site_mapping or {}
    rmonths = role_months or {}
    dup = manifest[manifest["n_dup_ts"] > 0]
    root = Path(static_root)
    rows_out: list[dict[str, Any]] = []
    extra_identical = 0
    extra_identical_zero = 0
    extra_identical_nonzero = 0
    extra_distinct = 0
    files_with_identical = 0
    failed: list[str] = []
    for _, r in dup.iterrows():
        lp = str(r["logical_path"])
        month = _month_from_logical_path(lp)
        if month is None:
            t = str(r.get("time_min") or "")
            month = t[:7] if len(t) >= 7 else None
        site_raw = str(r.get("site") or "")
        garage = str(r.get("garage") or "")
        station = str(r.get("station") or "")
        try:
            text = _decompress_text((root / lp).read_bytes())
        except OSError:
            failed.append(lp)
            continue
        lines = text.decode("utf-8", errors="replace").splitlines()
        data = [ln for ln in lines[1:] if ln.strip()]
        seen: dict[str, list[str]] = {}
        for ln in data:
            seen.setdefault(ln.split(",", 1)[0], []).append(ln)
        file_identical = 0
        file_zero = 0
        file_nonzero = 0
        file_distinct = 0
        for group in seen.values():
            if len(group) < 2:
                continue
            counts: dict[str, int] = {}
            for ln in group:
                counts[ln] = counts.get(ln, 0) + 1
            for ln, cnt in counts.items():
                if cnt < 2:
                    continue
                n_id = cnt - 1
                file_identical += n_id
                if _is_zero_idle_row(ln):
                    file_zero += n_id
                else:
                    file_nonzero += n_id
            file_distinct += len(counts) - 1
        extra_identical += file_identical
        extra_identical_zero += file_zero
        extra_identical_nonzero += file_nonzero
        extra_distinct += file_distinct
        if file_identical:
            files_with_identical += 1
        rows_out.append(
            {
                "logical_path": lp,
                "site_raw": site_raw,
                "site_canonical": site_canonical(site_raw, mapping),
                "garage": garage,
                "station": station,
                "month": month,
                "role": file_role(site_raw, garage, month, mapping, rmonths),
                "has_current": bool(r.get("has_current", False)),
                "has_pilot": bool(r.get("has_pilot", False)),
                "has_voltage": bool(r.get("has_voltage", False)),
                "has_power": bool(r.get("has_power", False)),
                "n_dup_ts": int(r["n_dup_ts"]),
                "identical_dup_rows": file_identical,
                "identical_zero_idle_rows": file_zero,
                "identical_nonzero_rows": file_nonzero,
                "same_timestamp_distinct_rows": file_distinct,
            }
        )

    cols = [
        "logical_path", "site_raw", "site_canonical", "garage", "station", "month",
        "role", "has_current", "has_pilot", "has_voltage", "has_power",
        "n_dup_ts", "identical_dup_rows", "identical_zero_idle_rows",
        "identical_nonzero_rows", "same_timestamp_distinct_rows",
    ]
    df_out = pd.DataFrame(rows_out, columns=cols) if rows_out else pd.DataFrame(columns=cols)
    if out_csv is not None:
        Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
        df_out.to_csv(out_csv, index=False)

    def _agg(sub: pd.DataFrame) -> dict[str, Any]:
        return {
            "files": int(len(sub)),
            "identical_dup_rows": int(sub["identical_dup_rows"].sum()),
            "identical_zero_idle_rows": int(sub["identical_zero_idle_rows"].sum()),
            "identical_nonzero_rows": int(sub["identical_nonzero_rows"].sum()),
            "same_timestamp_distinct_rows": int(sub["same_timestamp_distinct_rows"].sum()),
        }

    by_site: dict[str, Any] = {}
    by_role: dict[str, Any] = {}
    by_role_month: dict[str, Any] = {}
    by_month: dict[str, Any] = {}
    if len(df_out):
        by_site = {str(k): _agg(g) for k, g in df_out.groupby("site_canonical")}
        by_role = {str(k): _agg(g) for k, g in df_out.groupby("role")}
        by_month = {str(k): _agg(g) for k, g in df_out.groupby("month")}
        for (role, m), g in df_out.groupby(["role", "month"]):
            by_role_month.setdefault(str(role), {})[str(m)] = _agg(g)
    return {
        "dup_ts_files": int(len(dup)),
        "identical_dup_rows": extra_identical,
        "identical_zero_idle_rows": extra_identical_zero,
        "identical_nonzero_rows": extra_identical_nonzero,
        "identical_dup_files": files_with_identical,
        "same_timestamp_distinct_rows": extra_distinct,
        "files_failed": len(failed),
        "by_site": by_site,
        "by_role": by_role,
        "by_role_month": by_role_month,
        "by_month": by_month,
        "classification_rule": (
            "逐字节相同行 → 可疑重叠（保留不删，派生层按冻结规则 collapse）；"
            "同一记录时间戳不同观测值 → 保留进入确定性分钟聚合；"
            "采样机制未被当前数据证明"
        ),
    }


_AGG_MEAN_FIELDS = ("current", "power", "pilot")


def _parse_static_rows(text: bytes) -> list[dict[str, Any]]:
    """解析静态 csv 文本为行记录（只含可解析数值列，缺列跳过；供影响量检查用）。"""
    header = text.split(b"\n", 1)[0]
    cols = header.decode("utf-8", errors="replace").strip().split(",")
    col_idx: dict[str, int] = {}
    for i, c in enumerate(cols):
        key = c.strip()
        if key in _COL_KEY:
            col_idx[_COL_KEY[key]] = i
    rows: list[dict[str, Any]] = []
    for line in text.split(b"\n")[1:]:
        if not line.strip():
            continue
        parts = line.split(b",")
        try:
            ts = datetime.fromisoformat(parts[0].decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            continue
        rec: dict[str, Any] = {"ts": ts}
        for key, idx in col_idx.items():
            if idx < len(parts) and parts[idx].strip():
                try:
                    rec[key] = float(parts[idx])
                except ValueError:
                    pass
        rows.append(rec)
    return rows


def _canonical_df_from_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """行记录 → 规范化静态 df（列名与 io/static.read_static_csv 一致，含电压/功率列）。

    供冻结 1min/5min 派生管线复用（derive_power 是唯一 canonical 功率派生实现）。
    """
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "ts" not in df.columns:
        return pd.DataFrame()
    df = df.rename(columns={"ts": "timestamp"})
    rename = {
        "current": "current_a",
        "pilot": "pilot_a",
        "voltage": "voltage_v",
        "energy": "energy_kwh",
        "power": "power_kw",
    }
    for k, v in rename.items():
        if k in df.columns:
            df[v] = df[k]
    for col in ("current_a", "pilot_a", "voltage_v", "energy_kwh", "power_kw"):
        if col not in df.columns:
            df[col] = np.nan
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["state"] = pd.NA
    return df[["timestamp", "current_a", "pilot_a", "voltage_v", "state", "energy_kwh", "power_kw"]]


def _minute_actual_power_kw(rows: list[dict[str, Any]], rated_v: float) -> pd.Series:
    """行记录 → 派生 actual_power_kw 的 1-min 均值（冻结优先级 measured→computed→estimated）。"""
    df = _canonical_df_from_rows(rows)
    if df.empty or "current_a" not in df.columns:
        return pd.Series(dtype="float64")
    df = df.dropna(subset=["current_a"]).copy()
    df = derive_power(df, rated_v)
    df["minute"] = df["timestamp"].dt.floor("min")
    return df.groupby("minute")["actual_power_kw"].mean()


def _minute_table_from_rows(
    rows: list[dict[str, Any]],
    rated_v: float,
    session_id: str,
    station_id: str,
    site: str,
    garage: str,
) -> pd.DataFrame:
    """行记录 → 生产路径 1 分钟会话表（aggregate_session_minute，冻结口径）。"""
    df = _canonical_df_from_rows(rows)
    if df.empty:
        return df
    return aggregate_session_minute(
        df, rated_v, session_id=session_id, station_id=station_id, site=site, garage=garage
    )


def _minute_impact(
    keep_rows: list[dict[str, Any]],
    coll_rows: list[dict[str, Any]],
    rated_v: float | None = None,
) -> dict[str, Any]:
    """1-min 聚合下 keep vs collapse 的逐字段差值。

    fields：current/power/pilot 取均值、energy 取末值（原始 CSV 字段）。
    derived_power：当 rated_v 给定且两侧都有可派生 current 时，用冻结优先级
    derive_power 在派生层比较 actual_power_kw（JPL current-only 即 I×192.7/1000，审查结论11 P0）。
    """
    zero_stats: dict[str, Any] = {
        f: {"affected_minutes": 0, "max_abs_diff": 0.0, "mean_abs_diff": 0.0}
        for f in (*_AGG_MEAN_FIELDS, "energy")
    }
    if not keep_rows:
        return {"fields": zero_stats, "derived_power": None}
    keep_df = pd.DataFrame(keep_rows)
    coll_df = pd.DataFrame(coll_rows)
    keep_df["ts"] = pd.to_datetime(keep_df["ts"], utc=True)
    coll_df["ts"] = pd.to_datetime(coll_df["ts"], utc=True)
    keep_df["minute"] = keep_df["ts"].dt.floor("min")
    coll_df["minute"] = coll_df["ts"].dt.floor("min")
    fields: dict[str, Any] = {}
    for f in _AGG_MEAN_FIELDS:
        if f not in keep_df.columns or f not in coll_df.columns:
            fields[f] = dict(zero_stats[f])
            continue
        ka = keep_df.groupby("minute")[f].mean()
        ca = coll_df.groupby("minute")[f].mean()
        fields[f] = _diff_stats((ka - ca).abs())
    if "energy" in keep_df.columns and "energy" in coll_df.columns:
        ke = keep_df.groupby("minute")["energy"].last()
        ce = coll_df.groupby("minute")["energy"].last()
        fields["energy"] = _diff_stats((ke - ce).abs())
    else:
        fields["energy"] = dict(zero_stats["energy"])

    derived_power: dict[str, Any] | None = None
    if rated_v is not None:
        kp = _minute_actual_power_kw(keep_rows, rated_v)
        cp = _minute_actual_power_kw(coll_rows, rated_v)
        if len(kp) or len(cp):
            derived_power = {
                "diff_minutes": (kp - cp).abs(),
                "n_minutes_keep": int(len(kp)),
                "n_minutes_collapse": int(len(cp)),
            }
    return {"fields": fields, "derived_power": derived_power}


def _agg_power_diff(diffs: list[pd.Series]) -> dict[str, Any]:
    """按 role 汇总 derived_power 分钟绝对差（absolute/相对口径分开，避免把总差当平均差）。"""
    if not diffs:
        return {
            "affected_minutes": 0,
            "max_abs_diff_kw": 0.0,
            "p95_abs_diff_kw": 0.0,
            "mean_abs_diff_kw": 0.0,
            "total_abs_energy_diff_kwh": 0.0,
            "n_files_contributing": 0,
        }
    vals = pd.concat(diffs, axis=0).dropna().astype(float)
    if not len(vals):
        return {
            "affected_minutes": 0,
            "max_abs_diff_kw": 0.0,
            "p95_abs_diff_kw": 0.0,
            "mean_abs_diff_kw": 0.0,
            "total_abs_energy_diff_kwh": 0.0,
            "n_files_contributing": len(diffs),
        }
    return {
        "affected_minutes": int((vals > 0).sum()),
        "max_abs_diff_kw": round(float(vals.max()), 6),
        "p95_abs_diff_kw": round(float(vals.quantile(0.95)), 6),
        "mean_abs_diff_kw": round(float(vals.mean()), 6),
        "total_abs_energy_diff_kwh": round(float(vals.sum() / 60.0), 6),
        "n_files_contributing": len(diffs),
    }


def _diff_stats(diff: pd.Series) -> dict[str, Any]:
    vals = diff.dropna().astype(float)
    n = int(len(vals))
    if n == 0:
        return {"affected_minutes": 0, "max_abs_diff": 0.0, "mean_abs_diff": 0.0}
    return {
        "affected_minutes": int((vals > 0).sum()),
        "max_abs_diff": round(float(vals.max()), 9),
        "mean_abs_diff": round(float(vals.mean()), 9),
    }


def dup_collapse_impact(
    manifest: pd.DataFrame,
    static_root: str | Path,
    out_json: str | Path | None = None,
    site_mapping: dict[str, Any] | None = None,
    role_months: dict[str, Any] | None = None,
    rated_voltage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """exact-duplicate 保留 vs 派生层 collapse 的 1-min 影响量（审查结论10 建议3）。

    只读输入，永不修改原始文件。只扫描 identical_dup_rows>0 的文件；对每文件比较
    "保留全部行" 与 "collapse 逐字节相同行" 两种派生口径在 1-min 聚合下的差异
    （current/power/pilot 取均值、energy 取分钟末值），按 role 汇总。

    审查结论11 P0：原始 CSV power 列为空时"power 零影响"不成立——同一差异必须在派生层
    actual_power_kw（derive_power：measured→computed→estimated，rated_voltage 按 canonical
    site 从 e0_full.yaml power.rated_voltage 取）重新评估，否则 JPL current-only 的
    I×192.7/1000 传播被漏报。
    """
    mapping = site_mapping or {}
    rmonths = role_months or {}
    rated_v_by_site = rated_voltage or {}
    dup = manifest[manifest["n_dup_ts"] > 0]
    root = Path(static_root)
    file_stats: dict[str, dict[str, Any]] = {}
    for _, r in dup.iterrows():
        lp = str(r["logical_path"])
        try:
            text = _decompress_text((root / lp).read_bytes())
        except OSError:
            continue
        decoded = text.decode("utf-8", errors="replace")
        raw_lines = [ln for ln in decoded.splitlines()[1:] if ln.strip()]
        if not raw_lines:
            continue
        coll_lines = list(dict.fromkeys(raw_lines))
        if len(coll_lines) == len(raw_lines):
            continue
        keep_rows = _parse_static_rows(text)
        header = decoded.split("\n", 1)[0]
        coll_text = ("\n".join([header, *coll_lines]) + "\n").encode("utf-8")
        coll_rows = _parse_static_rows(coll_text)
        site_raw = str(r.get("site") or "")
        canonical = site_canonical(site_raw, mapping)
        rated_v = rated_v_by_site.get(canonical)
        impact = _minute_impact(keep_rows, coll_rows, rated_v=rated_v)
        month = _month_from_logical_path(lp)
        if month is None:
            t = str(r.get("time_min") or "")
            month = t[:7] if len(t) >= 7 else None
        file_stats[lp] = {
            "role": file_role(site_raw, str(r.get("garage") or ""), month, mapping, rmonths),
            "canonical_site": canonical,
            "rated_v": rated_v,
            "identical_dup_rows": len(raw_lines) - len(coll_lines),
            "fields": impact["fields"],
            "derived_power": impact["derived_power"],
        }

    by_role: dict[str, Any] = {}
    totals: dict[str, Any] = {
        f: {"affected_minutes": 0, "max_abs_diff": 0.0, "mean_abs_diff": 0.0}
        for f in (*_AGG_MEAN_FIELDS, "energy")
    }
    role_pwr_diffs: dict[str, list[pd.Series]] = {}
    all_pwr_diffs: list[pd.Series] = []
    for _, st in file_stats.items():
        role = st["role"]
        br = by_role.setdefault(
            role,
            {
                "files": 0,
                "affected_files_any_field": 0,
                "fields": {
                    f: {"affected_minutes": 0, "max_abs_diff": 0.0, "mean_abs_diff": 0.0}
                    for f in (*_AGG_MEAN_FIELDS, "energy")
                },
            },
        )
        br["files"] += 1
        affected_any = any(s["affected_minutes"] > 0 for s in st["fields"].values())
        if affected_any:
            br["affected_files_any_field"] += 1
        for f, s in st["fields"].items():
            br["fields"][f]["affected_minutes"] += s["affected_minutes"]
            br["fields"][f]["max_abs_diff"] = max(
                br["fields"][f]["max_abs_diff"], s["max_abs_diff"]
            )
            br["fields"][f]["mean_abs_diff"] += s["mean_abs_diff"]
            totals[f]["affected_minutes"] += s["affected_minutes"]
            totals[f]["max_abs_diff"] = max(totals[f]["max_abs_diff"], s["max_abs_diff"])
            totals[f]["mean_abs_diff"] += s["mean_abs_diff"]
        if st["derived_power"] is not None and st["derived_power"]["diff_minutes"] is not None:
            d = st["derived_power"]["diff_minutes"]
            role_pwr_diffs.setdefault(role, []).append(d)
            all_pwr_diffs.append(d)
    n_files = len(file_stats)
    if n_files:
        for br in by_role.values():
            for f in br["fields"]:
                br["fields"][f]["mean_abs_diff"] = round(
                    br["fields"][f]["mean_abs_diff"] / br["files"], 9
                )
        for f in totals:
            totals[f]["mean_abs_diff"] = round(totals[f]["mean_abs_diff"] / max(n_files, 1), 9)

    derived_power_summary: dict[str, Any] = {
        "rule": (
            "派生层 actual_power_kw（derive_power 冻结优先级 measured→computed→estimated，"
            "JPL current-only=rated 192.7×current/1000）；keep vs collapse 1-min 均值绝对差"
        ),
        "by_role": {role: _agg_power_diff(v) for role, v in sorted(role_pwr_diffs.items())},
        "overall": _agg_power_diff(all_pwr_diffs),
    }

    result: dict[str, Any] = {
        "scope": (
            "只扫描 identical_dup_rows>0 的文件；派生层 1-min 聚合："
            "current/power/pilot 取均值、energy 取分钟末值；"
            "actual_power_kw 按冻结功率优先级在派生层评估"
        ),
        "input_untouched": True,
        "files_scanned": n_files,
        "by_role": by_role,
        "overall_fields": totals,
        "derived_power": derived_power_summary,
    }
    if out_json is not None:
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(out_json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return result


# current-only 池预算代理（与 e3_lite.run JPL_PROX 冻结集一致：只含实际类代理，无 pilot 类）
_CURRENT_ONLY_PROXIES = ("A2_prev_actual", "A3_rolling_quantile")
_CURRENT_ONLY_MAIN = "A2_prev_actual"


def _current_only_e3_cand(min_df: pd.DataFrame, frozen_months: set[str]) -> pd.DataFrame:
    """分钟表 → current-only 池×周期 候选窗口表（E3-Lite 同管线，仅冻结月份）。"""
    cyc = build_cycles(min_df)
    pool = compute_pool_stats(cyc)
    prox = compute_proxies(cyc, pool)
    prox_m = prox[prox["month"].isin(frozen_months)]
    cand = candidate_windows(prox_m[eligible_mask(prox_m, list(_CURRENT_ONLY_PROXIES))])
    meta = prox_m[["site", "garage", "cycle", "day", "month"]].drop_duplicates()
    if len(cand):
        cand = cand.merge(meta, on=["site", "garage", "cycle"], how="left")
    return cand


def _day_rate_ci(
    cand: pd.DataFrame, proxy: str, seed: int, n_boot: int
) -> dict[str, Any]:
    """日等权率 + 日 cluster bootstrap 95%CI（与 e3_lite._day_bootstrap_ci 同口径）。"""
    daily = cand.groupby("day")[f"candidate_{proxy}"].mean()
    if len(daily) < 2:
        return {"n_days": int(len(daily)), "day_rate": None, "ci95": None}
    vals = daily.to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(daily), size=(n_boot, len(daily)))
    rates = vals[idx].mean(axis=1)
    return {
        "n_days": int(len(daily)),
        "day_rate": float(vals.mean()),
        "ci95": [float(np.percentile(rates, 2.5)), float(np.percentile(rates, 97.5))],
    }


def current_only_sensitivity(
    manifest: pd.DataFrame,
    static_root: str | Path,
    out_json: str | Path | None = None,
    site_mapping: dict[str, Any] | None = None,
    role_months: dict[str, Any] | None = None,
    rated_voltage: dict[str, Any] | None = None,
    p_on_kw: float = 0.5,
    e3_stop: dict[str, Any] | None = None,
    bootstrap_seed: int = 42,
    n_boot: int = 2000,
) -> dict[str, Any]:
    """审查结论11 P0：current-only 月份窗口 exact-duplicate 的 E3 门敏感性。

    exact-duplicate 在派生层被 collapse；本函数把"保留全部行 keep"与"collapse"两套 1min 表
    分别跑冻结 E3-Lite 管线（K1.2-A/C：A2_prev_actual 主基线，预算差值=候选窗口，无吸收假设），
    对比：low_power_state 占比（P_on_kw 阈值）、A2 周期加权/日等权候选率 + 日 cluster bootstrap
    95%CI、日候选能量占比中位数，以及候选/活跃窗口翻转数量；并判 E3 门在 keep/collapse 下是否
    翻转。只读输入，永不修改原始文件。
    """
    stop = e3_stop or {}
    lower_rate = float(stop.get("caltech_a2_daily_ci_lower_rate", 0.01))
    share_min = float(stop.get("daily_energy_share_each_pool", 0.005))
    mapping = site_mapping or {}
    rmonths = role_months or {}
    rated_v_by_site = rated_voltage or {}
    frozen_months = set(rmonths.get("jpl_current_only_window", []))
    root = Path(static_root)

    affected_files: list[dict[str, Any]] = []
    for _, r in manifest[manifest["n_dup_ts"] > 0].iterrows():
        lp = str(r["logical_path"])
        month = _month_from_logical_path(lp)
        if month is None:
            t = str(r.get("time_min") or "")
            month = t[:7] if len(t) >= 7 else None
        role = file_role(
            str(r.get("site") or ""), str(r.get("garage") or ""), month, mapping, rmonths
        )
        if role != "jpl_current_only_window":
            continue
        try:
            text = _decompress_text((root / lp).read_bytes())
        except OSError:
            continue
        decoded = text.decode("utf-8", errors="replace")
        raw_lines = [ln for ln in decoded.splitlines()[1:] if ln.strip()]
        if not raw_lines:
            continue
        coll_lines = list(dict.fromkeys(raw_lines))
        if len(coll_lines) == len(raw_lines):
            continue
        site_raw = str(r.get("site") or "")
        canonical = site_canonical(site_raw, mapping)
        rated_v = rated_v_by_site.get(canonical)
        if rated_v is None:
            continue
        keep_rows = _parse_static_rows(text)
        header = decoded.split("\n", 1)[0]
        coll_text = ("\n".join([header, *coll_lines]) + "\n").encode("utf-8")
        coll_rows = _parse_static_rows(coll_text)
        affected_files.append(
            {
                "logical_path": lp,
                "role": role,
                "rated_v": float(rated_v),
                "station_id": str(r.get("station") or ""),
                "garage": str(r.get("garage") or ""),
                "site": canonical,
                "keep_rows": keep_rows,
                "coll_rows": coll_rows,
            }
        )

    empty_ret: dict[str, Any] = {
        "scope": (
            "current-only 冻结月份窗口（jpl_current_only_window）内 exact-duplicate 文件，"
            "keep vs collapse 各跑冻结 E3-Lite 管线（A2_prev_actual 主基线）"
        ),
        "input_untouched": True,
        "files_scanned": 0,
        "files_with_identical_rows": 0,
        "low_power_state": {"keep": None, "collapse": None},
        "e3_a2": {"keep": None, "collapse": None},
        "flips": {"candidate_flips": 0, "n_candidate_rows": 0, "active_flips": 0},
        "gate": {
            "pass_candidate_rate_keep": False,
            "pass_candidate_rate_collapse": False,
            "pass_daily_share_keep": False,
            "pass_daily_share_collapse": False,
            "gate_flipped": False,
        },
    }
    if not affected_files:
        if out_json is not None:
            Path(out_json).parent.mkdir(parents=True, exist_ok=True)
            Path(out_json).write_text(
                json.dumps(empty_ret, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return empty_ret

    keep_min_list: list[pd.DataFrame] = []
    coll_min_list: list[pd.DataFrame] = []
    for af in affected_files:
        keep_min = _minute_table_from_rows(
            af["keep_rows"], af["rated_v"], af["logical_path"], af["station_id"],
            af["site"], af["garage"],
        )
        coll_min = _minute_table_from_rows(
            af["coll_rows"], af["rated_v"], af["logical_path"], af["station_id"],
            af["site"], af["garage"],
        )
        if not keep_min.empty:
            keep_min_list.append(keep_min)
        if not coll_min.empty:
            coll_min_list.append(coll_min)
    if not keep_min_list or not coll_min_list:
        if out_json is not None:
            Path(out_json).parent.mkdir(parents=True, exist_ok=True)
            Path(out_json).write_text(
                json.dumps(empty_ret, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return empty_ret

    keep_min = pd.concat(keep_min_list, ignore_index=True)
    coll_min = pd.concat(coll_min_list, ignore_index=True)

    def _low_power(min_df: pd.DataFrame) -> dict[str, Any]:
        n = int(len(min_df))
        if not n:
            return {"n_minutes": 0, "ratio": None}
        ratio = float((min_df["actual_power_kw"].fillna(0.0) <= p_on_kw).mean())
        return {"n_minutes": n, "ratio": ratio}

    def _e3_block(min_df: pd.DataFrame, cand: pd.DataFrame) -> dict[str, Any]:
        if not len(cand):
            return {
                "n_cycles": 0, "n_days": 0, "n_pool_months": 0,
                "cycle_weighted_rate": 0.0, "day_rate": None, "day_rate_ci95": None,
                "day_rate_ci_lower": None, "daily_energy_share_median": None,
                "daily_energy_share_mean": None, "candidate_energy_total_kwh": 0.0,
            }
        ev_day = min_df.copy()
        ev_day["day"] = ev_day["timestamp_utc"].astype(str).str[:10]
        ev_day_energy = ev_day.groupby("day")["actual_power_kw"].sum() / 60.0
        cand_day = cand.groupby("day")[f"candidate_energy_{_CURRENT_ONLY_MAIN}_kwh"].sum()
        share = cand_day.div(ev_day_energy.reindex(cand_day.index)).reindex(
            ev_day_energy.index
        ).fillna(0.0)
        ci = _day_rate_ci(cand, _CURRENT_ONLY_MAIN, bootstrap_seed, n_boot)
        return {
            "n_cycles": int(len(cand)),
            "n_days": int(cand["day"].nunique()),
            "n_pool_months": int(cand["month"].nunique()),
            "cycle_weighted_rate": float(cand[f"candidate_{_CURRENT_ONLY_MAIN}"].mean()),
            "day_rate": ci["day_rate"],
            "day_rate_ci95": ci["ci95"],
            "day_rate_ci_lower": float(ci["ci95"][0]) if ci["ci95"] else None,
            "daily_energy_share_median": round(float(share.median()), 6),
            "daily_energy_share_mean": round(float(share.mean()), 6),
            "candidate_energy_total_kwh": round(
                float(cand[f"candidate_energy_{_CURRENT_ONLY_MAIN}_kwh"].sum()), 6
            ),
        }

    keep_cand = _current_only_e3_cand(keep_min, frozen_months)
    coll_cand = _current_only_e3_cand(coll_min, frozen_months)
    keep_e3 = _e3_block(keep_min, keep_cand)
    coll_e3 = _e3_block(coll_min, coll_cand)

    keep_cyc = build_cycles(keep_min)
    coll_cyc = build_cycles(coll_min)

    n_cand_rows = 0
    candidate_flips = 0
    if len(keep_cand) and len(coll_cand):
        key = ["site", "garage", "cycle"]
        kk = keep_cand.set_index(key)[f"candidate_{_CURRENT_ONLY_MAIN}"]
        cc = coll_cand.set_index(key)[f"candidate_{_CURRENT_ONLY_MAIN}"]
        merged = kk.rename("keep").to_frame().join(cc.rename("collapse"), how="outer")
        merged["keep"] = merged["keep"].fillna(False)
        merged["collapse"] = merged["collapse"].fillna(False)
        n_cand_rows = int(len(merged))
        candidate_flips = int((merged["keep"] != merged["collapse"]).sum())

    active_flips = 0
    if len(keep_cyc) and len(coll_cyc):
        key = ["site", "garage", "session_id", "cycle"]
        kk = keep_cyc.set_index(key)["active"].rename("keep")
        cc = coll_cyc.set_index(key)["active"].rename("collapse")
        merged = kk.to_frame().join(cc, how="outer")
        merged["keep"] = merged["keep"].fillna(False)
        merged["collapse"] = merged["collapse"].fillna(False)
        active_flips = int((merged["keep"] != merged["collapse"]).sum())

    def _pass_rate(e3: dict[str, Any]) -> bool:
        lo = e3.get("day_rate_ci_lower")
        return bool(lo is not None and lo >= lower_rate)

    def _pass_share(e3: dict[str, Any]) -> bool:
        sh = e3.get("daily_energy_share_median")
        return bool(sh is not None and sh >= share_min)

    pass_rate_keep = _pass_rate(keep_e3)
    pass_rate_collapse = _pass_rate(coll_e3)
    pass_share_keep = _pass_share(keep_e3)
    pass_share_collapse = _pass_share(coll_e3)
    gate_flipped = (pass_rate_keep != pass_rate_collapse) or (
        pass_share_keep != pass_share_collapse
    )

    result: dict[str, Any] = {
        "scope": (
            "current-only 冻结月份窗口（jpl_current_only_window）内 exact-duplicate 文件，"
            "keep vs collapse 各跑冻结 E3-Lite 管线（K1.2-A/C A2_prev_actual 主基线，"
            "预算差值=候选窗口，无吸收假设）"
        ),
        "input_untouched": True,
        "p_on_kw": float(p_on_kw),
        "frozen_months": sorted(frozen_months),
        "proxy_main": _CURRENT_ONLY_MAIN,
        "files_scanned": len(affected_files),
        "files_with_identical_rows": len(affected_files),
        "low_power_state": {"keep": _low_power(keep_min), "collapse": _low_power(coll_min)},
        "e3_a2": {"keep": keep_e3, "collapse": coll_e3},
        "flips": {
            "candidate_flips": candidate_flips,
            "n_candidate_rows": n_cand_rows,
            "active_flips": active_flips,
        },
        "gate": {
            "rule": (
                f"日等权候选率日 cluster bootstrap 95%CI 下界 >= {lower_rate} 且 "
                f"日候选能量占比中位数 >= {share_min}（与 e0_full.yaml e3 停止线同值）"
            ),
            "pass_candidate_rate_keep": pass_rate_keep,
            "pass_candidate_rate_collapse": pass_rate_collapse,
            "pass_daily_share_keep": pass_share_keep,
            "pass_daily_share_collapse": pass_share_collapse,
            "gate_flipped": gate_flipped,
        },
    }
    if out_json is not None:
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(out_json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return result


# 审查结论12 冻结 E3-Lite JPL current-only 池复现基线（来自 e3_lite_summary.json / E3_Lite_gate.md）
_FROZEN_JPL_CURRENT_ONLY = {
    "n_cycles": 36736,
    "a2_cycle_weighted_rate": 0.39261215156794427,
    "a2_day_rate": 0.3623694692507855,
    "a2_day_rate_ci95": [0.32995762618758384, 0.395798678130819],
    "daily_energy_share_median": 0.038928678037374986,
    "gate": "PASS",
}
# 浮点复现容差（n_cycles/sessions 精确一致；比率允许微小数值误差）
_RATES_TOL = 1e-4
_SHARE_TOL = 5e-3


def _run_jpl_current_only_e3(
    minute_df: pd.DataFrame, frozen_months: set[str], seed: int, n_boot: int
) -> dict[str, Any]:
    """完整 JPL current-only 分钟母体 → 冻结 E3-Lite 管线（A2_prev_actual 主基线）。

    直接复用 E3-Lite 同一组函数（build_cycles→compute_pool_stats→compute_proxies
    →eligible_mask→candidate_windows），月过滤按冻结 cycle_month，meta 含 month_conn
    防止 merge fan-out。能量分母按 timestamp month ∈ frozen_months（与 e3_lite.run 同口径）。
    """
    prox_m_meta = ["site", "garage", "cycle", "day", "month", "month_conn"]
    cyc = build_cycles(minute_df)
    pool = compute_pool_stats(cyc)
    prox = compute_proxies(cyc, pool)
    prox_m = prox[prox["month"].isin(frozen_months)]
    elig = eligible_mask(prox_m, list(_CURRENT_ONLY_PROXIES))
    cand = candidate_windows(prox_m[elig])
    meta = prox_m[prox_m_meta].drop_duplicates()
    if len(cand):
        cand = cand.merge(meta, on=["site", "garage", "cycle"], how="left")
    ci = _day_rate_ci(cand, _CURRENT_ONLY_MAIN, seed, n_boot)
    ev = minute_df.copy()
    ev = ev[ev["timestamp_utc"].astype(str).str[:7].isin(frozen_months)]
    ev["day"] = ev["timestamp_utc"].astype(str).str[:10]
    ev_day_energy = ev.groupby("day")["actual_power_kw"].sum() / 60.0
    cand_day = cand.groupby("day")[f"candidate_energy_{_CURRENT_ONLY_MAIN}_kwh"].sum()
    share = cand_day.div(ev_day_energy.reindex(cand_day.index)).reindex(
        ev_day_energy.index
    ).fillna(0.0)
    return {
        "n_cycles": int(len(cand)),
        "n_days": int(cand["day"].nunique()) if len(cand) else 0,
        "n_pool_months": int(cand["month"].nunique()) if len(cand) else 0,
        "a2_cycle_weighted_rate": float(cand[f"candidate_{_CURRENT_ONLY_MAIN}"].mean())
        if len(cand)
        else 0.0,
        "a2_day_rate": ci["day_rate"],
        "a2_day_rate_ci95": ci["ci95"],
        "a2_day_rate_ci_lower": float(ci["ci95"][0]) if ci["ci95"] else None,
        "daily_energy_share_median": round(float(share.median()), 6) if len(share) else None,
        "daily_energy_share_mean": round(float(share.mean()), 6) if len(share) else None,
        "candidate_energy_total_kwh": round(
            float(cand[f"candidate_energy_{_CURRENT_ONLY_MAIN}_kwh"].sum()), 6
        )
        if len(cand)
        else 0.0,
        "_cand": cand,
        "_cyc": cyc,
    }


def current_only_full_pool_sensitivity(
    minute_table_path: str | Path,
    sample_registry_path: str | Path,
    classification_csv_path: str | Path,
    static_root: str | Path,
    out_json: str | Path | None = None,
    site_mapping: dict[str, Any] | None = None,
    role_months: dict[str, Any] | None = None,
    rated_voltage: dict[str, Any] | None = None,
    e3_stop: dict[str, Any] | None = None,
    bootstrap_seed: int = 42,
    n_boot: int = 2000,
    frozen_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """审查结论12 P0：冻结完整 JPL current-only 母体 keep-vs-collapse 敏感性。

    以冻结 K1 的完整 JPL current-only 分钟母体（lite_session_minute.parquet JPL 部分，
    即 E3-Lite 正式池构造用的同一母体）为基准。Keep 臂原样跑冻结 E3-Lite 管线，必须先
    复现历史冻结值（n_cycles=36736、A2≈39.3%、日率≈36.2%、CI≈[33.0,39.6]、能量占比≈3.9%、
    gate=PASS）；复现失败立即 STOP。Collapse 臂只替换真正属于冻结母体且含 exact-duplicate
    的会话分钟，其余数千会话逐字节与 Keep 一致，再跑同一完整池管线。比较两臂 gate verdict。

    不得用 54-file 子池代替完整冻结池；eligibility 以冻结 K1 sample 母体成员身份为准，
    窗口（jpl_current_only_window）只作定位辅助。只读输入，永不修改原始文件。
    """
    stop = e3_stop or {}
    lower_rate = float(stop.get("caltech_a2_daily_ci_lower_rate", 0.01))
    share_min = float(stop.get("daily_energy_share_each_pool", 0.005))
    frozen: dict[str, Any] = dict(frozen_baseline or _FROZEN_JPL_CURRENT_ONLY)
    frozen_months = set(role_months.get("jpl_current_only_window", [])) if role_months else set()

    keep_min = pd.read_parquet(minute_table_path)
    keep_min = keep_min[keep_min["site"] == "jpl"].copy()
    frozen_sessions = set(keep_min["session_id"].unique())

    # ---- Keep 臂：复现冻结 E3 ----
    keep_e3 = _run_jpl_current_only_e3(keep_min, frozen_months, bootstrap_seed, n_boot)
    keep_cand = keep_e3.pop("_cand")
    keep_cyc = keep_e3.pop("_cyc")

    def _close(a: Any, b: Any, tol: float) -> bool:
        if a is None or b is None:
            return a is None and b is None
        return abs(float(a) - float(b)) <= tol

    keep_reproduces = (
        keep_e3["n_cycles"] == int(frozen["n_cycles"])
        and _close(keep_e3["a2_cycle_weighted_rate"], frozen["a2_cycle_weighted_rate"], _RATES_TOL)
        and _close(keep_e3["a2_day_rate"], frozen["a2_day_rate"], _RATES_TOL)
        and keep_e3["a2_day_rate_ci95"] is not None
        and frozen["a2_day_rate_ci95"] is not None
        and _close(keep_e3["a2_day_rate_ci95"][0], frozen["a2_day_rate_ci95"][0], _RATES_TOL)
        and _close(keep_e3["a2_day_rate_ci95"][1], frozen["a2_day_rate_ci95"][1], _RATES_TOL)
        and keep_e3["daily_energy_share_median"] is not None
        and _close(
            keep_e3["daily_energy_share_median"], frozen["daily_energy_share_median"], _SHARE_TOL
        )
    )

    frozen_ref = {
        "n_cycles": int(frozen["n_cycles"]),
        "a2_cycle_weighted_rate": float(frozen["a2_cycle_weighted_rate"]),
        "a2_day_rate": float(frozen["a2_day_rate"]) if frozen["a2_day_rate"] is not None else None,
        "a2_day_rate_ci95": (
            [float(x) for x in frozen["a2_day_rate_ci95"]]
            if frozen["a2_day_rate_ci95"] is not None else None
        ),
        "daily_energy_share_median": (
            float(frozen["daily_energy_share_median"])
            if frozen["daily_energy_share_median"] is not None else None
        ),
        "gate": str(frozen["gate"]),
    }
    base: dict[str, Any] = {
        "scope": (
            "冻结完整 JPL current-only 分钟母体（lite_session_minute.parquet JPL 部分）"
            "keep vs collapse（仅替换含 exact-duplicate 的母体成员会话）"
        ),
        "input_untouched": True,
        "frozen_months": sorted(frozen_months),
        "proxy_main": _CURRENT_ONLY_MAIN,
        "frozen_baseline_reference": frozen_ref,
        "population": {
            "n_frozen_sessions": len(frozen_sessions),
        },
        "keep": keep_e3,
        "keep_reproduces_frozen_baseline": keep_reproduces,
    }

    if not keep_reproduces:
        result: dict[str, Any] = {
            "scope": base["scope"],
            "input_untouched": True,
            "frozen_months": base["frozen_months"],
            "proxy_main": base["proxy_main"],
            "frozen_baseline_reference": base["frozen_baseline_reference"],
            "population": {
                "n_frozen_sessions": len(frozen_sessions),
                "n_duplicate_affected_sessions": 0,
                "n_affected_sessions_found_in_frozen_population": 0,
                "n_affected_sessions_not_in_population": 0,
                "n_population_sessions_untouched": len(frozen_sessions),
            },
            "keep": keep_e3,
            "keep_reproduces_frozen_baseline": False,
            "collapse": None,
            "consistency": None,
            "flips": None,
            "gate": None,
            "acceptance": {
                "keep_reproduces_frozen_baseline": False,
                "population_identity_preserved": None,
                "nonaffected_sessions_unchanged": None,
                "keep_gate": None,
                "collapse_gate": None,
                "gate_flipped": None,
            },
            "stop": "KEEP_NOT_REPRODUCED — 完整 JPL 母体未复现冻结 E3 基线，立即 STOP 查 pipeline",
        }
        if out_json is not None:
            Path(out_json).parent.mkdir(parents=True, exist_ok=True)
            Path(out_json).write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return result

    # ---- 冻结样本 membership：受 exact-dup 影响文件 → session_id ----
    clf = pd.read_csv(classification_csv_path, dtype=str)
    reg = pd.read_csv(sample_registry_path, dtype=str)
    reg_jpl = reg[reg["site"] == "jpl"].copy()
    reg_jpl["lp"] = reg_jpl["static_file"].str.replace("\\", "/", regex=False)
    jpl_dup = clf[
        (clf["site_canonical"] == "jpl") & (clf["identical_dup_rows"].astype(int) > 0)
    ].copy()
    jpl_dup["lp"] = jpl_dup["logical_path"]
    mapped = jpl_dup.merge(
        reg_jpl[["lp", "sessionID", "sample_role", "month", "static_file", "stationID"]],
        on="lp",
        how="left",
    )
    affected_all = mapped[mapped["sessionID"].notna()]["sessionID"].tolist()
    affected_in_pop = [s for s in affected_all if s in frozen_sessions]
    affected_not_in_pop = [s for s in affected_all if s not in frozen_sessions]
    affected_sessions = set(affected_in_pop)

    # ---- Collapse 臂：局部 session 替换 ----
    rated_v_by_site = rated_voltage or {}
    rated_v_raw = rated_v_by_site.get("jpl")
    rated_v = float(rated_v_raw) if rated_v_raw is not None else 192.7
    root = Path(static_root)
    coll_rebuild: dict[str, pd.DataFrame] = {}
    rebuild_failed: list[str] = []
    for _, r in mapped[mapped["sessionID"].notna()].iterrows():
        sid = str(r["sessionID"])
        if sid not in affected_sessions:
            continue
        try:
            raw = read_static_csv(root / str(r["static_file"]))
        except (OSError, ValueError):
            rebuild_failed.append(sid)
            continue
        # collapse：逐字节相同行去重
        dup_mask = raw.duplicated(keep="first")
        raw_coll = raw[~dup_mask].copy() if dup_mask.any() else raw.copy()
        reg_row = reg_jpl[reg_jpl["sessionID"] == sid].iloc[0]
        coll_min = aggregate_session_minute(
            raw_coll,
            rated_v,
            session_id=sid,
            station_id=str(reg_row["stationID"]),
            site="jpl",
            garage=str(reg_row["garage"]),
        )
        if not coll_min.empty:
            coll_rebuild[sid] = coll_min

    # 构造 collapse 完整表：未受影响 session 逐字节保留 keep；受影响 session 替换
    keep_unaffected = keep_min[~keep_min["session_id"].isin(affected_sessions)]
    rebuilt_parts = [df for df in coll_rebuild.values() if not df.empty]
    coll_min = pd.concat([keep_unaffected, *rebuilt_parts], ignore_index=True)

    # ---- 硬一致性检查 ----
    coll_sessions = set(coll_min["session_id"].unique())
    population_identity_preserved = coll_sessions == frozen_sessions
    nonaffected_unchanged = True
    if len(keep_unaffected):
        ku = keep_unaffected.sort_values(["session_id", "timestamp_utc"]).reset_index(drop=True)
        unaffected_ids = keep_unaffected["session_id"].unique()
        cu = (
            coll_min[coll_min["session_id"].isin(unaffected_ids)]
            .sort_values(["session_id", "timestamp_utc"])
            .reset_index(drop=True)
        )
        nonaffected_unchanged = ku.equals(cu)
    no_extra_minutes = len(coll_min) == len(keep_min)
    site_garage_unchanged = set(
        zip(coll_min["site"], coll_min["garage"], strict=True)
    ) == set(zip(keep_min["site"], keep_min["garage"], strict=True))
    # 受影响 session 之外 actual_power diff = 0
    coll_check = coll_min.merge(
        keep_min[["session_id", "timestamp_utc", "actual_power_kw"]].rename(
            columns={"actual_power_kw": "keep_apk"}
        ),
        on=["session_id", "timestamp_utc"],
        how="inner",
    )
    non_target_diff = coll_check[~coll_check["session_id"].isin(affected_sessions)]
    nonaffected_apk_zero_diff = True
    if len(non_target_diff):
        na = non_target_diff["actual_power_kw"].fillna(-999.0)
        nk = non_target_diff["keep_apk"].fillna(-999.0)
        nonaffected_apk_zero_diff = bool((na == nk).all())

    consistency = {
        "population_identity_preserved": population_identity_preserved,
        "nonaffected_sessions_unchanged": nonaffected_unchanged,
        "no_extra_or_missing_minutes": no_extra_minutes,
        "site_garage_unchanged": site_garage_unchanged,
        "nonaffected_actual_power_zero_diff": nonaffected_apk_zero_diff,
        "keep_rows": int(len(keep_min)),
        "collapse_rows": int(len(coll_min)),
        "keep_sessions": int(len(frozen_sessions)),
        "collapse_sessions": int(len(coll_sessions)),
    }

    # ---- Collapse 臂：跑同一完整池管线 ----
    coll_e3 = _run_jpl_current_only_e3(coll_min, frozen_months, bootstrap_seed, n_boot)
    coll_cand = coll_e3.pop("_cand")
    coll_cyc = coll_e3.pop("_cyc")

    # ---- flips ----
    n_cand_rows = 0
    candidate_flips = 0
    if len(keep_cand) and len(coll_cand):
        key = ["site", "garage", "cycle"]
        kk = keep_cand.set_index(key)[f"candidate_{_CURRENT_ONLY_MAIN}"]
        cc = coll_cand.set_index(key)[f"candidate_{_CURRENT_ONLY_MAIN}"]
        merged = kk.rename("keep").to_frame().join(cc.rename("collapse"), how="outer")
        merged["keep"] = merged["keep"].fillna(False)
        merged["collapse"] = merged["collapse"].fillna(False)
        n_cand_rows = int(len(merged))
        candidate_flips = int((merged["keep"] != merged["collapse"]).sum())

    eligible_cycle_flips = 0
    if len(keep_cand) and len(coll_cand):
        key = ["site", "garage", "cycle"]
        keep_set = set(map(tuple, keep_cand[key].to_numpy()))
        coll_set = set(map(tuple, coll_cand[key].to_numpy()))
        eligible_cycle_flips = len(keep_set.symmetric_difference(coll_set))

    active_flips = 0
    if len(keep_cyc) and len(coll_cyc):
        key = ["site", "garage", "session_id", "cycle"]
        kk = keep_cyc.set_index(key)["active"].rename("keep")
        cc = coll_cyc.set_index(key)["active"].rename("collapse")
        merged = kk.to_frame().join(cc, how="outer")
        merged["keep"] = merged["keep"].fillna(False)
        merged["collapse"] = merged["collapse"].fillna(False)
        active_flips = int((merged["keep"] != merged["collapse"]).sum())

    flips = {
        "candidate_flips": candidate_flips,
        "n_candidate_rows": n_cand_rows,
        "eligible_cycle_flips": eligible_cycle_flips,
        "active_flips": active_flips,
    }

    # ---- gate verdict ----
    def _pass_rate(e3: dict[str, Any]) -> bool:
        lo = e3.get("a2_day_rate_ci_lower")
        return bool(lo is not None and lo >= lower_rate)

    def _pass_share(e3: dict[str, Any]) -> bool:
        sh = e3.get("daily_energy_share_median")
        return bool(sh is not None and sh >= share_min)

    pass_rate_keep = _pass_rate(keep_e3)
    pass_rate_collapse = _pass_rate(coll_e3)
    pass_share_keep = _pass_share(keep_e3)
    pass_share_collapse = _pass_share(coll_e3)
    keep_gate = pass_rate_keep and pass_share_keep
    collapse_gate = pass_rate_collapse and pass_share_collapse
    gate_flipped = (pass_rate_keep != pass_rate_collapse) or (
        pass_share_keep != pass_share_collapse
    )

    gate = {
        "rule": (
            f"日等权候选率日 cluster bootstrap 95%CI 下界 >= {lower_rate} 且 "
            f"日候选能量占比中位数 >= {share_min}（与 e0_full.yaml e3 停止线同值）"
        ),
        "pass_candidate_rate_keep": pass_rate_keep,
        "pass_candidate_rate_collapse": pass_rate_collapse,
        "pass_daily_share_keep": pass_share_keep,
        "pass_daily_share_collapse": pass_share_collapse,
        "keep_gate": keep_gate,
        "collapse_gate": collapse_gate,
        "gate_flipped": gate_flipped,
    }

    acceptance = {
        "keep_reproduces_frozen_baseline": keep_reproduces,
        "population_identity_preserved": population_identity_preserved,
        "nonaffected_sessions_unchanged": nonaffected_unchanged,
        "keep_gate": keep_gate,
        "collapse_gate": collapse_gate,
        "gate_flipped": gate_flipped,
    }

    stop_reason: str | None = None
    if not keep_reproduces:
        stop_reason = "KEEP_NOT_REPRODUCED"
    elif not population_identity_preserved:
        stop_reason = "POPULATION_IDENTITY_BROKEN"
    elif not nonaffected_unchanged:
        stop_reason = "NONAFFECTED_SESSIONS_CHANGED"
    elif not keep_gate:
        stop_reason = "KEEP_GATE_NOT_PASS"

    result = {
        "scope": base["scope"],
        "input_untouched": True,
        "frozen_months": base["frozen_months"],
        "proxy_main": base["proxy_main"],
        "frozen_baseline_reference": base["frozen_baseline_reference"],
        "population": {
            "n_frozen_sessions": len(frozen_sessions),
            "n_duplicate_affected_sessions": len(affected_all),
            "n_affected_sessions_found_in_frozen_population": len(affected_in_pop),
            "n_affected_sessions_not_in_population": len(affected_not_in_pop),
            "n_population_sessions_untouched": len(frozen_sessions) - len(affected_sessions),
        },
        "keep": keep_e3,
        "keep_reproduces_frozen_baseline": keep_reproduces,
        "collapse": coll_e3,
        "consistency": consistency,
        "flips": flips,
        "gate": gate,
        "acceptance": acceptance,
        "stop": stop_reason,
        "rebuild_failed_sessions": rebuild_failed,
    }
    if out_json is not None:
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(out_json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return result


def run_e0f01(
    cfg_path: str | Path | None = None,
    workers: int = 1,
    reuse_manifest: bool = False,
    require_clean_baseline: bool = True,
) -> dict[str, Any]:
    """E0F-01/01.1 全量执行：manifest → 质量汇总 → 连接时间审计 → 重复分类 → 影响量 → 冻结产物。

    产物：
    - data_registry/e0_full_source_manifest.parquet
    - data_registry/e0_full_quality_summary.json
    - data_registry/e0_full_connection_time_audit.parquet
    - data_registry/e0_full_dup_ts_classification.csv
    - data_registry/e0_full_dup_collapse_impact.json
    - data_registry/e0_full_dup_current_only_sensitivity.json
    - data_registry/e0_full_dup_current_only_full_pool_sensitivity.json
    - data_registry/e0_full_baseline.json
    - reports/E0_Full_input_audit.md

    reuse_manifest=True 时复用已存在的 manifest（迭代用），默认全量重扫保证确定性。
    require_clean_baseline=True：正式冻结运行时存在未提交代码则拒绝生成 baseline
    （审查结论10 P0-1：代码 commit → clean run → evidence commit）。
    """
    cfg = load_yaml(cfg_path or (Path(__file__).resolve().parents[3] / "configs" / "e0_full.yaml"))
    k1_cfg = load_yaml(Path(__file__).resolve().parents[3] / "configs" / "k1_preregister.yaml")
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
        site_mapping=cfg.get("site_mapping"),
        role_months=cfg.get("k1_role_months"),
    )
    quality["dup_ts_classification"] = dup_cls

    impact = dup_collapse_impact(
        manifest,
        static_root,
        out_json=impl_root / "data_registry" / "e0_full_dup_collapse_impact.json",
        site_mapping=cfg.get("site_mapping"),
        role_months=cfg.get("k1_role_months"),
        rated_voltage=cfg.get("power", {}).get("rated_voltage"),
    )
    quality["dup_collapse_impact"] = impact

    sens = current_only_sensitivity(
        manifest,
        static_root,
        out_json=impl_root / "data_registry" / "e0_full_dup_current_only_sensitivity.json",
        site_mapping=cfg.get("site_mapping"),
        role_months=cfg.get("k1_role_months"),
        rated_voltage=cfg.get("power", {}).get("rated_voltage"),
        p_on_kw=float(k1_cfg["primary_threshold"]["P_on_kw"]),
        e3_stop=cfg.get("k1_replication_stop_lines", {}).get("e3"),
        bootstrap_seed=int(cfg.get("seeds", {}).get("bootstrap", 42)),
        n_boot=int(cfg.get("seeds", {}).get("n_boot", 2000)),
    )
    quality["dup_current_only_sensitivity"] = sens

    # 审查结论12 P0：冻结完整 JPL current-only 母体 keep-vs-collapse 敏感性（E0F-01.3）
    full_pool_sens = current_only_full_pool_sensitivity(
        minute_table_path=impl_root / "datasets" / "lite_session_minute.parquet",
        sample_registry_path=impl_root / "data_registry" / "k1_sample_registry.csv",
        classification_csv_path=impl_root / "data_registry" / "e0_full_dup_ts_classification.csv",
        static_root=static_root,
        out_json=impl_root
        / "data_registry"
        / "e0_full_dup_current_only_full_pool_sensitivity.json",
        site_mapping=cfg.get("site_mapping"),
        role_months=cfg.get("k1_role_months"),
        rated_voltage=cfg.get("power", {}).get("rated_voltage"),
        e3_stop=cfg.get("k1_replication_stop_lines", {}).get("e3"),
        bootstrap_seed=int(cfg.get("seeds", {}).get("bootstrap", 42)),
        n_boot=int(cfg.get("seeds", {}).get("n_boot", 2000)),
    )
    quality["dup_current_only_full_pool_sensitivity"] = full_pool_sens

    quality_out = impl_root / "data_registry" / "e0_full_quality_summary.json"
    quality_out.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")

    from patent_preexperiment.e0_full.baseline import build_e0_full_baseline

    baseline_out = impl_root / "data_registry" / "e0_full_baseline.json"
    build_e0_full_baseline(
        out=baseline_out,
        manifest_hash_hex=quality["manifest_sha256"],
        config=cfg,
        require_clean=require_clean_baseline,
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
        lines += ["", "## 重复时间戳分类（对冻结 stop-line 的证据补充，审查结论10 P0-2）", ""]
        lines.append(
            f"- 含重复时间戳文件：{dup['dup_ts_files']}；"
            f"同一记录时间戳、不同观测值：{dup['same_timestamp_distinct_rows']} 行"
            f"（保留进入确定性分钟聚合，机制未被当前数据证明）；"
            f"逐字节相同行：{dup['identical_dup_rows']} 行"
            f"（含 {dup['identical_zero_idle_rows']} 行 0.0 空闲 + "
            f"{dup['identical_nonzero_rows']} 行非零，分布于 {dup['identical_dup_files']} 个文件）"
        )
        lines.append(f"- 规则：{dup['classification_rule']}")
        if dup.get("by_role"):
            lines.append("")
            lines.append(
                "| role | files | identical_dup_rows | zero_idle | nonzero | same_ts_distinct |"
            )
            lines.append("|---|---|---|---|---|---|")
            for role, v in sorted(dup["by_role"].items()):
                lines.append(
                    f"| {role} | {v['files']} | {v['identical_dup_rows']} | "
                    f"{v['identical_zero_idle_rows']} | {v['identical_nonzero_rows']} | "
                    f"{v['same_timestamp_distinct_rows']} |"
                )
    impact = quality.get("dup_collapse_impact")
    if impact:
        lines += [
            "",
            "## exact-duplicate 保留 vs 派生层 collapse 的 1-min 影响量（审查结论10 建议3）",
            "",
        ]
        lines.append(f"- 范围：{impact['scope']}；输入未修改：{impact['input_untouched']}")
        for role, v in sorted(impact["by_role"].items()):
            lines.append(
                f"- {role}：{v['files']} 文件，其中 {v['affected_files_any_field']} 个受影响；"
                f"受影响分钟数 current={v['fields']['current']['affected_minutes']} "
                f"power={v['fields']['power']['affected_minutes']} "
                f"pilot={v['fields']['pilot']['affected_minutes']} "
                f"energy={v['fields']['energy']['affected_minutes']}；"
                f"最大绝对差 current={v['fields']['current']['max_abs_diff']} "
                f"power={v['fields']['power']['max_abs_diff']}"
            )
        dp = impact.get("derived_power")
        if dp:
            lines.append("")
            lines.append(
                "派生层 actual_power_kw 影响量（审查结论11 P0：JPL current-only 经 "
                "rated 192.7×current/1000 传播）："
            )
            lines.append(f"- 规则：{dp['rule']}")
            for role, v in sorted(dp["by_role"].items()):
                lines.append(
                    f"- {role}：{v['affected_minutes']} 受影响分钟，"
                    f"max={v['max_abs_diff_kw']}kW p95={v['p95_abs_diff_kw']}kW "
                    f"mean={v['mean_abs_diff_kw']}kW，累计绝对能量差 "
                    f"{v['total_abs_energy_diff_kwh']}kWh"
                )
            o = dp["overall"]
            lines.append(
                f"- 总体：{o['affected_minutes']} 受影响分钟，max={o['max_abs_diff_kw']}kW "
                f"p95={o['p95_abs_diff_kw']}kW mean={o['mean_abs_diff_kw']}kW，"
                f"累计绝对能量差 {o['total_abs_energy_diff_kwh']}kWh"
            )
    sens = quality.get("dup_current_only_sensitivity")
    if sens:
        lines += [
            "",
            "## current-only exact-duplicate 的 E3 门敏感性（审查结论11 P0）",
            "",
        ]
        lines.append(
            f"- 范围：{sens['scope']}；P_on_kw={sens['p_on_kw']}；"
            f"冻结月份 {sens['frozen_months']}；文件 {sens['files_scanned']}"
        )
        for tag, s in (("keep", sens["low_power_state"]["keep"]),
                       ("collapse", sens["low_power_state"]["collapse"])):
            if s:
                lines.append(f"- low_power_state {tag}：{s['ratio']:.4f}（{s['n_minutes']} 分钟）")
        for tag, e in (("keep", sens["e3_a2"]["keep"]), ("collapse", sens["e3_a2"]["collapse"])):
            if e:
                lines.append(
                    f"- A2 {tag}：cycle_rate={e['cycle_weighted_rate']:.5f} "
                    f"day_rate={e['day_rate']} ci95={e['day_rate_ci95']} "
                    f"n_days={e['n_days']}；日能量占比中位数={e['daily_energy_share_median']}"
                )
        flips = sens["flips"]
        lines.append(
            f"- 翻转：候选窗口 {flips['candidate_flips']}/{flips['n_candidate_rows']}，"
            f"活跃周期 {flips['active_flips']}"
        )
        g = sens["gate"]
        lines.append(
            f"- 门：rate keep={g['pass_candidate_rate_keep']} / "
            f"collapse={g['pass_candidate_rate_collapse']}；"
            f"share keep={g['pass_daily_share_keep']} / "
            f"collapse={g['pass_daily_share_collapse']}；门翻转：{g['gate_flipped']}"
        )
    fps = quality.get("dup_current_only_full_pool_sensitivity")
    if fps:
        lines += [
            "",
            "## 完整 JPL current-only 母体 keep-vs-collapse 敏感性（审查结论12 P0，E0F-01.3）",
            "",
        ]
        lines.append(f"- 范围：{fps['scope']}；输入未修改：{fps['input_untouched']}")
        lines.append(
            f"- 冻结基线参考：n_cycles={fps['frozen_baseline_reference']['n_cycles']}，"
            f"A2={fps['frozen_baseline_reference']['a2_cycle_weighted_rate']:.6f}，"
            f"日率={fps['frozen_baseline_reference']['a2_day_rate']:.6f}，"
            f"CI={fps['frozen_baseline_reference']['a2_day_rate_ci95']}，"
            f"能量占比={fps['frozen_baseline_reference']['daily_energy_share_median']}，"
            f"gate={fps['frozen_baseline_reference']['gate']}"
        )
        pop = fps["population"]
        lines.append(
            f"- 母体 membership：frozen_sessions={pop['n_frozen_sessions']}，"
            f"affected={pop['n_duplicate_affected_sessions']}，"
            f"affected_in_pop={pop['n_affected_sessions_found_in_frozen_population']}，"
            f"affected_not_in_pop={pop['n_affected_sessions_not_in_population']}，"
            f"untouched={pop['n_population_sessions_untouched']}"
        )
        ke = fps.get("keep")
        if ke:
            lines.append(
                f"- Keep：n_cycles={ke['n_cycles']} A2={ke['a2_cycle_weighted_rate']:.6f} "
                f"日率={ke['a2_day_rate']} CI={ke['a2_day_rate_ci95']} "
                f"能量占比中位={ke['daily_energy_share_median']}"
            )
        lines.append(f"- Keep 复现冻结基线：{fps['keep_reproduces_frozen_baseline']}")
        ce = fps.get("collapse")
        if ce:
            lines.append(
                f"- Collapse：n_cycles={ce['n_cycles']} A2={ce['a2_cycle_weighted_rate']:.6f} "
                f"日率={ce['a2_day_rate']} CI={ce['a2_day_rate_ci95']} "
                f"能量占比中位={ce['daily_energy_share_median']}"
            )
        cons = fps.get("consistency")
        if cons:
            lines.append(
                f"- 一致性：population_identity={cons['population_identity_preserved']}，"
                f"nonaffected_unchanged={cons['nonaffected_sessions_unchanged']}，"
                f"no_extra_minutes={cons['no_extra_or_missing_minutes']}，"
                f"site_garage={cons['site_garage_unchanged']}，"
                f"nonaffected_apk_zero_diff={cons['nonaffected_actual_power_zero_diff']}"
            )
        fl = fps.get("flips")
        if fl:
            lines.append(
                f"- 翻转：候选 {fl['candidate_flips']}/{fl['n_candidate_rows']}，"
                f"eligible_cycle={fl['eligible_cycle_flips']}，活跃 {fl['active_flips']}"
            )
        g = fps.get("gate")
        if g:
            lines.append(
                f"- 门：keep_gate={g['keep_gate']} collapse_gate={g['collapse_gate']} "
                f"gate_flipped={g['gate_flipped']}"
            )
        lines.append(f"- 验收：{fps['acceptance']}")
        if fps.get("stop"):
            lines.append(f"- STOP 原因：{fps['stop']}")
    sm = quality.get("site_mapping_audit")
    if sm:
        lines += ["", "## 站点 raw→canonical 映射（审查结论10 P1，E0F-02 前冻结）", ""]
        lines.append(
            f"- raw_sites：{sm['raw_sites']}；canonical_sites：{sm['canonical_sites']}；"
            f"未映射：{sm['unmapped_raw']}；mapping_ok：{sm['mapping_ok']}"
        )
    lines += ["", "## 停止线判定", ""]
    for name, check in quality["stop_lines"]["checks"].items():
        lines.append(f"- {name}：{'PASS' if check['ok'] else 'FAIL'}（{check}）")
    lines.append("")
    lines.append(f"## 总体：{'PASS' if quality['stop_lines']['passed'] else 'STOP'}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
