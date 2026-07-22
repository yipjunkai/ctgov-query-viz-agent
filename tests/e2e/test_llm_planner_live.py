"""Live LLM planner smoke — runs only when a key is configured (via `just e2e`).

Proves the real OpenRouter/OpenAI tool-calling path maps a question to the right intent. Skipped
automatically when no key is present, so the gate stays green for keyless reviewers.
"""

import pytest

from ctgov_agent.config import get_settings
from ctgov_agent.planner.factory import build_planner
from ctgov_agent.planner.ir import Filters

pytestmark = pytest.mark.e2e


async def test_live_llm_maps_distribution_intent() -> None:
    settings = get_settings()
    if not (settings.openrouter_api_key or settings.openai_api_key):
        pytest.skip("no LLM key configured (set OPENROUTER_API_KEY or OPENAI_API_KEY)")

    planner = build_planner(settings)
    plan = await planner.plan("How are melanoma trials distributed across phases?", Filters())
    assert plan.intent == "distribution"
