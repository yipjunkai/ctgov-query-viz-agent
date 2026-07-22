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


def test_out_of_range_year_is_rejected() -> None:
    # A nonsense year is a malformed request (422), not an uncaught 500 deeper in the pipeline.
    assert _client.post("/visualize", json={"query": "x", "start_year": 50000}).status_code == 422


def test_inverted_year_range_is_rejected() -> None:
    r = _client.post("/visualize", json={"query": "x", "start_year": 2020, "end_year": 2010})
    assert r.status_code == 422
