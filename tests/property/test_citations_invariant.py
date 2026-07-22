"""Anti-hallucination invariant: a citation excerpt is always a value its source record carries.

If this ever fails, the agent is attributing a value to a trial record that record doesn't contain —
exactly the hallucination the whole design exists to prevent.

Two oracles are used deliberately:

* The categorical/temporal excerpts are enum-like / date strings, so we assert the classic
  "substring of the serialized source record" property (matching the README's wording).
* The geographic and network excerpts are *free text* (country names, brief titles). A JSON-dump
  substring check would be escaping-fragile there (a title with a quote or non-ASCII character is
  escaped in the dump), so we assert the stronger, representation-independent invariant: the
  excerpt is *exactly one of the record's own field values*.
"""

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from ctgov_agent.ctgov.models import StudyRecord, parse_study
from ctgov_agent.engine.aggregate import (
    aggregate_by_country,
    aggregate_by_dimension,
    aggregate_by_year,
)
from ctgov_agent.engine.citations import bucket_citations, edge_citations
from ctgov_agent.engine.network import build_network
from ctgov_agent.planner.ir import CategoricalDim, EntityDim

_PHASES = ["NA", "EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"]
_STATUSES = ["RECRUITING", "COMPLETED", "TERMINATED", "WITHDRAWN"]
_COUNTRIES = ["United States", "France", "Japan", "Brazil", "Germany"]


@st.composite
def _study(draw: st.DrawFn) -> dict[str, Any]:
    phases = draw(st.lists(st.sampled_from(_PHASES), max_size=3, unique=True))
    status = draw(st.sampled_from(_STATUSES))
    year = draw(st.integers(min_value=2000, max_value=2025))
    month = draw(st.integers(min_value=1, max_value=12))
    countries = draw(st.lists(st.sampled_from(_COUNTRIES), max_size=3, unique=True))
    sponsor = draw(st.text(min_size=1, max_size=16))
    interventions = draw(st.lists(st.text(min_size=1, max_size=16), max_size=3))
    return {
        "protocolSection": {
            "identificationModule": {"briefTitle": draw(st.text(min_size=1, max_size=24))},
            "designModule": {"phases": phases},
            "statusModule": {
                "overallStatus": status,
                "startDateStruct": {"date": f"{year}-{month:02d}-15"},
            },
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor}},
            "armsInterventionsModule": {
                "interventions": [{"name": name, "type": "DRUG"} for name in interventions]
            },
            "contactsLocationsModule": {"locations": [{"country": c} for c in countries]},
        }
    }


def _with_unique_ncts(studies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for i, study in enumerate(studies):
        study["protocolSection"]["identificationModule"]["nctId"] = f"NCT{i:08d}"
    return studies


def _field_values(record: StudyRecord, field: str | None) -> list[str]:
    """The record's own value(s) for the field a citation claims to quote."""
    by_field: dict[str, list[str]] = {
        "phase": list(record.phases),
        "status": [record.status] if record.status else [],
        "study_type": [record.study_type] if record.study_type else [],
        "start_date": [record.start_date] if record.start_date else [],
        "country": list(record.countries),
        "brief_title": [record.brief_title] if record.brief_title else [],
        "nct_id": [record.nct_id],
    }
    return by_field.get(field or "", [])


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


@given(st.lists(_study(), min_size=1, max_size=8))
def test_geographic_citation_excerpts_are_field_values(studies: list[dict[str, Any]]) -> None:
    records = [parse_study(s) for s in _with_unique_ncts(studies)]
    by_nct = {r.nct_id: r for r in records}
    for bucket in aggregate_by_country(records):
        for cite in bucket_citations(bucket, "country"):
            assert cite.excerpt in _field_values(by_nct[cite.nct_id], cite.field)


@given(st.lists(_study(), min_size=1, max_size=8))
def test_network_edge_citation_excerpts_are_field_values(studies: list[dict[str, Any]]) -> None:
    records = [parse_study(s) for s in _with_unique_ncts(studies)]
    by_nct = {r.nct_id: r for r in records}
    _nodes, edges = build_network(records, (EntityDim.sponsor, EntityDim.intervention))
    for edge in edges:
        for cite in edge_citations(edge):
            assert cite.excerpt in _field_values(by_nct[cite.nct_id], cite.field)
