"""P2.1A B3 trigger map（v1.3 §4.3 C2——一次生成、永久固定）。

对每个 (session_id, M3_segment_id)，用 hash(global_seed=20260813_A, session_id, segment_id)
从该 segment 的 eligible-risk-set cycles 中均匀选 1 个 trigger。

- **稳定 hash**：`hashlib.md5` 机械映射（禁止 Python built-in `hash()`，跨进程不稳定）。
- **一次生成、永久固定**：首次构建后保存为 artifact（parquet）；bootstrap 只查表，
  不重新随机（避免 cluster 被重复抽到时产生新 realization）。
- 每 segment 抽 1 次（不重复抽样取最优）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from patent_preexperiment.phase3_p2_1.frozen import FROZEN

B3_MAP_ARTIFACT = "b3_trigger_map.parquet"


def _stable_hash(*parts: str) -> int:
    """md5 稳定机械映射：int(md5('|'.join(parts))[:8], 16)。"""
    key = "|".join(parts).encode("utf-8")
    return int(hashlib.md5(key).hexdigest()[:8], 16)


def build_b3_map(eligible: pd.DataFrame) -> pd.DataFrame:
    """从 eligible risk set 构建固定 B3 trigger map（每 segment 1 行）。

    输入 eligible 必须含 segment_id / session_id / timestamp_utc（build_eligible_risk_set 输出）。
    输出列：
      segment_id, session_id, run_id, timestamp_utc, cycle_index,
      protective_bound, actual_power_kw
    """
    if eligible.empty:
        return pd.DataFrame(
            columns=[
                "segment_id", "session_id", "run_id", "timestamp_utc", "cycle_index",
                "protective_bound", "actual_power_kw",
            ]
        )

    rows: list[dict] = []
    for segment_id, seg in eligible.groupby("segment_id", sort=True):
        seg = seg.sort_values("timestamp_utc")
        session_id = str(seg["session_id"].iloc[0])
        h = _stable_hash(FROZEN.b3_global_seed, session_id, str(segment_id))
        chosen = seg.iloc[h % len(seg)]
        rows.append(
            {
                "segment_id": segment_id,
                "session_id": session_id,
                "run_id": int(chosen["run_id"]),
                "timestamp_utc": chosen["timestamp_utc"],
                "cycle_index": int(chosen["cycle_index"]),
                "protective_bound": float(chosen["protective_bound"]),
                "actual_power_kw": float(chosen["actual_power_kw"]),
            }
        )
    return pd.DataFrame(rows)


def save_b3_map(b3_map: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    b3_map.to_parquet(path, index=False)
    return path


def load_b3_map(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def build_or_load_b3_map(
    eligible: pd.DataFrame,
    artifact_path: Path,
) -> pd.DataFrame:
    """C2 一次生成、永久固定——artifact 优先 + 语义校验。

    - artifact 不存在：构建并保存（首次）。
    - artifact 存在：load + 从当前 eligible 重新构建（确定性）并逐行比对：
        * 完全一致 → 复用 artifact（不覆盖写）；
        * 不一致 → hard fail（eligible risk set 与 artifact 生成时不同，
          说明 Step-0 数据/代码漂移；C2 禁止静默换 realization）。

    返回 artifact 中的 map（= 生成时的 realization，永久固定）。
    """
    freshly_built = build_b3_map(eligible)
    if not artifact_path.exists():
        save_b3_map(freshly_built, artifact_path)
        return freshly_built
    stored = load_b3_map(artifact_path)
    _assert_b3_map_equal(stored, freshly_built, artifact_path)
    return stored  # 复用，不覆盖


def _assert_b3_map_equal(
    stored: pd.DataFrame, expected: pd.DataFrame, path: Path
) -> None:
    """逐行校验 stored 与 freshly-built map 一致。"""
    if list(stored.columns) != list(expected.columns):
        raise RuntimeError(
            f"B3 map C2 漂移（列不一致）：stored={list(stored.columns)} "
            f"!= expected={list(expected.columns)}（artifact={path}）"
        )
    if len(stored) != len(expected):
        raise RuntimeError(
            f"B3 map C2 漂移（行数）：stored={len(stored)} != expected={len(expected)}"
            f"（artifact={path}）"
        )
    s = stored.sort_values("segment_id").reset_index(drop=True)
    e = expected.sort_values("segment_id").reset_index(drop=True)
    if not (s["segment_id"].to_numpy() == e["segment_id"].to_numpy()).all():
        raise RuntimeError(f"B3 map C2 漂移（segment_id 集合不一致）（artifact={path}）")
    for col in ("session_id", "timestamp_utc", "cycle_index"):
        if not (s[col].to_numpy() == e[col].to_numpy()).all():
            raise RuntimeError(
                f"B3 map C2 漂移（列 {col} 选中的 cycle 不同）（artifact={path})"
            )


def _b3_selected_cycle_rows(
    eligible: pd.DataFrame,
    b3_map: pd.DataFrame,
) -> pd.DataFrame:
    """把 B3 map 命中的 cycle 对回 eligible 行（每 segment 1 行，列与 eligible 相同）。

    C2 语义：map 固定，查询返回同一 realization；命中行缺失 → fail-closed（抛错）。
    """
    if b3_map.empty:
        return pd.DataFrame(columns=eligible.columns)
    keys = ["segment_id", "timestamp_utc"]
    joined = eligible.reset_index().merge(b3_map[keys], on=keys, how="inner")
    if len(joined) != len(b3_map):
        raise RuntimeError(
            f"B3 map 对回 eligible 行数不一致：map={len(b3_map)}，命中={len(joined)}"
        )
    joined = joined.set_index("index")
    joined.index.name = None
    return joined
