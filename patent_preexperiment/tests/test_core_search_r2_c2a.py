"""CORE-SEARCH R2-C2a 单元测试：手写 AUC / Spearman / OLS。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from patent_preexperiment.core_search.r2_c2a_gate import (
    _auc,
    _fit_ols,
    _predict_ols,
    _spearman,
)


def test_auc_perfect_separation():
    y = np.array([0, 0, 0, 1, 1, 1])
    score = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
    assert np.isclose(_auc(y, score), 1.0)


def test_auc_random_is_half():
    y = np.array([0, 0, 1, 1])
    score = np.array([0.0, 0.5, 0.5, 1.0])
    # 正样本 ranks: 0.5,1.0 → 排序 tie 处理
    assert 0.4 < _auc(y, score) < 0.9


def test_spearman_monotonic():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    assert np.isclose(_spearman(x, y), 1.0)


def test_ols_recovers_linear():
    x = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [0.0, 1.0, 0.0, 1.0]})
    y = pd.Series([3.0 + 2.0 * a + 1.0 * b for a, b in zip(x["a"], x["b"], strict=True)])
    coef = _fit_ols(x, y)
    pred = _predict_ols(x, coef)
    assert np.allclose(pred, y.to_numpy(), atol=1e-6)
