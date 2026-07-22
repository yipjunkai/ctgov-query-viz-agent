"""FastAPI application entrypoint.

Kept deliberately thin: routers translate HTTP ↔ domain objects and delegate all logic to the
pipeline/services. No business logic lives here.
"""

from fastapi import FastAPI

app = FastAPI(
    title="ClinicalTrials.gov Query-to-Visualization Agent",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the reviewer, tests, and any deploy target."""
    return {"status": "ok"}
