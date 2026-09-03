"""Run CORE-SEARCH R4-C0 EVSE infrastructure event audit."""

from __future__ import annotations

from patent_preexperiment.core_search.r4c0_evse import run_r4_c0

if __name__ == "__main__":
    print(run_r4_c0()["gate"])
