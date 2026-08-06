"""禁止特征强制校验（K0-03 / V2.1 §16.4 P0 级）。"""

from __future__ import annotations

from pathlib import Path

from patent_preexperiment.config.yamlutil import load_yaml

_FORBIDDEN_PATH = Path(__file__).resolve().parents[3] / "configs" / "forbidden_features.yaml"


class ForbiddenFeatureError(ValueError):
    """输入 schema 中出现了禁止的在线特征。"""


def load_forbidden_features(path: str | Path | None = None) -> list[str]:
    cfg = load_yaml(path or _FORBIDDEN_PATH)
    return list(cfg["forbidden_features"])


def assert_no_forbidden(columns: list[str], forbidden: list[str] | None = None) -> None:
    """对输入列名做阻断式校验；命中任何禁止特征立即抛错。"""
    forbidden = forbidden if forbidden is not None else load_forbidden_features()
    hit = sorted({c for c in columns if c in forbidden})
    if hit:
        raise ForbiddenFeatureError(f"禁止特征泄漏：{hit}")
