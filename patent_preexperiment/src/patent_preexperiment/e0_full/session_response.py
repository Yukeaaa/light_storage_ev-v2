"""E0F-03 会话分钟响应表 session_response_1min 构建（V2.1 §10.1/§10.2；issue #14；审查结论17）。

职责边界：
- 只把原始响应转成可追溯的 canonical 分钟观测：这一分钟是谁/在哪/属于哪个
  split-role-layer-mode/实际响应多少/power 来源/能量来源/质量标记/重复如何进入聚合。
- 不定义"可执行能力"、不生成"吸收余量"、不做任何 D1-R 模型判断（那是 E1/E2 的事）。
- 85,877 session universe 原样继承；session_id/split/role/sample_layer/field_mode
  只从 E0F-02 registry join，禁止重新推导。

口径（issue #14 验收；审查结论17 授权）：
1. 派生层 exact-duplicate collapse（逐字节相同原始行保留首次出现）并逐分钟登记
   raw_duplicate_count；同一时间戳不同观测保留进入确定性分钟聚合。
2. actual_power_kw 严格用冻结优先级 measured→computed→estimated（rated 按 canonical
   site：jpl=192.7/caltech=240/office001=240，见 configs/e0_full.yaml power.rated_voltage）。
3. [session_id, timestamp_utc(1min)] 唯一；非法重复 hard STOP。
4. 只做数据工程检查：即使构建了 test 分区，也不查看 test 上的 K1/D1-R outcome 指标
   （configs/e0_full.yaml session_response.test_policy）。
5. 空会话（无任何分钟）与读取/解析失败一律 hard STOP（stop_lines：大规模文件读取失败）。
6. disconnect_time / done_charging_time / kwh_delivered 只作离线标签与能量审计基准，
   禁止进入在线特征（configs/e0_full.yaml session_response.offline_labels）。

 输出：datasets/session_response_1min/site=<site>/year=YYYY/month=MM/data.parquet
 按 (site, year, month) 分区；分区注册表 e0_full_session_response_partitions.json 登记
 每分区行数/会话数/sha256。

 全局唯一证明（E0F-03.2，审查结论19）：三腿合成，无 28.3M 全局 key 集合：
 - 每行治理列（site/split/role/sample_layer/field_mode/match_status/external/stress）
   必须等于 E0F-02 registry 中该 session_id 的值（继承来源冻结，禁止重推导）→
   session_id 唯一决定 canonical site；
 - 每行 timestamp_utc 的 year/month 必须等于所在分区路径 → timestamp 唯一决定
   year/month 分区；
 - 每个 site/year/month 分区内 [session_id, timestamp_utc] 唯一。
 三条合取 ⇒ 一个 [session_id, timestamp_utc] 只能落进唯一一个 site/year/month 分区，
 从而全局唯一。孤儿会话（在 parquet 但不在 registry）由 covered 集合校验按 extra 报。
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.io.paths import acn_project_dir, static_root_dir
from patent_preexperiment.io.static import read_static_text
from patent_preexperiment.response.session import derive_power

_OUTPUT_COLUMNS = [
    "session_id", "station_id", "site", "garage", "cluster", "split", "role",
    "sample_layer", "field_mode", "match_status", "external", "stress",
    "connection_time", "disconnect_time", "done_charging_time", "kwh_delivered",
    "timestamp_utc", "timestamp_local", "timezone_valid",
    "connected_elapsed_min",
    "current_a", "voltage_v", "power_kw", "actual_power_kw", "power_source",
    "pilot_a", "pilot_power_kw", "pilot_available",
    "state_raw", "state_norm", "state_available",
    "energy_cum_kwh", "energy_source",
    "sample_count", "raw_duplicate_count",
    "gap_flag", "gap_before_min", "severe_gap_before",
    "source_file",
]

_DATETIME_COLS = {"connection_time", "disconnect_time", "done_charging_time", "timestamp_utc"}

# E0F-02 治理列（冻结继承来源，禁止重推导；finalize 逐行对齐校验，审查结论19）。
_GOVERNANCE_COLUMNS = (
    "site", "split", "role", "sample_layer", "field_mode", "match_status", "external", "stress"
)

_BOOL_COLS = {
    "external", "stress", "timezone_valid", "pilot_available", "state_available",
    "gap_flag", "severe_gap_before",
}
_INT_COLS = {"sample_count", "raw_duplicate_count"}
_FLOAT_COLS = {
    "connected_elapsed_min", "current_a", "voltage_v", "power_kw", "actual_power_kw",
    "pilot_a", "pilot_power_kw", "energy_cum_kwh", "kwh_delivered", "gap_before_min",
}

_RAW_COL_NAMES = {
    "current_a": "Charging Current (A)",
    "pilot_a": "Actual Pilot (A)",
    "voltage_v": "Voltage (V)",
    "state": "Charging State",
    "energy_kwh": "Energy Delivered (kWh)",
    "power_kw": "Power (kW)",
}

_STATE_NORM = {
    "CHARGING": "charging",
    "CONNECTED": "connected",
    "IDLE": "idle",
    "FINISHING": "finishing",
}

_MINUTE_KEY = "%Y-%m-%dT%H:%M:%SZ"


def _to_ts(value: Any) -> pd.Timestamp | None:
    """解析为 UTC Timestamp；缺失/非法返回 None。"""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value if value.tzinfo is not None else value.tz_localize("UTC")
    if isinstance(value, float) and np.isnan(value):
        return None
    s = str(value)
    if not s or s in {"nan", "NaT", "None"}:
        return None
    try:
        ts = pd.Timestamp(s)
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _mode(series: pd.Series) -> str:
    vals = series.dropna()
    if vals.empty:
        return ""
    return str(vals.mode().iloc[0])


def parse_session_lines(lines: list[str]) -> pd.DataFrame:
    """把静态 csv 文本行解析为规范化 df（缺列补齐、非法时间戳行跳过、非法数值置 NaN）。

    与 io/static.parse_static_bytes 的列口径一致：timestamp/current_a/pilot_a/voltage_v/
    state/energy_kwh/power_kw。state 保留原文串；时间为 naive-UTC 归一后本地化为 UTC。
    """
    if not lines:
        return pd.DataFrame()
    header = lines[0].lstrip("\ufeff")
    cols = header.split(",")
    idx: dict[str, int] = {}
    for i, c in enumerate(cols):
        idx[c.strip()] = i
    recs: list[dict[str, Any]] = []
    for ln in lines[1:]:
        if not ln.strip():
            continue
        parts = ln.split(",")
        if len(parts) < len(cols):
            continue
        try:
            ts = datetime.fromisoformat(parts[0].strip())
        except ValueError:
            continue
        if ts.tzinfo is not None:
            ts = ts.astimezone(UTC).replace(tzinfo=None)
        rec: dict[str, Any] = {"timestamp": ts}
        for canon, raw_name in _RAW_COL_NAMES.items():
            col_i = idx.get(raw_name)
            if col_i is None or col_i >= len(parts):
                continue
            raw_val = parts[col_i].strip()
            if not raw_val:
                continue
            if canon == "state":
                rec["state"] = raw_val
            else:
                try:
                    rec[canon] = float(raw_val)
                except ValueError:
                    pass
        recs.append(rec)
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs)
    for col in ("current_a", "pilot_a", "voltage_v", "energy_kwh", "power_kw"):
        if col not in df.columns:
            df[col] = np.nan
    if "state" not in df.columns:
        df["state"] = pd.NA
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df[["timestamp", "current_a", "pilot_a", "voltage_v", "state", "energy_kwh", "power_kw"]]


def exact_dup_extras(raw_lines: list[str]) -> dict[str, int]:
    """逐字节相同原始行的额外份数，按分钟累计（保留首次出现）。

    返回 {分钟键: 被 collapse 掉的额外行数}；分钟键格式 "%Y-%m-%dT%H:%M:%SZ"。
    """
    ts_list = [ln.split(",", 1)[0] for ln in raw_lines]
    if len(ts_list) == len(set(ts_list)):
        return {}
    per_ts: dict[str, dict[str, int]] = {}
    for ln in raw_lines:
        ts = ln.split(",", 1)[0]
        per_ts.setdefault(ts, {})
        per_ts[ts][ln] = per_ts[ts].get(ln, 0) + 1
    extras: dict[str, int] = {}
    for ts, counts in per_ts.items():
        extra = sum(c - 1 for c in counts.values())
        if not extra:
            continue
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        key = dt.replace(second=0, microsecond=0).strftime(_MINUTE_KEY)
        extras[key] = extras.get(key, 0) + extra
    return extras


def aggregate_session_minutes(
    rows: pd.DataFrame,
    meta: dict[str, Any],
    n_extra: dict[str, int],
) -> pd.DataFrame:
    """post-collapse 秒级观测 → 会话 1 分钟表（含质量/缺口/能量/注册列）。"""
    df = derive_power(rows, rated_v=float(meta["rated_v"]))
    df["_min"] = df["timestamp"].dt.floor("min")

    g = df.groupby("_min", sort=True)
    out = g.agg(
        current_a=("current_a", "mean"),
        voltage_v=("voltage_v", "mean"),
        power_kw=("power_kw", "mean"),
        actual_power_kw=("actual_power_kw", "mean"),
        power_source=("power_source", _mode),
        pilot_a=("pilot_a", "mean"),
        state_raw=("state", _mode),
        energy_kwh=("energy_kwh", "last"),
        sample_count=("current_a", "size"),
    ).reset_index()
    out["raw_duplicate_count"] = (
        out["_min"].dt.strftime(_MINUTE_KEY).map(n_extra).fillna(0).astype("int64")
    )

    ts = out["_min"].rename("timestamp_utc")
    out["timestamp_utc"] = ts
    out["timestamp_local"] = ts.dt.tz_convert(meta["tz_local"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["timezone_valid"] = True
    ct = meta["connection_time"]
    if ct is None:
        out["connected_elapsed_min"] = pd.Series(np.nan, index=out.index)
    else:
        out["connected_elapsed_min"] = (
            (ts - pd.Timestamp(ct)).dt.total_seconds() / 60.0
        )
    out["pilot_power_kw"] = out["pilot_a"] * float(meta["rated_v"]) / 1000.0
    out["pilot_available"] = out["pilot_a"].notna()
    out["state_available"] = out["state_raw"].ne("")
    out["state_norm"] = out["state_raw"].map(_STATE_NORM)
    out["state_norm"] = out["state_norm"].fillna(out["state_raw"])
    out.loc[out["state_raw"].eq(""), "state_norm"] = ""
    out["energy_cum_kwh"] = out["energy_kwh"].ffill()
    out["gap_flag"] = out["sample_count"] < int(meta["minute_sample_threshold"])
    prev = ts.shift(1)
    out["gap_before_min"] = (ts.sub(prev).dt.total_seconds() / 60.0).to_numpy()
    out["severe_gap_before"] = out["gap_before_min"].ge(float(meta["severe_gap_min"])).fillna(False)

    const_cols: dict[str, Any] = {
        "session_id": str(meta["session_id"]),
        "station_id": str(meta["station_id"]),
        "site": str(meta["site"]),
        "garage": str(meta["garage"]),
        "cluster": str(meta["garage"]),
        "split": str(meta["split"]),
        "role": str(meta["role"]),
        "sample_layer": str(meta["sample_layer"]),
        "field_mode": str(meta["field_mode"]),
        "match_status": str(meta["match_status"]),
        "external": bool(meta["external"]),
        "stress": bool(meta["stress"]),
        "connection_time": pd.Timestamp(ct),
        "disconnect_time": _to_ts(meta["disconnect_time"]),
        "done_charging_time": _to_ts(meta["done_charging_time"]),
        "kwh_delivered": _to_float(meta["kwh_delivered"]),
        "energy_source": str(meta["energy_source"]),
        "source_file": str(meta["source_file"]),
    }
    for k, v in const_cols.items():
        out[k] = v
    out = _cast_dtypes(out)
    return out.sort_values("timestamp_utc").reset_index(drop=True)[_OUTPUT_COLUMNS]


def _cast_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    for c in _DATETIME_COLS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], utc=True)
    for c in _BOOL_COLS:
        if c in df.columns:
            df[c] = df[c].astype(bool)
    for c in _INT_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("int64")
    for c in _FLOAT_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def session_energy_audit(
    out: pd.DataFrame, meta: dict[str, Any]
) -> dict[str, Any]:
    """会话级能量审计行（能量一致性校验基准，只作审计不作特征）。

    能量跨度基于 canonical 分钟表的 energy_cum_kwh（原始累计计量逐分钟前向保持，
    会话内单调非降）。会话末尾常出现 UNPLUGGED 复位行（仪表 re-arm 到 0.0），
    属已知伪影。energy_first 取分钟表首条非空累计读数、energy_last 取分钟表峰值
    （累计计量单调非降，峰值即最终有效读数，复位到 0.0 不会成为峰值），
    不使用分钟末值，避免复位行污染能量跨度。
    口径与 build/finalize 两条路径完全一致（只依赖 canonical 分钟表列）。
    """
    e = out["energy_cum_kwh"].dropna()
    return {
        "session_id": str(meta["session_id"]),
        "site": str(meta["site"]),
        "match_status": str(meta["match_status"]),
        "has_energy": str(meta["energy_source"]) == "raw",
        "n_minutes": int(len(out)),
        "integral_kwh": float(out["actual_power_kw"].sum() / 60.0),
        "energy_first": float(e.iloc[0]) if not e.empty else None,
        "energy_last": float(e.max()) if not e.empty else None,
        "ref_api_kwh": _to_float(meta["kwh_delivered"]),
    }


def _error_frame(session_id: str, error: str) -> pd.DataFrame:
    return pd.DataFrame({"session_id": [session_id], "parse_error": [error]})


def _frame_ok(frame: pd.DataFrame) -> bool:
    return not frame.empty and "parse_error" not in frame.columns


def _session_worker(args: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any] | None]:
    """单个会话：读文件 → exact-dup collapse → 解析 → 分钟聚合 + 能量审计。

    args 为 build_session_response 预组装的 meta（含 static_root/source_file）。
    """
    root = Path(args["static_root"])
    rel = str(args["source_file"])
    try:
        text = read_static_text(root / rel)
    except Exception as exc:  # noqa: BLE001
        return _error_frame(args["session_id"], f"read:{exc!r}"), None
    lines = text.splitlines()
    if not lines:
        return _error_frame(args["session_id"], "empty_file"), None
    raw_lines = [ln for ln in lines[1:] if ln.strip()]
    collapsed = list(dict.fromkeys(raw_lines))
    n_extra = exact_dup_extras(raw_lines)
    rows = parse_session_lines([lines[0], *collapsed])
    if rows.empty:
        return _error_frame(args["session_id"], "no_parseable_rows"), None
    out = aggregate_session_minutes(rows, args, n_extra)
    return out, session_energy_audit(out, args)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_meta(
    registry: pd.DataFrame,
    manifest: pd.DataFrame,
    api_meta: pd.DataFrame,
    cfg: dict[str, Any],
    static_root: str | Path,
) -> list[dict[str, Any]]:
    """逐会话预组装 worker 入参（注册列一律来自 registry，禁止重推导）。"""
    rated_v = {k: float(v) for k, v in cfg["power"]["rated_voltage"].items()}
    minute_thr = int(cfg["session_response"]["minute_sample_threshold"])
    severe_gap = float(cfg["session_response"]["severe_gap_min"])
    tz_local = str(cfg["session_response"]["timezone_local"])

    mf = manifest.set_index("logical_path")
    missing_manifest: list[str] = []
    api_lookup: dict[str, tuple[Any, Any]] = {}
    if "sessionID" in api_meta.columns and "doneChargingTime" in api_meta.columns:
        for _, r in api_meta[["sessionID", "doneChargingTime", "kWhDelivered"]].iterrows():
            sid = str(r["sessionID"])
            api_lookup[sid] = (r["doneChargingTime"], r["kWhDelivered"])
    else:
        api_lookup = {}

    metas: list[dict[str, Any]] = []
    for _, r in registry.iterrows():
        sid = str(r["session_id"])
        sf = str(r["source_file"])
        m = mf.loc[sf] if sf in mf.index else None
        if m is None:
            missing_manifest.append(sf)
            continue
        site = str(r["site"])
        done, kwh = (None, None)
        if str(r["match_status"]) == "matched":
            done, kwh = api_lookup.get(sid, (None, None))
        ct = r["connection_time"]
        meta: dict[str, Any] = {
            "session_id": sid,
            "station_id": str(r["station"]),
            "site": site,
            "garage": str(r["garage"]),
            "split": str(r["split"]),
            "role": str(r["role"]),
            "sample_layer": str(r["sample_layer"]),
            "field_mode": str(r["field_mode"]),
            "match_status": str(r["match_status"]),
            "external": bool(r["external"]),
            "stress": bool(r["stress"]),
            "connection_time": None if pd.isna(ct) else pd.Timestamp(ct),
            "disconnect_time": r["disconnect_time"] if pd.notna(r["disconnect_time"]) else None,
            "done_charging_time": done,
            "kwh_delivered": kwh,
            "energy_source": "raw" if bool(m["has_energy"]) else "none",
            "source_file": sf,
            "static_root": str(static_root),
            "rated_v": rated_v.get(site, 240.0),
            "minute_sample_threshold": minute_thr,
            "severe_gap_min": severe_gap,
            "tz_local": tz_local,
        }
        metas.append(meta)
    if missing_manifest:
        raise ValueError(
            "E0F-03 停止：registry 会话不在 manifest 中，无法确定能量列来源；"
            f"共 {len(missing_manifest)} 个，首个：{missing_manifest[0]}"
        )
    return metas


def _energy_consistency_summary(
    audits: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """能量一致性：分钟积分 vs canonical 分钟表能量跨度（has_energy 会话）与
    API kWhDelivered（matched）。

    能量为累计计量；会话末尾 UNPLUGGED 复位行（仪表 re-arm 到 0.0）为已知伪影，
    能量跨度按 峰值(energy_cum_kwh) - 首条非空分钟读数(energy_cum_kwh) 计算。
    caltech/office001 原始中位 |dev| >= tolerance_median_dev 触发硬 STOP（等值即 STOP，
    round 只用于显示）；jpl 聚合可用，会话级离群另报不做 STOP。
    """
    if not audits:
        return {"by_site": {}, "api_kwh": {}}
    df = pd.DataFrame(audits)
    tolerance = float(cfg["session_response"]["energy_consistency"]["tolerance_median_dev"])

    by_site: dict[str, Any] = {}
    raw_median: dict[str, float] = {}
    for site in ("caltech", "jpl", "office001"):
        g = df[(df["site"] == site) & df["has_energy"]].copy()
        if g.empty:
            continue
        g["energy_span"] = g["energy_last"] - g["energy_first"]
        g["dev_energy"] = (
            (g["integral_kwh"] - g["energy_span"]) / g["energy_span"].replace(0, np.nan)
        )
        ok = g["dev_energy"].notna()
        abs_dev = g.loc[ok, "dev_energy"].abs()
        med = float(abs_dev.median()) if ok.any() else None
        raw_median[site] = med if med is not None else float("nan")
        by_site[site] = {
            "sessions": int(len(g)),
            "median_abs_dev": round(med, 6) if med is not None else None,
            "p95_abs_dev": round(float(abs_dev.quantile(0.95)), 6) if ok.any() else None,
            "n_outliers_gt_20pct": int((g.loc[ok, "dev_energy"].abs() > 0.20).sum()),
        }

    api_kwh: dict[str, Any] = {}
    m = df[df["ref_api_kwh"].notna() & (df["ref_api_kwh"] > 0.05) & df["has_energy"]].copy()
    if not m.empty:
        m["dev_api"] = (m["integral_kwh"] - m["ref_api_kwh"]) / m["ref_api_kwh"]
        for site in ("caltech", "jpl", "office001"):
            g = m[m["site"] == site]
            if g.empty:
                continue
            api_kwh[site] = {
                "sessions": int(len(g)),
                "median_abs_dev": round(float(g["dev_api"].abs().median()), 6),
                "p95_abs_dev": round(float(g["dev_api"].abs().quantile(0.95)), 6),
            }

    # 门线用原始中位（>= 冻结 tolerance 即 STOP，等值也 STOP）；round 只用于报告显示。
    stop_hits = [
        f"{site} 中位 |dev|={raw_median[site]} >= {tolerance}（冻结 tolerance_median_dev）"
        for site in ("caltech", "office001")
        if not np.isnan(raw_median.get(site, float("nan")))
        and raw_median[site] >= tolerance
    ]
    if stop_hits:
        raise RuntimeError("E0F-03 能量一致性 STOP：" + "；".join(stop_hits))
    return {"by_site": by_site, "api_kwh": api_kwh}


def _assert_partition_path_consistent(
    df: pd.DataFrame, site: str, year: int, month: int, label: str
) -> None:
    """分区路径 ↔ 行内容一致性：site 与 timestamp_utc 的 year/month 必须等于所在分区路径。

    结合"分区内 [session_id, timestamp_utc] 唯一"，可廉价机器证明全局唯一：
    若每行 timestamp 的 year/month 与其所在 year/month 分区路径一致，则同一 key
    不可能同时出现在两个不同月份分区（timestamp 决定唯一分区），无需维护 28M key 的全局集合。
    finalize 是从已有文件读取，必须防 stale/wrong 分区文件。
    """
    if df["site"].astype(str).ne(site).any():
        raise RuntimeError(
            f"E0F-03 {label} 停止（分区路径不一致）：路径 site={site} 内存在 site 与路径不符的行"
        )
    ts = df["timestamp_utc"]
    if ts.dt.year.ne(year).any() or ts.dt.month.ne(month).any():
        raise RuntimeError(
            f"E0F-03 {label} 停止（分区路径不一致）：路径 {site}/{year}-{month:02d} "
            "内存在 timestamp_utc 的 year/month 与路径不符的行"
        )


def _gov_cmp(value: Any) -> str:
    """治理列比较用 canonical 字符串：bool → true/false，NaN/None → 空串。"""
    if isinstance(value, (bool, np.bool_)):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    if value is pd.NA or value is pd.NaT:
        return ""
    return str(value).strip()


def _session_governance_index(registry: pd.DataFrame) -> pd.DataFrame:
    """E0F-02 治理列逐会话索引（session_id → site/split/role/sample_layer/field_mode/
    match_status/external/stress）。字段继承来源冻结，禁止重推导（审查结论19）。
    registry session_id 必须唯一，否则索引对齐无意义。
    """
    dup = registry["session_id"][registry["session_id"].duplicated()]
    if not dup.empty:
        raise RuntimeError(
            "E0F-03.2 停止：E0F-02 registry session_id 必须唯一，"
            f"发现 {len(dup)} 个重复，首例：{dup.iloc[0]}"
        )
    missing = [c for c in _GOVERNANCE_COLUMNS if c not in registry.columns]
    if missing:
        raise RuntimeError(
            f"E0F-03.2 停止：E0F-02 registry 缺少治理列 {sorted(missing)}"
        )
    return registry.set_index("session_id")[list(_GOVERNANCE_COLUMNS)]


def _assert_session_governance(
    df: pd.DataFrame,
    gov: pd.DataFrame,
    path: str | Path,
    label: str,
) -> None:
    """每行治理列必须等于 E0F-02 registry 中该 session_id 的值（禁止重推导）。

    这是 E0F-03.2 的最后一腿：分区路径一致性只保证"行 site == 路径 site"，
    若 stale 行被改写成错误路径的 site，路径一致性会成立但 session 的 canonical
    site（registry）已被违背——因此必须再校验行内治理列 == registry 会话级值。
    孤儿会话（在 parquet 但不在 registry）跳过，由 covered 集合校验按 extra 报，
    避免两种错误口径重复。
    """
    sids = df["session_id"].astype(str)
    known = sids.isin(gov.index)
    if not known.all():
        df = df[known.to_numpy()]
        if df.empty:
            return
        sids = df["session_id"].astype(str)
    mism: list[str] = []
    for col in gov.columns:
        expected = sids.map(gov[col]).map(_gov_cmp)
        actual = df[col].map(_gov_cmp)
        bad = actual.ne(expected)
        if bad.any():
            for sid in df.loc[bad.to_numpy(), "session_id"].drop_duplicates().astype(str):
                exp_v = _gov_cmp(gov.at[sid, col])
                act_v = df.loc[df["session_id"].astype(str).eq(sid), col].iloc[0]
                mism.append(f"{sid}.{col}: registry={exp_v} 行内={_gov_cmp(act_v)}")
    if mism:
        shown = mism[:8]
        suffix = f"；…共 {len(mism)} 处" if len(mism) > 8 else ""
        raise RuntimeError(
            f"E0F-03.2 {label} 停止（治理列与 E0F-02 registry 不一致）：{path}；"
            + "；".join(shown)
            + suffix
        )


def _partition_stats(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": int(len(df)),
        "sessions": int(df["session_id"].nunique()),
        "gap_minutes": int(df["gap_flag"].sum()),
        "severe_gap_before_minutes": int(df["severe_gap_before"].sum()),
        "power_source": {k: int(v) for k, v in df["power_source"].value_counts().to_dict().items()},
    }


def build_session_response(
    registry: pd.DataFrame,
    manifest: pd.DataFrame,
    api_meta: pd.DataFrame,
    cfg: dict[str, Any],
    static_root: str | Path,
    out_dir: str | Path,
    partition_registry_out: str | Path,
    max_workers: int | None = None,
    batch_size: int = 2048,
) -> dict[str, Any]:
    """E0F-03 引擎：meta 组装 → 并行会话分钟构建 → 分区写出 → 校验 → 能量审计。

    registry：E0F-02 split registry（85,877 会话）；manifest：E0F-01 source manifest；
    api_meta：api_metadata_index.csv（matched 的 doneChargingTime/kWhDelivered）。
    """
    metas = _build_meta(registry, manifest, api_meta, cfg, static_root)
    gov = _session_governance_index(registry)
    out_dir = Path(out_dir)
    tmp_dir = out_dir / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    pending: dict[tuple[str, int, int], list[pd.DataFrame]] = {}
    part_files: dict[tuple[str, int, int], list[Path]] = {}
    audits: list[dict[str, Any]] = []
    fails: list[tuple[str, str]] = []
    covered: set[str] = set()
    buffer_rows = 0
    flush_rows = int(cfg.get("session_response", {}).get("buffer_flush_rows", 300_000))

    def _route(key: tuple[str, int, int], frame: pd.DataFrame) -> None:
        nonlocal buffer_rows
        pending.setdefault(key, []).append(frame)
        buffer_rows += len(frame)
        if buffer_rows >= flush_rows:
            for k in list(pending):
                if sum(len(f) for f in pending[k]) >= flush_rows:
                    _flush_part(k, pending, part_files, tmp_dir)
                    buffer_rows = 0

    workers = max_workers or 8
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for start in range(0, len(metas), batch_size):
            chunk = metas[start : start + batch_size]
            fut_map = {ex.submit(_session_worker, meta): meta["session_id"] for meta in chunk}
            for fut in as_completed(fut_map):
                sid = fut_map[fut]
                frame, audit = fut.result()
                if not _frame_ok(frame):
                    fails.append((sid, frame["parse_error"].iloc[0]))
                    continue
                covered.add(sid)
                audits.append(audit or {})
                s_arr = frame["site"].to_numpy()
                y_arr = frame["timestamp_utc"].dt.year.to_numpy()
                m_arr = frame["timestamp_utc"].dt.month.to_numpy()
                u_keys = sorted(
                    {
                        (str(s), int(yy), int(mm))
                        for s, yy, mm in zip(s_arr, y_arr, m_arr, strict=True)
                    }
                )
                for s, yy, mm in u_keys:
                    mask = (s_arr == s) & (y_arr == yy) & (m_arr == mm)
                    _route((s, yy, mm), frame.loc[mask])

    for key in list(pending):
        _flush_part(key, pending, part_files, tmp_dir)

    if fails:
        raise RuntimeError(
            "E0F-03 停止（读取/解析失败，stop_lines）："
            f"{len(fails)} 个会话失败，首个：{fails[0]}"
        )

    partitions: list[dict[str, Any]] = []
    merged_stats: dict[str, Any] = {}
    for key in sorted(part_files):
        parts = part_files[key]
        frames = [pd.read_parquet(p) for p in parts]
        df = pd.concat(frames, ignore_index=True)
        df = df.sort_values(
            ["session_id", "timestamp_utc"], kind="mergesort"
        ).reset_index(drop=True)
        _assert_partition_path_consistent(df, *key, "build")
        _assert_session_governance(
            df,
            gov,
            f"site={key[0]}/year={key[1]}/month={key[2]:02d}",
            "build",
        )
        if df.duplicated(subset=["session_id", "timestamp_utc"]).any():
            raise RuntimeError(
                "E0F-03 停止（主键非法重复）：partition "
                f"{key} 内 [session_id, timestamp_utc] 不唯一"
            )
        site, year, month = key
        d = out_dir / f"site={site}" / f"year={year}" / f"month={month:02d}"
        d.mkdir(parents=True, exist_ok=True)
        final = d / "data.parquet"
        df.to_parquet(final, index=False)
        for p in parts:
            p.unlink(missing_ok=True)
        partitions.append(
            {
                "site": site,
                "year": int(year),
                "month": int(month),
                "rows": int(len(df)),
                "sessions": int(df["session_id"].nunique()),
                "sha256": _sha256_file(final),
            }
        )
        stats = _partition_stats(df)
        _merge_stats(merged_stats, stats)
        del frames, df

    summary = _build_final_registry(
        partitions=partitions,
        merged_stats=merged_stats,
        covered=covered,
        audits=audits,
        cfg=cfg,
        expected=set(registry["session_id"].astype(str)),
        partition_registry_out=partition_registry_out,
        n_failed=len(fails),
    )
    # 清理临时目录
    if tmp_dir.exists():
        for leftover in tmp_dir.iterdir():
            leftover.unlink(missing_ok=True)
        tmp_dir.rmdir()
    return summary


def _merge_stats(merged: dict[str, Any], stats: dict[str, Any]) -> None:
    """分区统计合并（power_source 按键累加，其余直接求和）。build 与 finalize 共用。"""
    for k, v in stats.items():
        if k == "power_source":
            for pk, pv in v.items():
                merged.setdefault("power_source", {})
                merged["power_source"][pk] = merged["power_source"].get(pk, 0) + pv
        else:
            merged[k] = merged.get(k, 0) + v


def _build_final_registry(
    partitions: list[dict[str, Any]],
    merged_stats: dict[str, Any],
    covered: set[str],
    audits: list[dict[str, Any]],
    cfg: dict[str, Any],
    expected: set[str],
    partition_registry_out: str | Path,
    n_failed: int,
) -> dict[str, Any]:
    """覆盖校验 → 能量审计 → 分区注册表写出 → summary。build 与 finalize 共用。

    覆盖校验按去重会话**集合**相等（covered == registry 集合），不只比较数量：
    同数量的错误集合（stale partition / orphan session）必须机器可证失败。禁止用
    分区会话数求和——跨 year/month 边界的会话会在多个分区被计数，求和会虚高。
    失败时报告 missing / extra 的计数与首个示例。
    """
    if covered != expected:
        missing = sorted(expected - covered)
        extra = sorted(covered - expected)
        raise RuntimeError(
            "E0F-03 停止（覆盖不完整）：covered 会话集合 != registry 会话集合；"
            f"missing {len(missing)} 个（首个 {missing[0] if missing else None}），"
            f"extra {len(extra)} 个（首个 {extra[0] if extra else None}）"
        )

    energy = _energy_consistency_summary(audits, cfg)

    part_registry = {
        "schema": "e0_full_session_response_1min.schema.json",
        "partition_cols": ["site", "year", "month"],
        "n_partitions": len(partitions),
        "n_sessions": len(expected),
        "n_rows": sum(p["rows"] for p in partitions),
        "uniqueness_check": "per-partition [session_id, timestamp_utc] unique + partition "
        "path ↔ row site/year/month 一致性 + 行治理列 == E0F-02 registry 会话级值"
        "（三腿合成全局唯一）",
        "partitions": sorted(partitions, key=lambda p: (p["site"], p["year"], p["month"])),
    }
    Path(partition_registry_out).parent.mkdir(parents=True, exist_ok=True)
    Path(partition_registry_out).write_text(
        json.dumps(part_registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "n_sessions": len(expected),
        "n_rows": part_registry["n_rows"],
        "n_partitions": len(partitions),
        "merged_stats": merged_stats,
        "energy_consistency": energy,
        "n_failed_sessions": n_failed,
        "partitions": part_registry["partitions"],
    }


def finalize_existing_partitions(
    registry: pd.DataFrame,
    cfg: dict[str, Any],
    out_dir: str | Path,
    partition_registry_out: str | Path,
) -> dict[str, Any]:
    """从已写出的 site/year/month 最终分区重建注册表/覆盖/统计/能量审计。

    用于 E0F-03 构建中断后免重建收尾。最终分区与全新构建完全一致，本函数只做
    canonical 分钟表上的确定性二次核算（主键唯一、分区统计、去重会话覆盖、能量
    一致性），能量口径与 build 路径一致（基于 energy_cum_kwh 的分钟表峰值跨度）。
    """
    out_dir = Path(out_dir)
    files = sorted(out_dir.glob("site=*/year=*/month=*/data.parquet"))
    if not files:
        raise RuntimeError(f"E0F-03 finalize 停止：{out_dir} 下无最终分区")
    gov = _session_governance_index(registry)
    partitions: list[dict[str, Any]] = []
    merged_stats: dict[str, Any] = {}
    covered: set[str] = set()
    accs: dict[str, dict[str, Any]] = {}

    for f in files:
        rel = f.relative_to(out_dir)
        site = rel.parts[0].split("=", 1)[1]
        year = int(rel.parts[1].split("=", 1)[1])
        month = int(rel.parts[2].split("=", 1)[1])
        df = pd.read_parquet(f)
        _assert_partition_path_consistent(df, site, year, month, "finalize")
        _assert_session_governance(df, gov, f, "finalize")
        if df.duplicated(subset=["session_id", "timestamp_utc"]).any():
            raise RuntimeError(
                f"E0F-03 finalize 停止（主键非法重复）：{f} 内 "
                "[session_id, timestamp_utc] 不唯一"
            )
        partitions.append(
            {
                "site": site,
                "year": year,
                "month": month,
                "rows": int(len(df)),
                "sessions": int(df["session_id"].nunique()),
                "sha256": _sha256_file(f),
            }
        )
        _merge_stats(merged_stats, _partition_stats(df))
        covered.update(df["session_id"].astype(str).to_numpy())
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
                    "ref_api_kwh": _to_float(g["kwh_delivered"].iloc[0]),
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

    audits = [accs[sid] for sid in sorted(accs)]
    return _build_final_registry(
        partitions=partitions,
        merged_stats=merged_stats,
        covered=covered,
        audits=audits,
        cfg=cfg,
        expected=set(registry["session_id"].astype(str)),
        partition_registry_out=partition_registry_out,
        n_failed=0,
    )


def _flush_part(
    key: tuple[str, int, int],
    pending: dict[tuple[str, int, int], list[pd.DataFrame]],
    part_files: dict[tuple[str, int, int], list[Path]],
    tmp_dir: Path,
) -> None:
    frames = pending.pop(key, [])
    if not frames:
        return
    df = pd.concat(frames, ignore_index=True)
    seq = len(part_files.get(key, []))
    p = tmp_dir / f"part_{key[0]}_{key[1]}_{key[2]:02d}_{seq}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    part_files.setdefault(key, []).append(p)


def _build_report(summary: dict[str, Any], cfg: dict[str, Any]) -> str:
    frozen = cfg["inputs"]["manifests"]
    lines: list[str] = [
        "# E0-Full 会话分钟响应表审计（E0F-03）",
        "",
        "## 口径声明",
        "",
        "session_response_1min 只把原始响应转成可追溯的 canonical 分钟观测，不定义",
        "可执行能力、不生成吸收余量、不做 D1-R 模型判断（那是 E1/E2 的事）。",
        f"- universe：{summary['n_sessions']:,} 个有静态时序的会话原样继承"
        f"（frozen {int(frozen['static_file_index_rows']):,}）；session_id/split/role/"
        "sample_layer/field_mode 只从 E0F-02 registry join，禁止重推导。",
        "- 派生层 exact-duplicate collapse（逐字节相同原始行保留首次出现），逐分钟登记"
        " raw_duplicate_count；同时间戳不同观测保留进入确定性分钟聚合。",
        "- actual_power_kw 冻结优先级 measured→computed→estimated（rated："
        "jpl=192.7/caltech=240/office001=240）。",
        "- 主键 [session_id, timestamp_utc(1min)] 唯一，非法重复 hard STOP。",
        "- 全局唯一证明（E0F-03.2 三腿合成）：每行治理列（site/split/role/sample_layer/"
        "field_mode/match_status/external/stress）必须等于 E0F-02 registry 该会话值"
        "（session_id → 唯一 canonical site）+ timestamp → 唯一 year/month 分区 + 分区内"
        " key unique，无需维护 28.3M key 的全局集合。",
        "- disconnect_time/done_charging_time/kwh_delivered 只作离线标签与能量审计基准，"
        "禁止在线特征。",
        f"- 分区：site/year/month，共 {summary['n_partitions']} 个分区，"
        f"{summary['n_rows']:,} 行；test 分区只做数据工程检查，不查看 outcome 指标。",
        "",
    ]
    stats = summary["merged_stats"]
    lines += ["## 质量标记汇总（分钟级）", ""]
    lines.append(f"- 总分钟数：{stats.get('rows', 0):,}")
    lines.append(f"- gap_flag（sample_count<10）分钟：{stats.get('gap_minutes', 0):,}")
    lines.append(
        f"- severe_gap_before（>=20min 缺口）分钟：{stats.get('severe_gap_before_minutes', 0):,}"
    )
    lines.append(f"- 失败会话：{summary['n_failed_sessions']}")
    ps = stats.get("power_source", {})
    lines.append(
        "- power_source 分布："
        + "；".join(f"{k}={v:,}" for k, v in sorted(ps.items()))
    )
    lines.append("")
    lines += ["## 能量一致性审计", ""]
    for site, v in summary["energy_consistency"].get("by_site", {}).items():
        lines.append(
            f"- {site}：n={v['sessions']:,}，中位|dev|={v['median_abs_dev']}，"
            f"p95={v['p95_abs_dev']}，|dev|>20% 会话={v['n_outliers_gt_20pct']}"
        )
    for site, v in summary["energy_consistency"].get("api_kwh", {}).items():
        lines.append(
            f"- {site}（vs API kWhDelivered）：n={v['sessions']:,}，"
            f"中位|dev|={v['median_abs_dev']}，p95={v['p95_abs_dev']}"
        )
    tol = cfg["session_response"]["energy_consistency"]["tolerance_median_dev"]
    lines.append("")
    lines.append(
        f"caltech/office001 分钟积分 vs 原始能量跨度中位 |dev| >= {tol} 即硬 STOP"
        "（门线用原始中位，等值即 STOP；round 只用于报告显示）；"
        "jpl 聚合可用、会话级离群过滤后另报（不做 STOP）。"
    )
    lines.append(
        "能量跨度口径：原始能量为累计计量，会话末尾 UNPLUGGED 复位行（仪表 re-arm 到 0.0）"
        "为已知伪影；基于 canonical 分钟表 energy_cum_kwh 计算，energy_last 取分钟峰值、"
        "energy_first 取首条非空分钟读数（口径与 build/finalize 两条路径一致）。"
    )
    lines.append("")
    lines += ["## 数据质量风险登记（D0/#16 P1 debt）", ""]
    amber_sites = [
        (site, v["median_abs_dev"])
        for site, v in summary["energy_consistency"].get("by_site", {}).items()
        if site in ("caltech", "office001")
        and v["median_abs_dev"] is not None
        and v["median_abs_dev"] >= tol * 0.8
    ]
    if amber_sites:
        for site, med in amber_sites:
            lines.append(
                f"- **{site}**：中位 |dev|={med} 已达冻结门线 {tol} 的 80%，标记为 Amber。"
                "不改变 E1 主样本定义、不删样本；在 D0/#16 按 month × split × field_mode "
                "报告 energy deviation 分布（≤5% / 5–20% / >20%），并在 train/validation/"
                "test、frozen K1 months、field_mode、site 上做高偏差会话敏感性分析。"
            )
    else:
        lines.append("- 无站点接近门线，无需 Amber 登记。")
    lines.append("")
    lines += ["## 分区清单（行数/会话数，sha256 见 partition registry）", ""]
    lines.append(
        "| site | year | month | rows | sessions |\n"
        "|---|---|---|---|---|"
    )
    for p in summary["partitions"]:
        lines.append(
            f"| {p['site']} | {p['year']} | {p['month']:02d} | {p['rows']:,} | {p['sessions']:,} |"
        )
    lines.append("")
    lines += [
        "## 规则依据",
        "",
        f"- 分区：`{cfg['outputs']['session_minute_1min']}`（site/year/month）",
        f"- collapse：`{cfg['session_response']['collapse_rule']}`",
        f"- 功率优先级：`{cfg['power']['priority']}`",
        f"- 本地时区：`{cfg['session_response']['timezone_local']}`",
        f"- minute_sample_threshold：`{cfg['session_response']['minute_sample_threshold']}`",
        f"- severe_gap_min：`{cfg['session_response']['severe_gap_min']}`",
    ]
    return "\n".join(lines) + "\n"


def _update_quality_summary(quality_path: Path, summary: dict[str, Any]) -> None:
    if not quality_path.exists():
        return
    data = json.loads(quality_path.read_text(encoding="utf-8"))
    data["session_response_1min"] = {
        "sessions_total": summary["n_sessions"],
        "rows_total": summary["n_rows"],
        "n_partitions": summary["n_partitions"],
        "n_failed_sessions": summary["n_failed_sessions"],
        "uniqueness_ok": True,
        "energy_consistency": summary["energy_consistency"],
    }
    quality_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_e0f03(
    cfg_path: str | Path | None = None,
    static_root: str | Path | None = None,
    acn_project: str | Path | None = None,
    max_workers: int | None = None,
    finalize_only: bool = False,
) -> dict[str, Any]:
    """E0F-03 全量执行：session_response_1min 分区 → 分区注册表 → 报告 → 质量摘要 → baseline。

    产物：
    - datasets/session_response_1min/site=<site>/year=YYYY/month=MM/data.parquet
    - data_registry/e0_full_session_response_partitions.json
    - reports/E0_Full_session_response_audit.md
    - data_registry/e0_full_quality_summary.json（追加 session_response_1min 节）
    - data_registry/e0_full_baseline.json（追加 session_response_registry 节）

    finalize_only=True：跳过并行构建，直接对已写出的最终分区做确定性二次核算
    （注册表/覆盖/统计/能量审计），用于构建中断后的免重建收尾。
    """
    impl_root = Path(__file__).resolve().parents[3]
    cfg = load_yaml(cfg_path or (impl_root / "configs" / "e0_full.yaml"))
    acn = Path(acn_project) if acn_project is not None else acn_project_dir()
    root = Path(static_root) if static_root is not None else static_root_dir()

    registry = pd.read_parquet(impl_root / "data_registry" / "e0_full_split_registry.parquet")
    manifest = pd.read_parquet(impl_root / "data_registry" / "e0_full_source_manifest.parquet")
    api_meta = pd.read_csv(acn / "manifests" / "api_metadata_index.csv", dtype=str)

    frozen = cfg["inputs"]["manifests"]
    n_all = int(frozen["static_file_index_rows"])
    n_matched = int(frozen["match_status"]["matched"])
    n_static = int(frozen["match_status"]["static_only"])
    if len(registry) != n_all:
        raise RuntimeError(
            f"E0F-03 人口冻结 STOP：registry {len(registry)} != 冻结 {n_all}"
        )
    if int((registry["match_status"] == "matched").sum()) != n_matched:
        raise RuntimeError(f"E0F-03 人口冻结 STOP：matched 数 != 冻结 {n_matched}")
    if int((registry["match_status"] == "static_only").sum()) != n_static:
        raise RuntimeError(f"E0F-03 人口冻结 STOP：static_only 数 != 冻结 {n_static}")

    out_dir = impl_root / cfg["outputs"]["session_minute_1min"]
    part_registry_out = impl_root / "data_registry" / "e0_full_session_response_partitions.json"
    if finalize_only:
        summary = finalize_existing_partitions(
            registry=registry,
            cfg=cfg,
            out_dir=out_dir,
            partition_registry_out=part_registry_out,
        )
    else:
        summary = build_session_response(
            registry=registry,
            manifest=manifest,
            api_meta=api_meta,
            cfg=cfg,
            static_root=root,
            out_dir=out_dir,
            partition_registry_out=part_registry_out,
            max_workers=max_workers,
        )

    report = _build_report(summary, cfg)
    report_out = impl_root / "reports" / "E0_Full_session_response_audit.md"
    report_out.write_text(report, encoding="utf-8")

    _update_quality_summary(impl_root / "data_registry" / "e0_full_quality_summary.json", summary)

    baseline_out = impl_root / "data_registry" / "e0_full_baseline.json"
    prev_baseline: dict[str, Any] = {}
    if baseline_out.exists():
        prev_baseline = json.loads(baseline_out.read_text(encoding="utf-8"))
    manifest_hash_hex = prev_baseline.get("source_manifest_sha256")
    split_registry_meta = prev_baseline.get("split_registry")

    from patent_preexperiment.e0_full.baseline import build_e0_full_baseline
    from patent_preexperiment.e0_full.input_audit import manifest_hash

    session_response_meta = {
        "partition_registry": {
            "sha256": _sha256_file(part_registry_out),
            "n_partitions": summary["n_partitions"],
            "n_sessions": summary["n_sessions"],
            "n_rows": summary["n_rows"],
        },
        "report": str(report_out.relative_to(impl_root)).replace("\\", "/"),
    }
    build_e0_full_baseline(
        out=baseline_out,
        manifest_hash_hex=str(manifest_hash_hex) if manifest_hash_hex else manifest_hash(manifest),
        config=cfg,
        require_clean=True,
        split_registry=split_registry_meta,
        session_response=session_response_meta,
    )

    return {
        "partition_dir": str(out_dir),
        "partition_registry": str(part_registry_out),
        "report": str(report_out),
        "baseline": str(baseline_out),
        "summary": summary,
    }
