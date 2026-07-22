"""End-to-end network graph through POST /visualize."""

from typing import Any

import httpx
import respx
from fastapi.testclient import TestClient

from ctgov_agent.api.app import app, get_pipeline
from ctgov_agent.ctgov.client import CtgovClient
from ctgov_agent.engine.pipeline import Pipeline
from ctgov_agent.planner.base import FakePlanner
from ctgov_agent.planner.ir import EntityDim, Filters, NetworkPlan

_STUDIES = "https://clinicaltrials.gov/api/v2/studies"


def _study(nct: str, sponsor: str, interventions: list[str]) -> dict[str, Any]:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": f"Study {nct}"},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor, "class": "INDUSTRY"}},
            "armsInterventionsModule": {
                "interventions": [{"type": "DRUG", "name": name} for name in interventions]
            },
        }
    }


def test_network_endpoint_builds_weighted_graph() -> None:
    plan = NetworkPlan(
        intent="network",
        endpoints=(EntityDim.sponsor, EntityDim.intervention),
        filters=Filters(condition="melanoma"),
    )
    studies = [
        _study("N1", "Merck", ["Pembrolizumab"]),
        _study("N2", "Merck", ["Pembrolizumab"]),
        _study("N3", "BMS", ["Nivolumab"]),
    ]
    payload = {"totalCount": 3, "studies": studies}

    app.dependency_overrides[get_pipeline] = lambda: Pipeline(FakePlanner(plan), CtgovClient())
    try:
        with respx.mock:
            respx.get(_STUDIES).mock(return_value=httpx.Response(200, json=payload))
            resp = TestClient(app).post(
                "/visualize", json={"query": "network of sponsors and drugs for melanoma"}
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    viz = body["visualization"]
    assert viz["kind"] == "network"
    assert viz["type"] == "network_graph"

    edges = {(e["source"], e["target"]): e["weight"] for e in viz["edges"]}
    assert edges[("sponsor:Merck", "intervention:Pembrolizumab")] == 2
    node_ids = {n["id"] for n in viz["nodes"]}
    assert {"sponsor:Merck", "intervention:Pembrolizumab", "sponsor:BMS"} <= node_ids
