"""P2.1A frozen constants（v1.3 §3/§4/§5/§6；不可通过 CLI/config 覆盖）。

冻结协议：phase3_p2_1_preregistration_v1.3（blob 7f09148）。
所有常量在本模块顶层定义；formal pipeline 不得接受任何 override。
D3 trigger 参数（Q95/15min/5/0.95/3）复用 P2 SchemaConfig（冻结值与 v1.3 §3 一致），
通过 `load_schema` 读入，不在此重定义。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class P21AFrozen:
    """v1.3 全部冻结参数（dataclass frozen，运行期不可变）。"""

    # —— 协议身份 ——
    experiment_id: str = "P2_1A_v1_3"
    protocol_version: str = "phase3_p2_1_preregistration_v1.3"
    frozen_protocol_commit_sha: str = "293ca11cbcfdae7d82ca21e184e44426999ea349"
    frozen_protocol_blob_sha: str = "7f09148b09f10b3a2ef89264e2031e3a5eca28a6"
    sentinel_path: str = "results/raw/phase3_p2_1/p2_1a_sentinel.json"

    # —— D3 trigger 参数（v1.3 §3；与 P2 SchemaConfig 冻结值一致，此处仅作 assert 镜像）——
    # 不重定义：由 load_schema 读入 scfg.history_quantile/history_window_min/
    # history_min_samples/min_history_samples/recovery_ratio/recovery_sustained_cycles。
    # 此处冻结期望值，formal runner 启动时 assert scfg 与之一致（防 schema 被改）。
    expected_history_quantile: float = 0.95
    expected_history_window_min: int = 15
    expected_history_min_samples: int = 5
    expected_min_history_samples: int = 5
    expected_recovery_ratio: float = 0.95
    expected_recovery_sustained_cycles: int = 3

    # —— Eligible risk set（v1.3 §4.2）——
    risk_set_site: str = "jpl"
    risk_set_field_mode: str = "current_only"
    risk_set_split: str = "train"

    # —— Outcome Y（v1.3 §4.4）——
    y_window_w: int = 10  # post-recovery 窗口 cycle 数
    y_q_threshold: float = 0.9  # Y=1 if Q50(post-W actual) >= 0.9 × protective_bound(t)

    # —— B1 persistence（v1.3 §4.3）——
    b1_epsilon_frac: float = 0.05  # max−min <= 5% × median(actual_3cycle)
    b1_sustained_cycles: int = 3

    # —— B2 rolling（v1.3 §4.3）——
    b2_window_min: int = 15  # rolling median/max window（shift(1) 因果化）
    b2_sustained_cycles: int = 3

    # —— B0/B4 sustained（与 D3 trigger 一致）——
    b0_sustained_cycles: int = 3  # = recovery_sustained_cycles
    b4_lag_cycles: int = 1  # B4 = lag(1) 版本触发 B0 条件

    # —— RNG seeds（v1.3 §4.3/§4.4/§6.2/§6.3/§6.5）——
    b3_global_seed: str = "20260813_A"
    bootstrap_seed: str = "20260813_B"
    target_bank_seed: str = "20260813_C"
    sil_noise_seed: str = "20260813_D"
    scenario_sample_seed: int = 20260812
    b_core_bootstrap_seed: str = "20260813_E"

    # —— Cluster bootstrap（v1.3 §4.4）——
    bootstrap_method: str = "percentile"
    bootstrap_n: int = 2000
    bootstrap_ci_low_pct: float = 2.5
    bootstrap_ci_high_pct: float = 97.5

    # —— Coverage / latency non-inferiority（v1.3 §4.4）——
    coverage_ni_factor: float = 0.8  # coverage(B0) >= 0.8 × coverage(B1)
    latency_ni_add_cycles: int = 3  # latency(B0) <= latency(B1) + 3

    # —— 数据充分性（v1.3 §5；看 Y 之前机械判定）——
    suff_min_eligible_segments: int = 100
    suff_min_trigger_sessions: int = 30  # B0/B1/B2a/B2b/B3/B4 均需 >= 30

    # —— PASS/FAIL 穷尽逻辑（v1.3 §4.4 closure C1）——
    # PASS = CI_lower > 0；FAIL = CI_lower <= 0（二态穷尽，无未定义分支）


FROZEN = P21AFrozen()
"""全局冻结常量实例。formal pipeline 通过 `from ...frozen import FROZEN` 引用。"""


def assert_d3_trigger_params_match(scfg: object) -> None:
    """formal runner 启动时校验 P2 SchemaConfig 的 D3 trigger 参数与 v1.3 §3 期望一致。

    防 schema YAML 被改导致 trigger 参数漂移。任一不一致 → RuntimeError（fail-closed）。
    """
    expected = {
        "history_quantile": FROZEN.expected_history_quantile,
        "history_window_min": FROZEN.expected_history_window_min,
        "history_min_samples": FROZEN.expected_history_min_samples,
        "min_history_samples": FROZEN.expected_min_history_samples,
        "recovery_ratio": FROZEN.expected_recovery_ratio,
        "recovery_sustained_cycles": FROZEN.expected_recovery_sustained_cycles,
    }
    for name, want in expected.items():
        got = getattr(scfg, name, None)
        if got != want:
            raise RuntimeError(
                f"frozen D3 trigger param drift: scfg.{name}={got!r} != v1.3 expected {want!r}; "
                f"protocol blob {FROZEN.frozen_protocol_blob_sha} is immutable"
            )
