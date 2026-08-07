"""集中化的外部数据路径解析（V2.1 §10.1：路径不散落在算法代码）。"""

from __future__ import annotations

from pathlib import Path

from patent_preexperiment.config.yamlutil import expand_vars, load_yaml

DEFAULT_PATHS = Path(__file__).resolve().parents[4] / "configs" / "paths.yaml"
# __file__ = src/patent_preexperiment/io/paths.py
# parents[0]=io, [1]=patent_preexperiment, [2]=src, [3]=patent_preexperiment(实现区), [4]=仓库根
# 但仓库根的 configs 不在实现区内；改为从实现区 configs 读。
DEFAULT_PATHS = Path(__file__).resolve().parents[3] / "configs" / "paths.yaml"


def load_paths(path: str | Path | None = None) -> dict[str, str]:
    path = Path(path or DEFAULT_PATHS)
    if not path.exists():
        raise FileNotFoundError(
            f"缺少本地路径配置 {path}。请复制 configs/paths.example.yaml 为 "
            f"configs/paths.yaml 并填入本机数据路径（ACN 数据在仓库外，路径含中文/空格）。"
        )
    cfg = load_yaml(path)
    return expand_vars(cfg)


_paths_cache: dict[str, str] | None = None


def get_paths() -> dict[str, str]:
    global _paths_cache
    if _paths_cache is None:
        _paths_cache = load_paths()
    return _paths_cache


def acn_project_dir() -> Path:
    return Path(get_paths()["acn_project"])


def static_root_dir() -> Path:
    return Path(get_paths()["static_root"])


def resolve_static(rel_path: str) -> Path:
    """static_file_index.csv 中相对路径（如 caltech\\xxx\\file.csv.gz）→ 绝对路径。"""
    return static_root_dir() / rel_path


def output_root_dir() -> Path:
    return Path(get_paths()["output_root"])
