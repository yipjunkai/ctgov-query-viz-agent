"""The request schema is a documented contract — malformed input is rejected with 422."""

from fastapi.testclient import TestClient

from ctgov_agent.api.app import app

_client = TestClient(app)


def test_empty_query_is_rejected() -> None:
    assert _client.post("/visualize", json={"query": ""}).status_code == 422


def test_missing_query_is_rejected() -> None:
    assert _client.post("/visualize", json={}).status_code == 422


def test_unknown_field_is_rejected() -> None:
    # extra="forbid": a smuggled field is refused, not silently ignored.
    assert _client.post("/visualize", json={"query": "x", "bogus": 1}).status_code == 422


def test_invalid_phase_enum_is_rejected() -> None:
    assert _client.post("/visualize", json={"query": "x", "phase": ["PHASE9"]}).status_code == 422
