"""Run CORE-SEARCH Decision #06 from completed R4-A0/R4-C0 data gates."""

from __future__ import annotations

from patent_preexperiment.core_search.r4_decision import run_decision_06

if __name__ == "__main__":
    print(run_decision_06()["decision"])
