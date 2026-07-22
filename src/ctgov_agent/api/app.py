"""FastAPI application entrypoint.

Kept deliberately thin: the router translates HTTP ↔ domain objects and delegates all logic to the
pipeline. The pipeline is injected via :func:`get_pipeline` so tests can substitute a fake planner
and a mocked client.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse

from ctgov_agent.api.schemas import AgentResponse, VisualizeRequest
from ctgov_agent.config import get_settings
from ctgov_agent.ctgov.client import CtgovClient
from ctgov_agent.engine.pipeline import Pipeline
from ctgov_agent.planner.factory import build_planner

# Default pipeline, wired from configuration: LLM planner if a key is set, else the rule-based
# fallback. Tests override get_pipeline to inject a fake planner and mocked client.
_settings = get_settings()
_default_pipeline = Pipeline(
    build_planner(_settings),
    CtgovClient(),
    too_broad_threshold=_settings.too_broad_threshold,
)


def get_pipeline() -> Pipeline:
    return _default_pipeline


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await _default_pipeline.aclose()


app = FastAPI(
    title="ClinicalTrials.gov Query-to-Visualization Agent",
    version="0.1.0",
    lifespan=lifespan,
)


_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/", response_class=HTMLResponse)
def demo() -> HTMLResponse:
    """Serve the self-contained demo page (a pure consumer of the /visualize contract)."""
    return HTMLResponse((_WEB_DIR / "index.html").read_text())


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
