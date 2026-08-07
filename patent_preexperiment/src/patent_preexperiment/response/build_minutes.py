"""E0-Lite 分钟表批量构建（ProcessPool 并行、有界内存分片，V2.1 §5.3）。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd

from patent_preexperiment.io.paths import resolve_static
from patent_preexperiment.io.static import read_static_csv
from patent_preexperiment.response.session import aggregate_session_minute

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "k1_preregister.yaml"
SAMPLE_REG = Path(__file__).resolve().parents[3] / "data_registry" / "k1_sample_registry.csv"


def _to_ts(value: Any) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return pd.Timestamp(value)
    except (ValueError, TypeError):
        return None


def _worker(row: dict[str, Any]) -> pd.DataFrame:
    from patent_preexperiment.config.yamlutil import load_yaml

    cfg = load_yaml(CONFIG)
    rated_v = cfg["rated_voltage"][row["site"]]
    path = resolve_static(row["static_file"])
    try:
        raw = read_static_csv(path)
        return aggregate_session_minute(
            raw,
            rated_v,
            session_id=row["sessionID"],
            station_id=row["stationID"],
            site=row["site"],
            garage=row["garage"],
            disconnect_time=_to_ts(row["disconnectTime"]),
            done_charging_time=_to_ts(row["doneChargingTime"]),
        )
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame([{"session_id": row["sessionID"], "parse_error": str(exc)}])


def _frame_ok(f: pd.DataFrame) -> bool:
    return not f.empty and "parse_error" not in f.columns


def build_minutes(
    out: str | Path, max_workers: int | None = None, batch_size: int = 1024
) -> pd.DataFrame:
    reg = pd.read_csv(SAMPLE_REG, dtype=str)
    workers = max_workers or 4
    tmp = Path(out).with_suffix("") / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = [
        {str(k): v for k, v in r.to_dict().items()} for _, r in reg.iterrows()
    ]
    n = len(rows)
    parse_fail: list[str] = []
    batch_files: list[Path] = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for start in range(0, n, batch_size):
            chunk = rows[start : start + batch_size]
            futs = {ex.submit(_worker, r): r["sessionID"] for r in chunk}
            frames: list[pd.DataFrame] = []
            for fut in as_completed(futs):
                f = fut.result()
                if _frame_ok(f):
                    frames.append(f)
                else:
                    parse_fail.append(f["session_id"].iloc[0])
            if frames:
                bf = tmp / f"batch_{start // batch_size:04d}.parquet"
                pd.concat(frames, ignore_index=True).to_parquet(bf, index=False)
                batch_files.append(bf)
            del frames
    all_df = pd.concat([pd.read_parquet(b) for b in batch_files], ignore_index=True)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    all_df.to_parquet(out, index=False)
    if parse_fail:
        print(f"[build_minutes] 解析失败 {len(parse_fail)} 个文件，已跳过")
    return all_df


if __name__ == "__main__":
    import sys

    out = Path(__file__).resolve().parents[3] / "datasets" / "lite_session_minute.parquet"
    df = build_minutes(out)
    print(f"sessions={df['session_id'].nunique()} rows={len(df)}")
    print(df.groupby("site").size().to_dict())
    sys.exit(0)
