"""FastAPI application entrypoint.

Kept deliberately thin: the router translates HTTP ↔ domain objects and delegates all logic to the
pipeline. The pipeline is injected via :func:`get_pipeline` so tests can substitute a fake planner
and a mocked client.
"""

from typing import Annotated

from fastapi import Depends, FastAPI

from ctgov_agent.api.schemas import AgentResponse, VisualizeRequest
from ctgov_agent.ctgov.client import CtgovClient
from ctgov_agent.engine.pipeline import Pipeline
from ctgov_agent.planner.base import UnconfiguredPlanner

app = FastAPI(
    title="ClinicalTrials.gov Query-to-Visualization Agent",
    version="0.1.0",
)

# Default pipeline. The real LLM planner + rule-based fallback replace UnconfiguredPlanner in the
# next slice; until then /visualize returns a clean `refused` rather than erroring.
_default_pipeline = Pipeline(UnconfiguredPlanner(), CtgovClient())


def get_pipeline() -> Pipeline:
    return _default_pipeline


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the reviewer, tests, and any deploy target."""
    return {"status": "ok"}


@app.post("/visualize")
async def visualize(
    request: VisualizeRequest,
    pipeline: Annotated[Pipeline, Depends(get_pipeline)],
) -> AgentResponse:
    """Turn a natural-language clinical-trials question into a visualization specification."""
    return await pipeline.run(request)
