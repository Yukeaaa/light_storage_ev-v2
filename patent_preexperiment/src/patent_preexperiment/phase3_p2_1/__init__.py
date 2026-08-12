"""P2.1A — D3 Falsification（phase3_p2_1）。

冻结协议：phase3_p2_1_preregistration_v1.3（blob 7f09148，commit 293ca11，FREEZE APPROVED）。
本模块只实现 v1.3；不改变 protocol。

Step-0 隔离：sufficiency/risk_set/b3_map/triggers/metrics.build_trigger_counts 不读 Y；
formal 才有权调 outcome.compute_y / metrics.build_trigger_table / bootstrap / gate。
"""

from __future__ import annotations

from patent_preexperiment.phase3_p2_1.frozen import FROZEN, P21AFrozen

__all__ = ["FROZEN", "P21AFrozen"]
