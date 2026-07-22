"""Exact API-call fan-out: the pipeline issues only the requests it needs (no over-fetching)."""

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
    DistributionPlan,
    Filters,
    QueryPlan,
    Series,
)

_STUDIES = "https://clinicaltrials.gov/api/v2/studies"


def _page(nct: str, phase: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "totalCount": 1,
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {"nctId": nct},
                        "designModule": {"phases": [phase]},
                    }
                }
            ],
        },
    )


def _call_count(plan: QueryPlan, responses: list[httpx.Response]) -> int:
    app.dependency_overrides[get_pipeline] = lambda: Pipeline(FakePlanner(plan), CtgovClient())
    try:
        with respx.mock:
            route = respx.get(_STUDIES).mock(side_effect=responses)
            TestClient(app).post("/visualize", json={"query": "q"})
            return route.call_count
    finally:
        app.dependency_overrides.clear()


def test_distribution_makes_exactly_count_then_search() -> None:
    plan = DistributionPlan(
        intent="distribution", dimension=CategoricalDim.phase, filters=Filters(condition="melanoma")
    )
    assert _call_count(plan, [_page("N1", "PHASE1"), _page("N1", "PHASE1")]) == 2


def test_comparison_makes_two_fetches_per_series() -> None:
    plan = ComparisonPlan(
        intent="comparison",
        dimension=CategoricalDim.phase,
        series=[
            Series(label="A", filters=Filters(intervention="A")),
            Series(label="B", filters=Filters(intervention="B")),
        ],
    )
    pages = [
        _page("A1", "PHASE2"),
        _page("A1", "PHASE2"),
        _page("B1", "PHASE2"),
        _page("B1", "PHASE2"),
    ]
    assert _call_count(plan, pages) == 4  # (count + search) per series, two series
