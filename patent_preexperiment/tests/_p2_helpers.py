"""P2 单测合成池助手：构造与 E0 生产 schema 一致（_MINUTE_COLUMNS）的会话分钟表。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.phase3_p2.actions import seed_byte
from patent_preexperiment.phase3_p2.schema import SchemaConfig

_MINUTE_COLUMNS = [
    "session_id",
    "station_id",
    "site",
    "field_mode",
    "match_status",
    "sample_layer",
    "split",
    "timestamp_utc",
    "actual_power_kw",
    "pilot_available",
    "pilot_power_kw",
    "severe_gap_before",
    "gap_before_min",
    "connected_elapsed_min",
]

_START = pd.Timestamp("2018-11-01 00:00:00", tz="UTC")


def make_session(
    session_id: str,
    site: str,
    field_mode: str,
    n_minutes: int,
    *,
    actual: list[float] | np.ndarray | float,
    severe_gap: list[bool] | None = None,
    pilot_power_kw: float | None = 6.0,
    pilot_available: bool = True,
    match_status: str = "matched",
    sample_layer: str = "L1_strict_matched",
    split: str = "train",
    start: pd.Timestamp = _START,
) -> pd.DataFrame:
    """构造一个会话的 1-min 行。

    - current_only 会话：pilot_available=False、pilot_power_kw=NaN。
    - measured_pilot 会话：pilot_available=True、pilot_power_kw 非空。
    """
    if field_mode == "current_only":
        pilot_available = False
        pilot_power_kw = None

    n = int(n_minutes)
    if isinstance(actual, (int, float)):
        actual_vals = np.full(n, float(actual))
    else:
        actual_vals = np.asarray(actual, dtype=float)
        if len(actual_vals) != n:
            raise ValueError(f"actual 长度 {len(actual_vals)} != n_minutes {n}")

    severe = severe_gap if severe_gap is not None else [False] * n
    if len(severe) != n:
        raise ValueError(f"severe_gap 长度 {len(severe)} != n_minutes {n}")

    pilot = (
        np.full(n, np.nan, dtype=float)
        if pilot_power_kw is None
        else np.full(n, pilot_power_kw)
    )
    return pd.DataFrame(
        {
            "session_id": [session_id] * n,
            "station_id": [f"{site}-ST-{session_id}"] * n,
            "site": [site] * n,
            "field_mode": [field_mode] * n,
            "match_status": [match_status] * n,
            "sample_layer": [sample_layer] * n,
            "split": [split] * n,
            "timestamp_utc": pd.to_datetime(
                [start + pd.Timedelta(minutes=i) for i in range(n)], utc=True
            ),
            "actual_power_kw": actual_vals,
            "pilot_available": [pilot_available] * n,
            "pilot_power_kw": pilot,
            "severe_gap_before": severe,
            "gap_before_min": [0.0] * n,
            "connected_elapsed_min": list(range(n)),
        }
    )[_MINUTE_COLUMNS]


def stable_current_only_session(
    session_id: str, n_minutes: int, actual_kw: float = 5.0
) -> pd.DataFrame:
    """稳定充电 current-only 会话（natural M3 域）：高功率足够边界>预算，支持 D3 recovery。"""
    return make_session(
        session_id,
        site="jpl",
        field_mode="current_only",
        n_minutes=n_minutes,
        actual=actual_kw,
    )


def stable_pilot_session(
    session_id: str, n_minutes: int, actual_kw: float = 5.0, pilot_kw: float = 6.0
) -> pd.DataFrame:
    """稳定充电 measured_pilot 会话（M2 域）。"""
    return make_session(
        session_id,
        site="caltech",
        field_mode="measured_pilot",
        n_minutes=n_minutes,
        actual=actual_kw,
        pilot_power_kw=pilot_kw,
    )


def session_seed(session_id: str) -> int:
    return seed_byte(session_id)


def low_budget_seed(scfg: SchemaConfig) -> int:
    """找一个 seed_byte 使 budget == budget_base（=3.0，最大边界余量）。"""
    ids = low_budget_session_ids(scfg, 1)
    return session_seed(ids[0])


def low_budget_session_ids(scfg: SchemaConfig, n: int) -> list[str]:
    """返回 n 个 seed%budget_modulus==0（budget=base）的会话 id。"""
    out: list[str] = []
    for i in range(10_000):
        sid = f"p2sess_b{i:05d}"
        if session_seed(sid) % scfg.budget_modulus == 0:
            out.append(sid)
            if len(out) == n:
                return out
    raise AssertionError(f"仅找到 {len(out)}/{n} 个 low-budget session id")
