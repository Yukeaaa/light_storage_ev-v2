"""CORE-SEARCH modules must be importable without local external-data paths."""

from __future__ import annotations

import importlib
import sys

from patent_preexperiment.io import paths


def test_r2_c_modules_import_without_paths_yaml(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DEFAULT_PATHS", tmp_path / "missing_paths.yaml")
    monkeypatch.setattr(paths, "_paths_cache", None)
    for name in [
        "patent_preexperiment.core_search.r2_c_data_gate",
        "patent_preexperiment.core_search.r2_c1_gate",
        "patent_preexperiment.core_search.r2_c2a_gate",
    ]:
        sys.modules.pop(name, None)

    for name in [
        "patent_preexperiment.core_search.r2_c_data_gate",
        "patent_preexperiment.core_search.r2_c1_gate",
        "patent_preexperiment.core_search.r2_c2a_gate",
    ]:
        importlib.import_module(name)
