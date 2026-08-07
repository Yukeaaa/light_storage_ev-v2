"""E0-Full 时间切分参考实现与测试（审查结论7 §6.1/§6.3；审查结论8 P1-3；V2.1 §10.3）。

本文件内的 `assign_split` 是切分规则的参考实现（金标准），E0F-02 生产实现必须与之对齐：
- 站点内按 session 排序后前 60% train / 中 20% validation / 后 20% test；
- 排序键为 [connection_time, session_id]（mergesort 稳定排序），相同 connection_time
  用 session_id 做确定性 tie-break，保证 split 与输入顺序无关；
- 整条会话属于唯一 split，绝不按分钟切分；
- external / stress 会话单独标记，不进入主 train/validation/test；
- 无随机性，同输入必得同输出。
"""

from __future__ import annotations

import pandas as pd
import pytest

TRAIN_RATIO = 0.6
VAL_RATIO = 0.2


def assign_split(
    sessions: pd.DataFrame,
    train_ratio: float = TRAIN_RATIO,
    val_ratio: float = VAL_RATIO,
) -> pd.DataFrame:
    """参考切分实现。输入列：session_id, site, connection_time, is_external, is_stress。

    Returns: 与输入同序的 DataFrame，追加 `split` 列（train/validation/test/external/stress）。
    """
    out = sessions.copy()
    out["split"] = ""
    if len(out) == 0:
        return out
    if not out["session_id"].is_unique:
        raise ValueError("切分输入必须是会话级：session_id 不得重复（禁止按分钟切分）")

    ext = out["is_external"].astype(bool)
    stress = out["is_stress"].astype(bool)
    out.loc[ext, "split"] = "external"
    out.loc[stress & ~ext, "split"] = "stress"

    eligible = out[~(ext | stress)].copy()
    for _site, g in eligible.groupby("site", sort=False):
        g = g.sort_values(["connection_time", "session_id"], kind="mergesort")
        n = len(g)
        n_train = int(round(n * train_ratio))
        n_val = int(round(n * val_ratio))
        n_test = n - n_train - n_val
        labels = ["train"] * n_train + ["validation"] * n_val + ["test"] * n_test
        out.loc[g.index, "split"] = labels
    return out


def _synth_sessions(n: int, site: str = "caltech", n_sites: int = 1) -> pd.DataFrame:
    """n 条会话：connection_time 每 10 分钟一条，跨 n_sites 个站点均匀分布。"""
    start = pd.Timestamp("2018-11-01 08:00:00")
    times = [start + pd.Timedelta(minutes=10 * i) for i in range(n)]
    sites = [f"site_{i % n_sites}" for i in range(n)]
    return pd.DataFrame({
        "session_id": [f"s{i:04d}" for i in range(n)],
        "site": sites,
        "connection_time": times,
        "is_external": False,
        "is_stress": False,
    })


def test_split_deterministic() -> None:
    df = _synth_sessions(1000, n_sites=2)
    a = assign_split(df)
    b = assign_split(df)
    pd.testing.assert_series_equal(a["split"], b["split"])


def test_split_output_same_shape_and_order() -> None:
    df = _synth_sessions(100)
    out = assign_split(df)
    assert len(out) == len(df)
    assert out["session_id"].tolist() == df["session_id"].tolist()
    assert set(out["split"]) <= {"train", "validation", "test"}


def test_session_single_split() -> None:
    df = _synth_sessions(1000, n_sites=2)
    out = assign_split(df)
    assert out.groupby("session_id")["split"].nunique().eq(1).all()
    assert not out["split"].eq("").any()


def test_ratios_approximately_60_20_20_per_site() -> None:
    df = _synth_sessions(3000, n_sites=3)
    out = assign_split(df)
    for _site, g in out.groupby("site"):
        shares = g["split"].value_counts(normalize=True)
        assert shares.get("train", 0.0) == pytest.approx(0.6, abs=0.02)
        assert shares.get("validation", 0.0) == pytest.approx(0.2, abs=0.02)
        assert shares.get("test", 0.0) == pytest.approx(0.2, abs=0.02)


def test_boundaries_monotonic_per_site() -> None:
    df = _synth_sessions(2000, n_sites=2)
    out = assign_split(df)
    for _site, g in out.groupby("site"):
        tr = g.loc[g["split"] == "train", "connection_time"]
        va = g.loc[g["split"] == "validation", "connection_time"]
        te = g.loc[g["split"] == "test", "connection_time"]
        assert tr.max() <= va.min()
        assert va.max() <= te.min()


def test_external_and_stress_excluded_from_main() -> None:
    df = _synth_sessions(1000)
    df.loc[[0, 1], "is_external"] = True
    df.loc[[2, 3], "is_stress"] = True
    out = assign_split(df)
    ext_splits = out.loc[out["session_id"].isin(["s0000", "s0001"]), "split"].tolist()
    assert ext_splits == ["external", "external"]
    stress_splits = out.loc[out["session_id"].isin(["s0002", "s0003"]), "split"].tolist()
    assert stress_splits == ["stress", "stress"]
    main = out[out["split"].isin(["train", "validation", "test"])]
    assert not main["session_id"].isin(["s0000", "s0001", "s0002", "s0003"]).any()


def test_split_ignores_insertion_order() -> None:
    df = _synth_sessions(200)
    shuffled = df.sample(frac=1.0, random_state=7).reset_index(drop=True)
    a = assign_split(df).set_index("session_id")["split"]
    b = assign_split(shuffled).set_index("session_id")["split"]
    pd.testing.assert_series_equal(a.sort_index(), b.sort_index())


def test_split_tie_connection_time_deterministic() -> None:
    # 多个 session 的 connection_time 完全相同：split 不得依赖原始输入顺序
    t = pd.Timestamp("2019-03-01 10:00:00")
    n = 80
    df = pd.DataFrame({
        "session_id": [f"s{i:04d}" for i in range(n)],
        "site": ["caltech"] * n,
        "connection_time": [t] * n,
        "is_external": False,
        "is_stress": False,
    })
    for seed in (3, 11, 19):
        shuffled = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
        a = assign_split(df).set_index("session_id")["split"]
        b = assign_split(shuffled).set_index("session_id")["split"]
        pd.testing.assert_series_equal(a.sort_index(), b.sort_index())
        assert set(b) == {"train", "validation", "test"}


def test_split_is_session_level_not_minute_level() -> None:
    # 切分必须按整条会话归属：任一 session_id 绝不出现两个 split 值
    many = _synth_sessions(100)
    out = assign_split(many)
    assert set(out["split"]) <= {"train", "validation", "test"}
    assert out.groupby("session_id")["split"].nunique().eq(1).all()


def test_split_rejects_minute_level_input() -> None:
    # 分钟级输入（同一会话多行）必须被拒绝：禁止按分钟分别切分
    df = _synth_sessions(50)
    dup = pd.concat([df, df], ignore_index=True)
    with pytest.raises(ValueError, match="会话级"):
        assign_split(dup)


def test_small_n_edges() -> None:
    one = _synth_sessions(1)
    out = assign_split(one)
    assert out.iloc[0]["split"] == "train"

    empty = _synth_sessions(0)
    out0 = assign_split(empty)
    assert len(out0) == 0
    assert "split" in out0.columns
