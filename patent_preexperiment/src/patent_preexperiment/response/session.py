"""E0-Lite/E1-Lite：静态文件 → 1 分钟会话表聚合（V2.1 §5.3）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

MINUTE = pd.Timedelta("1min")


def _bucket_ts(ts: pd.Series) -> pd.Series:
    return ts.dt.floor("min")


def _mode(series: pd.Series) -> str:
    if series.dropna().empty:
        return ""
    return series.dropna().mode().iloc[0]


def derive_power(df_raw: pd.DataFrame, rated_v: float) -> pd.DataFrame:
    """功率优先级：实测 Power → Voltage×Current(computed) → 额定×Current(estimated)。"""
    df = df_raw.copy()
    power = df["power_kw"]
    computed = power.isna() & df["voltage_v"].notna() & df["current_a"].notna()
    estimated = power.isna() & df["current_a"].notna()
    out = pd.DataFrame(index=df.index, columns=["actual_power_kw", "power_source"], dtype=object)
    out.loc[power.notna(), "actual_power_kw"] = power[power.notna()]
    out.loc[power.notna(), "power_source"] = "measured"
    out.loc[computed, "actual_power_kw"] = df.loc[computed, "voltage_v"] * df.loc[computed, "current_a"] / 1000.0
    out.loc[computed, "power_source"] = "computed"
    out.loc[estimated, "actual_power_kw"] = df.loc[estimated, "current_a"] * rated_v / 1000.0
    out.loc[estimated, "power_source"] = "estimated"
    df["actual_power_kw"] = pd.to_numeric(out["actual_power_kw"], errors="coerce")
    df["power_source"] = out["power_source"].astype(str)
    return df


def aggregate_session_minute(
    df_raw: pd.DataFrame,
    rated_v: float,
    session_id: str,
    station_id: str,
    site: str,
    garage: str,
    disconnect_time: pd.Timestamp | None = None,
    done_charging_time: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """原始秒级样本聚合为 1 分钟会话表（均值 + 前向保持能量 + 质量标记）。"""
    df = df_raw.dropna(subset=["current_a"]).copy()
    df = derive_power(df, rated_v)
    df["ts_min"] = _bucket_ts(df["timestamp"])

    g = df.groupby("ts_min")
    out = g.agg(
        current_a=("current_a", "mean"),
        pilot_a=("pilot_a", "mean"),
        voltage_v=("voltage_v", "mean"),
        power_kw=("power_kw", "mean"),
        actual_power_kw=("actual_power_kw", "mean"),
        power_source=("power_source", lambda s: s.mode().iloc[0] if not s.empty else ""),
        state=("state", lambda s: s.dropna().mode().iloc[0] if not s.dropna().empty else ""),
        energy_kwh=("energy_kwh", "last"),
        sample_count=("current_a", "size"),
    ).reset_index()

    first = df["timestamp"].min()
    out["session_id"] = session_id
    out["station_id"] = station_id
    out["site"] = site
    out["garage"] = garage
    out["timestamp_utc"] = out["ts_min"]
    out["connected_elapsed_min"] = (out["ts_min"] - first).dt.total_seconds() // 60
    out["minutes_from_end"] = pd.Series(np.nan, index=out.index, dtype="float64")
    out["disconnect_time"] = pd.Series(pd.NA, index=out.index, dtype="object")
    out["done_charging_time"] = pd.Series(pd.NA, index=out.index, dtype="object")
    if disconnect_time is not None:
        out["minutes_from_end"] = (disconnect_time - out["ts_min"]).dt.total_seconds() / 60.0
        out["disconnect_time"] = disconnect_time
    if done_charging_time is not None:
        out["done_charging_time"] = done_charging_time
    out["pilot_power_kw"] = out["pilot_a"] * rated_v / 1000.0
    out["pilot_available"] = out["pilot_a"].notna()
    out["gap_flag"] = out["sample_count"] < 10
    out = out.drop(columns=["ts_min"])
    return out[["session_id", "station_id", "site", "garage", "timestamp_utc", "connected_elapsed_min",
                "current_a", "voltage_v", "power_kw", "actual_power_kw", "power_source",
                "pilot_a", "pilot_power_kw", "pilot_available", "state", "energy_kwh",
                "sample_count", "gap_flag", "minutes_from_end", "disconnect_time", "done_charging_time"]]
