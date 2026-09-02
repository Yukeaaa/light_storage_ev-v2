"""R2-C2a：ONLINE RECOVERY-RISK PREDICTABILITY GATE（R2-C2 第一子门，不跑 allocation）。

回答：用在线安全信息，能否比 reported_service_slack 明显更好地识别真实 post-charge temporal slack？

标签（离线）：T_slack = max(disconnect - doneCharging, 0)，has_slack = T_slack >= 15min。
参考决策时刻 t = 最新 userInput 的 modifiedAt（modifiedAt<=t 逐样本 guard）。
在线特征：connection age / reported remaining / reported minutesAvailable / requested kWh。
baseline：reported_service_slack = minutesAvailable - kWhRequested/rated_power*60。
candidate：OLS(T_slack ~ 在线特征)，caltech 站点内按 connectionTime 60/20/20 时序切分，
train 拟合 / validation 评价。
红线：T_slack/disconnect/doneCharging 只作离线标签；不用人工补能折扣函数。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from patent_preexperiment.config.yamlutil import load_yaml
from patent_preexperiment.core_search.r2_c1_gate import _extract_session_targets
from patent_preexperiment.core_search.r2_c_data_gate import _load_api_metadata
from patent_preexperiment.io.paths import get_paths

_PATENT_ROOT = Path(__file__).resolve().parents[3]
_MAPPING = Path(get_paths()["acn_project"]) / "manifests" / "static_api_mapping.csv"
_CONFIG = _PATENT_ROOT / "configs" / "core_search_r2c2.yaml"

_RATED_KW = 7.2
_SLACK_MIN = 15.0  # has_slack 阈值（分钟）


def _build_dataset() -> pd.DataFrame:
    """构建 session 级 slack 标签 + 在线特征（caltech matched，时序切分）。"""
    mapping = pd.read_csv(_MAPPING)
    m = mapping[mapping["match_status"] == "matched"].copy()
    site_map = dict(zip(m["sessionID"].astype(str), m["site_api"].astype(str), strict=True))
    matched = set(m["sessionID"].astype(str))
    api = _load_api_metadata()
    sess = _extract_session_targets(api)
    sess["sessionID"] = sess["sessionID"].astype(str)
    sess = sess[sess["sessionID"].isin(matched)].copy()
    sess["site"] = sess["sessionID"].map(site_map)
    sess = sess[sess["site"] == "caltech"].copy()

    conn = pd.to_datetime(sess["connectionTime"], errors="coerce", utc=True)
    disc = pd.to_datetime(sess["disconnectTime"], errors="coerce", utc=True)
    done = pd.to_datetime(sess["doneChargingTime"], errors="coerce", utc=True)
    mod = pd.to_datetime(sess["modifiedAt_last"], errors="coerce", utc=True)
    rd = pd.to_datetime(sess["requestedDeparture_last"], errors="coerce", utc=True)

    sess["t_slack_h"] = ((disc - done).dt.total_seconds() / 3600.0).clip(lower=0.0)
    sess["connection_age_min"] = (mod - conn).dt.total_seconds() / 60.0
    sess["reported_remaining_min"] = (rd - mod).dt.total_seconds() / 60.0
    sess["reported_minutes_available"] = pd.to_numeric(
        sess["minutesAvailable_last"], errors="coerce"
    )
    sess["requested_kwh"] = pd.to_numeric(sess["kWhRequested_last"], errors="coerce")
    sess["reported_need_min"] = sess["requested_kwh"] / _RATED_KW * 60.0

    # 参考时刻合法性：connection <= modifiedAt <= disconnect（modifiedAt 逐样本 guard）
    valid = (
        conn.notna() & disc.notna() & done.notna() & mod.notna()
        & sess["t_slack_h"].notna()
        & sess["reported_minutes_available"].notna()
        & sess["requested_kwh"].notna()
        & (mod >= conn) & (mod <= disc)
    )
    sess = sess[valid].copy()
    sess = sess.sort_values("connectionTime", kind="stable").reset_index(drop=True)

    # 时序 60/20/20 切分
    n = len(sess)
    n_train = int(n * 0.6)
    n_val = int(n * 0.2)
    split = np.where(
        np.arange(n) < n_train, "train",
        np.where(np.arange(n) < n_train + n_val, "validation", "test"),
    )
    sess["split"] = split
    return sess


def _auc(y: np.ndarray, score: np.ndarray) -> float:
    y = np.asarray(y, dtype=bool)
    score = np.asarray(score, dtype=float)
    n_pos = int(y.sum())
    n_neg = int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return np.nan
    ranks = pd.Series(score).rank(method="average").to_numpy()
    sum_pos_rank = float(ranks[y].sum())
    return (sum_pos_rank - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx = pd.Series(x).rank(method="average")
    ry = pd.Series(y).rank(method="average")
    return float(rx.corr(ry))


def _fit_ols(x: pd.DataFrame, y: pd.Series) -> np.ndarray:
    xm = x.to_numpy(dtype="float64")
    design = np.column_stack([np.ones(xm.shape[0]), xm])
    coef, *_ = np.linalg.lstsq(design, y.to_numpy(dtype="float64"), rcond=None)
    return cast(np.ndarray, coef)


def _predict_ols(x: pd.DataFrame, coef: np.ndarray) -> np.ndarray:
    xm = x.to_numpy(dtype="float64")
    design = np.column_stack([np.ones(xm.shape[0]), xm])
    return cast(np.ndarray, design @ coef)


def run_r2_c2a() -> dict[str, object]:
    cfg = load_yaml(_CONFIG)
    sess = _build_dataset()

    feat_cols = [
        "connection_age_min", "reported_remaining_min",
        "reported_minutes_available", "requested_kwh",
    ]
    has_slack = (sess["t_slack_h"] >= _SLACK_MIN / 60.0).to_numpy(dtype=bool)

    # baseline：reported_service_slack（仅用用户申报信息）
    baseline = (
        sess["reported_minutes_available"] - sess["requested_kwh"] / _RATED_KW * 60.0
    ).to_numpy(dtype="float64")

    train = sess[sess["split"] == "train"]
    val = sess[sess["split"] == "validation"]
    coef = _fit_ols(train[feat_cols], train["t_slack_h"])
    candidate = _predict_ols(sess[feat_cols], coef)

    c_val = candidate[val.index]
    b_val = baseline[val.index]

    # 评价指标（validation）
    auc_base = _auc(has_slack[val.index], b_val)
    auc_cand = _auc(has_slack[val.index], c_val)
    sp_base = _spearman(val["t_slack_h"].to_numpy(), b_val)
    sp_cand = _spearman(val["t_slack_h"].to_numpy(), c_val)

    # false-safe rate：预测"有 slack"实际"无 slack"的比例（取预测值前 30% 为"预测有"）
    thr = np.quantile(c_val, 0.70)
    cand_hi = c_val >= thr
    false_safe_cand = (
        float((cand_hi & ~has_slack[val.index]).mean() / cand_hi.mean())
        if cand_hi.mean() > 0
        else np.nan
    )
    thr_b = np.quantile(b_val, 0.70)
    base_hi = b_val >= thr_b
    false_safe_base = (
        float((base_hi & ~has_slack[val.index]).mean() / base_hi.mean())
        if base_hi.mean() > 0
        else np.nan
    )

    d_auc = auc_cand - auc_base
    d_sp = sp_cand - sp_base

    gate = cfg["r2_c2a"]["gate"]
    stop_max = float(gate["stop_max"])
    go_min = float(gate["go_min"])
    false_safe_improved = (
        (not np.isnan(false_safe_cand) and not np.isnan(false_safe_base))
        and false_safe_cand <= false_safe_base
    )
    if d_auc <= stop_max:
        verdict = "STOP"
    elif d_auc >= go_min and (
        not gate.get("require_false_safe_improve", True) or false_safe_improved
    ):
        verdict = "GO"
    else:
        verdict = "CONDITIONAL"

    stats: dict[str, object] = {
        "n_caltech_matched": int(sess.shape[0]),
        "n_train": int((sess["split"] == "train").sum()),
        "n_validation": int((sess["split"] == "validation").sum()),
        "t_slack_median_h": float(sess["t_slack_h"].median()),
        "has_slack_rate": float(has_slack.mean()),
        "auc_baseline": auc_base,
        "auc_candidate": auc_cand,
        "delta_auc": d_auc,
        "spearman_baseline": sp_base,
        "spearman_candidate": sp_cand,
        "delta_spearman": d_sp,
        "false_safe_baseline": false_safe_base,
        "false_safe_candidate": false_safe_cand,
        "verdict": verdict,
    }

    out_root = _PATENT_ROOT / str(cfg["outputs"]["results_root"])
    out_root.mkdir(parents=True, exist_ok=True)
    sess.to_csv(out_root / "r2_c2a_slack_dataset.csv", index=False)
    pd.Series(stats).to_csv(out_root / "r2_c2a_gate_stats.csv", header=["value"])

    _write_report(cfg, stats)
    return stats


def _f(stats: dict[str, object], key: str, digits: int) -> str:
    v = stats.get(key)
    return f"{v:.{digits}f}" if isinstance(v, float) and not np.isnan(v) else str(v)


def _write_report(cfg: dict[str, Any], stats: dict[str, object]) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    L: list[str] = []
    L.append("# CORE_SEARCH_R2_C2A_GATE：在线恢复风险可预测性门\n")
    L.append(f"> 生成时间（UTC）：{ts}")
    L.append("> 配置：configs/core_search_r2c2.yaml（rule_version=core_search_r2c2，冻结）\n")

    L.append("## 1. 目的\n")
    L.append(
        "> 在线安全信息能否比 reported_service_slack 明显更好识别"
        "真实 post-charge temporal slack？\n"
    )

    L.append("## 2. 数据与标签\n")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append(f"| caltech matched 会话数 | {stats.get('n_caltech_matched')} |")
    L.append(f"| train / validation | {stats.get('n_train')} / {stats.get('n_validation')} |")
    L.append(f"| T_slack 中位（小时） | {_f(stats, 't_slack_median_h', 2)} |")
    L.append(f"| has_slack(>=15min) 占比 | {_f(stats, 'has_slack_rate', 3)} |\n")

    L.append("## 3. 可预测性（validation）\n")
    L.append("| 指标 | baseline(reported_slack) | candidate(OLS) | Δ |")
    L.append("|---|---|---|---|")
    L.append(
        f"| AUC(has_slack) | {_f(stats, 'auc_baseline', 3)} | {_f(stats, 'auc_candidate', 3)} "
        f"| {_f(stats, 'delta_auc', 3)} |"
    )
    L.append(
        f"| Spearman(T_slack) | {_f(stats, 'spearman_baseline', 3)} | "
        f"{_f(stats, 'spearman_candidate', 3)} | {_f(stats, 'delta_spearman', 3)} |"
    )
    L.append(
        f"| false-safe rate | {_f(stats, 'false_safe_baseline', 3)} | "
        f"{_f(stats, 'false_safe_candidate', 3)} | — |\n"
    )

    L.append("## 4. 门判定\n")
    v = stats.get("verdict")
    marker = {"STOP": "**STOP**", "CONDITIONAL": "**CONDITIONAL**", "GO": "**GO**"}.get(
        str(v), str(v)
    )
    L.append(f"### 判定：{marker}\n")
    if str(v) == "GO":
        L.append("- 在线特征明显优于 reported baseline → 进入 R2-C2b 六臂 allocation replay。\n")
    elif str(v) == "STOP":
        L.append("- 在线特征几乎无增量 → R2-C 作为核心专利方向中止。\n")
    else:
        L.append("- 增量处于灰区 → 仅诊断，不进入 allocation。\n")

    L.append("## 5. 术语纪律\n")
    L.append("- T_slack 仅作离线标签；不用人工补能折扣函数。")
    L.append("- false-safe = 预测有恢复余量实际无余量的比例。\n")

    report_path = _PATENT_ROOT / str(cfg["outputs"]["report_a"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
