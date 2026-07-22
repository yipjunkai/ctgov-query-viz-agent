"""The demo page is served at / and is a pure consumer of the /visualize contract."""

from fastapi.testclient import TestClient

from ctgov_agent.api.app import app


def test_demo_page_is_served() -> None:
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Query-to-Visualization Agent" in resp.text
    assert "/visualize" in resp.text  # the page calls the API
