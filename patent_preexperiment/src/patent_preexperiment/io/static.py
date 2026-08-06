"""ACN 静态时序文件读取（支持 gzip 尾部垃圾恢复，按首成员解压）。"""

from __future__ import annotations

import io
import zlib
from pathlib import Path

import pandas as pd

_RAW_COLS = {
    "Charging Current (A)": "current_a",
    "Actual Pilot (A)": "pilot_a",
    "Voltage (V)": "voltage_v",
    "Charging State": "state",
    "Energy Delivered (kWh)": "energy_kwh",
    "Power (kW)": "power_kw",
}


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


def read_static_csv(path: str | Path) -> pd.DataFrame:
    """读取单个静态 csv.gz，返回规范化列名的 DataFrame。"""
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = zlib.decompress(raw, zlib.MAX_WBITS | 16)
    except zlib.error:
        text = _decompress_first_gzip_member(raw)
    df = pd.read_csv(io.BytesIO(text), header=0, skip_blank_lines=False)
    df = df.rename(columns=_RAW_COLS)
    time_col = df.columns[0]
    if time_col != "timestamp":
        df = df.rename(columns={time_col: "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", utc=True)
    for col in ("current_a", "pilot_a", "voltage_v", "power_kw", "energy_kwh"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "state" not in df.columns:
        df["state"] = pd.NA
    return df[["timestamp", "current_a", "pilot_a", "voltage_v", "state", "energy_kwh", "power_kw"]]
