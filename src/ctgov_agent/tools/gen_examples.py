"""Generate the golden example runs in examples/.

Runs representative requests through the real pipeline with the deterministic rule-based planner (no
LLM key needed) against the live API, and writes each request + actual JSON response to
examples/*.json (the committed golden outputs). Responses pass through a local on-disk cache under
examples/_cache/ (gitignored, ~13 MB) so repeat local runs are fast; a fresh regeneration needs
network access to ClinicalTrials.gov.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from ctgov_agent.api.schemas import VisualizeRequest
from ctgov_agent.ctgov.client import CtgovClient, ResponseCache
from ctgov_agent.engine.pipeline import Pipeline
from ctgov_agent.planner.rules import RuleBasedPlanner

_OUT = Path("examples")

# (filename, request). All are handled by the no-key rule planner given the structured fields, so
# they reproduce without an API key. Comparison queries need the LLM planner — see the README.
_EXAMPLES: list[tuple[str, dict[str, Any]]] = [
    (
        "01-distribution-by-phase",
        {"query": "How are melanoma trials distributed across phases?", "condition": "melanoma"},
    ),
    (
        "02-distribution-by-status",
        {
            "query": "Break down pembrolizumab trials by recruitment status",
            "drug_name": "Pembrolizumab",
        },
    ),
    (
        "03-time-trend-per-year",
        {
            "query": "How has the number of pembrolizumab trials changed per year?",
            "drug_name": "Pembrolizumab",
            "start_year": 2015,
        },
    ),
    (
        "04-geographic-by-country",
        {"query": "Which countries have the most trials for melanoma?", "condition": "melanoma"},
    ),
    (
        "05-network-sponsor-drug",
        {
            "query": "Show a network of sponsors and drugs for melanoma trials",
            "condition": "melanoma",
        },
    ),
]


async def main() -> None:
    _OUT.mkdir(exist_ok=True)
    client = CtgovClient(cache=ResponseCache(_OUT / "_cache"))
    pipeline = Pipeline(RuleBasedPlanner(), client)
    try:
        for name, request in _EXAMPLES:
            response = await pipeline.run(VisualizeRequest(**request))
            payload = {"request": request, "response": response.model_dump(mode="json")}
            (_OUT / f"{name}.json").write_text(json.dumps(payload, indent=2) + "\n")
            print(f"wrote examples/{name}.json  (status={response.status})")
    finally:
        await pipeline.aclose()


if __name__ == "__main__":
    asyncio.run(main())
