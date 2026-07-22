"""End-to-end money path: POST /visualize → bar chart, with a DI'd fake planner + mocked API.

This is the architecture proof: a fixed plan and fixture records produce an exact, deterministic
visualization spec — no LLM, no network.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from ctgov_agent.api.app import app, get_pipeline
from ctgov_agent.ctgov.client import CtgovClient
from ctgov_agent.engine.pipeline import Pipeline
from ctgov_agent.planner.base import FakePlanner
from ctgov_agent.planner.ir import CategoricalDim, DistributionPlan, Filters
from ctgov_agent.vocab.controlled import Phase

_FIXTURE: dict[str, Any] = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "ctgov_search_melanoma.json").read_text()
)


@pytest.fixture
def client_with_fake_plan() -> Iterator[TestClient]:
    plan = DistributionPlan(
        intent="distribution",
        dimension=CategoricalDim.phase,
        filters=Filters(condition="melanoma"),
    )
    ctgov = CtgovClient()
    app.dependency_overrides[get_pipeline] = lambda: Pipeline(FakePlanner(plan), ctgov)
    try:
        with respx.mock:
            respx.get("https://clinicaltrials.gov/api/v2/studies").mock(
                return_value=httpx.Response(200, json=_FIXTURE)
            )
            yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_distribution_by_phase_returns_bar_chart(client_with_fake_plan: TestClient) -> None:
    resp = client_with_fake_plan.post(
        "/visualize", json={"query": "How are melanoma trials distributed across phases?"}
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "ok"
    viz = body["visualization"]
    assert viz["kind"] == "chart"
    assert viz["type"] == "bar_chart"
    assert viz["encoding"]["x"]["field"] == "key"
    assert viz["encoding"]["y"]["field"] == "value"

    valid_phases = {p.value for p in Phase}
    assert viz["data"], "expected at least one phase bucket"
    for point in viz["data"]:
        assert point["key"] in valid_phases
        assert point["value"] >= 1

    # Deep citations flow through, and every excerpt is a real substring of its source record.
    source = {
        s["protocolSection"]["identificationModule"]["nctId"]: json.dumps(s)
        for s in _FIXTURE["studies"]
    }
    assert any(point["citations"] for point in viz["data"])
    for point in viz["data"]:
        for cite in point["citations"]:
            assert cite["excerpt"] in source[cite["nct_id"]]

    meta = body["meta"]
    assert meta["total_trials_matched"] == _FIXTURE["totalCount"]
    assert meta["trials_aggregated"] == len(_FIXTURE["studies"])
    assert meta["source"] == "clinicaltrials.gov"


def test_no_matching_trials_is_refused() -> None:
    plan = DistributionPlan(
        intent="distribution", dimension=CategoricalDim.phase, filters=Filters(condition="zzzznope")
    )
    ctgov = CtgovClient()
    app.dependency_overrides[get_pipeline] = lambda: Pipeline(FakePlanner(plan), ctgov)
    try:
        with respx.mock:
            respx.get("https://clinicaltrials.gov/api/v2/studies").mock(
                return_value=httpx.Response(200, json={"totalCount": 0, "studies": []})
            )
            resp = TestClient(app).post(
                "/visualize", json={"query": "trials for zzzznope by phase"}
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "refused"
    assert body["reason"] == "no_data"


def test_distribution_all_null_dimension_reports_honest_no_data() -> None:
    # Trials matched, but none carry a phase (e.g. a purely observational set). The refusal must
    # say so, not claim "no trials matched".
    plan = DistributionPlan(
        intent="distribution",
        dimension=CategoricalDim.phase,
        filters=Filters(condition="observational-only"),
    )
    studies = [
        {
            "protocolSection": {
                "identificationModule": {"nctId": f"NCT{i}", "briefTitle": "obs"},
                "statusModule": {"overallStatus": "RECRUITING"},
            }
        }
        for i in range(2)
    ]
    ctgov = CtgovClient()
    app.dependency_overrides[get_pipeline] = lambda: Pipeline(FakePlanner(plan), ctgov)
    try:
        with respx.mock:
            respx.get("https://clinicaltrials.gov/api/v2/studies").mock(
                return_value=httpx.Response(200, json={"totalCount": 2, "studies": studies})
            )
            resp = TestClient(app).post("/visualize", json={"query": "phase breakdown"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "refused"
    assert body["reason"] == "no_data"
    assert "Matched 2" in body["message"]
    assert "phase" in body["message"]
