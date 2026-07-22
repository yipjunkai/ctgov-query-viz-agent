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


def test_distribution_meta_reconciles_dropped_trials() -> None:
    # Two trials have a phase, one has none: the bars sum to 2 but 3 matched. Meta must own that
    # gap (trials_unclassified + an assumption note) instead of leaving it silent.
    plan = DistributionPlan(
        intent="distribution",
        dimension=CategoricalDim.phase,
        filters=Filters(condition="melanoma"),
    )
    studies = [
        {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT1"},
                "designModule": {"phases": ["PHASE2"]},
            }
        },
        {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT2"},
                "designModule": {"phases": ["PHASE2"]},
            }
        },
        {"protocolSection": {"identificationModule": {"nctId": "NCT3"}}},  # no phase
    ]
    ctgov = CtgovClient()
    app.dependency_overrides[get_pipeline] = lambda: Pipeline(FakePlanner(plan), ctgov)
    try:
        with respx.mock:
            respx.get("https://clinicaltrials.gov/api/v2/studies").mock(
                return_value=httpx.Response(200, json={"totalCount": 3, "studies": studies})
            )
            resp = TestClient(app).post("/visualize", json={"query": "phase breakdown"})
    finally:
        app.dependency_overrides.clear()

    body = resp.json()
    assert body["status"] == "ok"
    assert sum(p["value"] for p in body["visualization"]["data"]) == 2
    meta = body["meta"]
    assert meta["trials_aggregated"] == 3
    assert meta["trials_unclassified"] == 1
    assert any("report no phase" in note for note in meta["assumptions"])


def test_too_broad_distribution_uses_facet_fast_path() -> None:
    # A distribution over more trials than the threshold is answered with one exact server-side
    # count per phase (no full paging), not refused.
    plan = DistributionPlan(
        intent="distribution", dimension=CategoricalDim.phase, filters=Filters(condition="cancer")
    )
    counts = {
        "NA": 400,
        "EARLY_PHASE1": 100,
        "PHASE1": 1000,
        "PHASE2": 1500,
        "PHASE3": 900,
        "PHASE4": 300,
    }  # bar sum 4200; classified (any phase) 4000 -> unclassified 1000; 4200 > 4000 -> multivalue

    def handler(request: httpx.Request) -> httpx.Response:
        adv = request.url.params.get("filter.advanced", "")
        occurrences = adv.count("AREA[Phase]")
        if occurrences == 0:
            return httpx.Response(200, json={"totalCount": 5000, "studies": []})  # matched total
        if occurrences > 1:
            return httpx.Response(200, json={"totalCount": 4000, "studies": []})  # classified total
        value = adv.replace("AREA[Phase]", "")
        sample = {
            "protocolSection": {
                "identificationModule": {"nctId": f"NCT-{value}", "briefTitle": "sample"},
                "designModule": {"phases": [value]},
            }
        }
        return httpx.Response(200, json={"totalCount": counts.get(value, 0), "studies": [sample]})

    ctgov = CtgovClient()
    app.dependency_overrides[get_pipeline] = lambda: Pipeline(
        FakePlanner(plan), ctgov, too_broad_threshold=100
    )
    try:
        with respx.mock:
            respx.get("https://clinicaltrials.gov/api/v2/studies").mock(side_effect=handler)
            resp = TestClient(app).post("/visualize", json={"query": "cancer trials by phase"})
    finally:
        app.dependency_overrides.clear()

    body = resp.json()
    assert body["status"] == "ok"
    data = {p["key"]: p["value"] for p in body["visualization"]["data"]}
    # Exact server-side totals, though each value returned only ONE sample record — proof the count
    # came from totalCount (fast path), not from counting fetched records.
    assert data["PHASE2"] == 1500
    assert sum(data.values()) == 4200
    meta = body["meta"]
    assert meta["total_trials_matched"] == 5000
    assert meta["trials_unclassified"] == 1000  # 5000 matched - 4000 classified
    assert any("too many to page" in note for note in meta["assumptions"])
    assert any("report no phase" in note for note in meta["assumptions"])
    # Deep citations survive: the excerpt is the exact phase value from a sample record.
    p2 = next(p for p in body["visualization"]["data"] if p["key"] == "PHASE2")
    assert p2["citations"] and p2["citations"][0]["excerpt"] == "PHASE2"
