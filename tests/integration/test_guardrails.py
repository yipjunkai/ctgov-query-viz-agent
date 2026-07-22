"""Refusal paths: the agent declines rather than returning a wrong or fabricated answer."""

from collections.abc import Callable

import httpx
import respx
from fastapi.testclient import TestClient

from ctgov_agent.api.app import app, get_pipeline
from ctgov_agent.ctgov.client import CtgovClient
from ctgov_agent.engine.pipeline import Pipeline
from ctgov_agent.planner.base import FakePlanner, PlannerError
from ctgov_agent.planner.ir import (
    CategoricalDim,
    DistributionPlan,
    Filters,
    QueryPlan,
    TimeTrendPlan,
)

_STUDIES = "https://clinicaltrials.gov/api/v2/studies"


class _RaisingPlanner:
    """A planner that always refuses with a given reason (stands in for the LLM's cannot_answer)."""

    def __init__(self, reason: str, message: str) -> None:
        self._reason = reason
        self._message = message

    async def plan(self, query: str, hints: Filters) -> QueryPlan:
        raise PlannerError(self._reason, self._message)


def _override(build: Callable[[], Pipeline]) -> None:
    app.dependency_overrides[get_pipeline] = build


def test_out_of_domain_query_is_refused() -> None:
    _override(
        lambda: Pipeline(
            _RaisingPlanner("out_of_domain", "Not about clinical trials."), CtgovClient()
        )
    )
    try:
        resp = TestClient(app).post("/visualize", json={"query": "what's the weather in Seoul?"})
    finally:
        app.dependency_overrides.clear()
    body = resp.json()
    assert body["status"] == "refused"
    assert body["reason"] == "out_of_domain"


def test_ambiguous_query_asks_for_clarification() -> None:
    _override(
        lambda: Pipeline(_RaisingPlanner("ambiguous", "Which drug did you mean?"), CtgovClient())
    )
    try:
        resp = TestClient(app).post("/visualize", json={"query": "trials for it"})
    finally:
        app.dependency_overrides.clear()
    body = resp.json()
    assert body["status"] == "needs_clarification"
    assert "which drug" in body["question"].lower()


def test_too_broad_query_is_refused_without_fetching() -> None:
    # A time trend genuinely needs every record, so it still refuses when the set is too large —
    # counted once, never paged. (Distributions instead take the facet fast path; see
    # test_visualize_distribution.py::test_too_broad_distribution_uses_facet_fast_path.)
    plan = TimeTrendPlan(intent="time_trend", filters=Filters())
    _override(lambda: Pipeline(FakePlanner(plan), CtgovClient(), too_broad_threshold=10))
    try:
        with respx.mock:
            route = respx.get(_STUDIES).mock(
                return_value=httpx.Response(200, json={"totalCount": 99999, "studies": []})
            )
            resp = TestClient(app).post("/visualize", json={"query": "all trials per year"})
    finally:
        app.dependency_overrides.clear()
    body = resp.json()
    assert body["status"] == "refused"
    assert body["reason"] == "too_broad"
    assert body["detail"]["total"] == 99999
    assert route.call_count == 1  # counted once, never paged the huge result set


def test_upstream_error_is_refused() -> None:
    plan = DistributionPlan(
        intent="distribution", dimension=CategoricalDim.phase, filters=Filters(condition="x")
    )
    _override(lambda: Pipeline(FakePlanner(plan), CtgovClient()))
    try:
        with respx.mock:
            respx.get(_STUDIES).mock(return_value=httpx.Response(500))
            resp = TestClient(app).post("/visualize", json={"query": "melanoma trials by phase"})
    finally:
        app.dependency_overrides.clear()
    body = resp.json()
    assert body["status"] == "refused"
    assert body["reason"] == "upstream_error"
