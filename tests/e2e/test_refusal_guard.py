"""Live guard: the planner refuses out-of-capability questions instead of forcing a plan.

These are *in-domain* questions the count-only IR cannot express (efficacy, enrollment size,
eligibility). The whole anti-hallucination thesis says the planner must call ``cannot_answer`` here
rather than force-fit a confident, cited answer to a question it can't answer. This locks in the
behaviour measured in ``docs/EVAL.md`` (force-fit 0% on the unsupported set).

Runs only with an LLM key, via ``just e2e``; skipped cleanly otherwise (the no-key rule planner does
no free-text extraction, so it isn't the target here).
"""

import pytest

from ctgov_agent.config import get_settings
from ctgov_agent.planner.base import PlannerError
from ctgov_agent.planner.factory import build_planner
from ctgov_agent.planner.ir import Filters

pytestmark = pytest.mark.e2e

# Each is about clinical trials but outside the five supported intents — must be refused.
UNSUPPORTED = [
    "Did Keytruda improve outcomes in melanoma?",  # results / efficacy
    "What's the average enrollment size for NSCLC phase 3 trials?",  # enrollment
    "What are the inclusion criteria for ALS trials?",  # eligibility
]


@pytest.mark.parametrize("question", UNSUPPORTED)
async def test_planner_refuses_out_of_capability(question: str) -> None:
    settings = get_settings()
    if not (settings.openrouter_api_key or settings.openai_api_key):
        pytest.skip("no LLM key configured (set OPENROUTER_API_KEY or OPENAI_API_KEY)")

    planner = build_planner(settings)
    try:
        with pytest.raises(PlannerError):
            await planner.plan(question, Filters())
    finally:
        close = getattr(planner, "aclose", None)
        if close is not None:
            await close()
