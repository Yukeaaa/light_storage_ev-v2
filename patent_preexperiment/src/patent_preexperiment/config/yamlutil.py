"""YAML 加载与 ${var} 模板展开。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import yaml

_PATTERN = re.compile(r"\$\{(\w+)\}")


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return dict(data or {})


def expand_vars(cfg: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """递归展开 `${key}` 引用（同层/上层键），未展开项保持原样。"""

    def _walk(node: Any, scope: dict[str, Any]) -> Any:
        if isinstance(node, dict):
            local = dict(scope)
            for k, v in node.items():
                local[k] = _walk(v, local)
            return {k: _walk(v, local) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(x, scope) for x in node]
        if isinstance(node, str):
            return _PATTERN.sub(lambda m: str(scope.get(m.group(1), m.group(0))), node)
        return node

    return cast(dict[str, Any], _walk(cfg, {}))
