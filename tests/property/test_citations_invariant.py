"""Anti-hallucination invariant: a citation excerpt is always a substring of its source record.

If this ever fails, the agent is attributing a value to a trial record that record doesn't contain —
exactly the hallucination the whole design exists to prevent.
"""

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from ctgov_agent.ctgov.models import parse_study
from ctgov_agent.engine.aggregate import aggregate_by_dimension, aggregate_by_year
from ctgov_agent.engine.citations import bucket_citations
from ctgov_agent.planner.ir import CategoricalDim

_PHASES = ["NA", "EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"]
_STATUSES = ["RECRUITING", "COMPLETED", "TERMINATED", "WITHDRAWN"]


@st.composite
def _study(draw: st.DrawFn) -> dict[str, Any]:
    phases = draw(st.lists(st.sampled_from(_PHASES), max_size=3, unique=True))
    status = draw(st.sampled_from(_STATUSES))
    year = draw(st.integers(min_value=2000, max_value=2025))
    month = draw(st.integers(min_value=1, max_value=12))
    return {
        "protocolSection": {
            "identificationModule": {"briefTitle": draw(st.text(min_size=1, max_size=24))},
            "designModule": {"phases": phases},
            "statusModule": {
                "overallStatus": status,
                "startDateStruct": {"date": f"{year}-{month:02d}-15"},
            },
        }
    }


def _with_unique_ncts(studies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for i, study in enumerate(studies):
        study["protocolSection"]["identificationModule"]["nctId"] = f"NCT{i:08d}"
    return studies


@given(st.lists(_study(), min_size=1, max_size=8))
def test_categorical_citation_excerpts_are_in_source(studies: list[dict[str, Any]]) -> None:
    records = [parse_study(s) for s in _with_unique_ncts(studies)]
    source = {r.nct_id: json.dumps(r.raw) for r in records}
    for dim, field in [(CategoricalDim.phase, "phase"), (CategoricalDim.status, "status")]:
        for bucket in aggregate_by_dimension(records, dim):
            for cite in bucket_citations(bucket, field):
                assert cite.excerpt in source[cite.nct_id]


@given(st.lists(_study(), min_size=1, max_size=8))
def test_time_citation_excerpts_are_in_source(studies: list[dict[str, Any]]) -> None:
    records = [parse_study(s) for s in _with_unique_ncts(studies)]
    source = {r.nct_id: json.dumps(r.raw) for r in records}
    for bucket in aggregate_by_year(records):
        for cite in bucket_citations(bucket, "start_date", use_start_date=True):
            assert cite.excerpt in source[cite.nct_id]
