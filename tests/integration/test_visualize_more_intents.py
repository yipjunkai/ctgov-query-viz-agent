"""End-to-end coverage for the time-trend, geographic, and comparison intents."""

from typing import Any

import httpx
import respx
from fastapi.testclient import TestClient

from ctgov_agent.api.app import app, get_pipeline
from ctgov_agent.ctgov.client import CtgovClient
from ctgov_agent.engine.pipeline import Pipeline
from ctgov_agent.planner.base import FakePlanner
from ctgov_agent.planner.ir import (
    CategoricalDim,
    ComparisonPlan,
    Filters,
    GeographicPlan,
    QueryPlan,
    Series,
    TimeTrendPlan,
)
from ctgov_agent.vocab.controlled import Status

_STUDIES = "https://clinicaltrials.gov/api/v2/studies"


def _study(
    nct: str, *, year: int | None = None, country: str | None = None, phase: str | None = None
) -> dict[str, Any]:
    ps: dict[str, Any] = {"identificationModule": {"nctId": nct, "briefTitle": f"Study {nct}"}}
    if year is not None:
        ps["statusModule"] = {"startDateStruct": {"date": f"{year}-06-01"}}
    if phase is not None:
        ps["designModule"] = {"phases": [phase]}
    if country is not None:
        ps["contactsLocationsModule"] = {"locations": [{"country": country}]}
    return {"protocolSection": ps}


def _payload(studies: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {"totalCount": total if total is not None else len(studies), "studies": studies}


def _post(plan: QueryPlan, query: str, responses: list[httpx.Response]) -> dict[str, Any]:
    app.dependency_overrides[get_pipeline] = lambda: Pipeline(FakePlanner(plan), CtgovClient())
    try:
        with respx.mock:
            respx.get(_STUDIES).mock(side_effect=responses)
            resp = TestClient(app).post("/visualize", json={"query": query})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    return resp.json()


def test_time_trend_fills_zero_years() -> None:
    plan = TimeTrendPlan(intent="time_trend", filters=Filters(intervention="Pembrolizumab"))
    studies = [
        _study("N1", year=2015),
        _study("N2", year=2016),
        _study("N3", year=2016),
        _study("N4", year=2018),
    ]
    resp = httpx.Response(200, json=_payload(studies))
    body = _post(plan, "trend of Pembrolizumab trials per year", [resp, resp])  # count + search

    viz = body["visualization"]
    assert viz["type"] == "time_series"
    series = {d["key"]: d["value"] for d in viz["data"]}
    assert series == {"2015": 1, "2016": 2, "2017": 0, "2018": 1}  # 2017 zero-filled


def test_geographic_sorted_descending() -> None:
    plan = GeographicPlan(
        intent="geographic", filters=Filters(condition="melanoma", status=[Status.RECRUITING])
    )
    studies = [
        _study("N1", country="United States"),
        _study("N2", country="United States"),
        _study("N3", country="France"),
    ]
    resp = httpx.Response(200, json=_payload(studies))
    body = _post(plan, "which countries have recruiting melanoma trials", [resp, resp])

    viz = body["visualization"]
    assert viz["type"] == "choropleth"
    assert [d["key"] for d in viz["data"]] == ["United States", "France"]
    assert viz["data"][0]["value"] == 2


def test_comparison_produces_grouped_bar() -> None:
    plan = ComparisonPlan(
        intent="comparison",
        dimension=CategoricalDim.phase,
        series=[
            Series(label="Drug A", filters=Filters(intervention="DrugA")),
            Series(label="Drug B", filters=Filters(intervention="DrugB")),
        ],
    )
    a = [_study("A1", phase="PHASE2"), _study("A2", phase="PHASE3")]
    b = [_study("B1", phase="PHASE2")]
    # Per series the pipeline calls count() then search(): countA, searchA, countB, searchB.
    responses = [
        httpx.Response(200, json=_payload(a, total=2)),
        httpx.Response(200, json=_payload(a, total=2)),
        httpx.Response(200, json=_payload(b, total=1)),
        httpx.Response(200, json=_payload(b, total=1)),
    ]
    body = _post(plan, "compare Drug A vs Drug B by phase", responses)

    viz = body["visualization"]
    assert viz["type"] == "grouped_bar"
    assert {d["series"] for d in viz["data"]} == {"Drug A", "Drug B"}
    points = {(d["series"], d["key"]): d["value"] for d in viz["data"]}
    assert points[("Drug A", "PHASE2")] == 1
    assert points[("Drug A", "PHASE3")] == 1
    assert points[("Drug B", "PHASE2")] == 1


def test_comparison_flags_same_drug_series() -> None:
    # Keytruda and Pembrolizumab are the same drug; the comparison should notice.
    plan = ComparisonPlan(
        intent="comparison",
        dimension=CategoricalDim.phase,
        series=[
            Series(label="Keytruda", filters=Filters(intervention="Keytruda")),
            Series(label="Pembrolizumab", filters=Filters(intervention="Pembrolizumab")),
        ],
    )
    a = [_study("A1", phase="PHASE2"), _study("A2", phase="PHASE3")]
    b = [_study("B1", phase="PHASE2")]
    responses = [
        httpx.Response(200, json=_payload(a, total=2)),
        httpx.Response(200, json=_payload(a, total=2)),
        httpx.Response(200, json=_payload(b, total=1)),
        httpx.Response(200, json=_payload(b, total=1)),
    ]
    body = _post(plan, "compare Keytruda vs Pembrolizumab by phase", responses)

    meta = body["meta"]
    assert [e["canonical"] for e in meta["resolved_entities"]] == ["Pembrolizumab"]  # deduped
    assert any("same drug" in note for note in meta["advisories"])
