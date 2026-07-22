"""The LLM planner validates the model's output and retries once — the anti-hallucination boundary.

The model is faked (a scripted sequence of tool calls) so these are fast and deterministic; the real
adapter is exercised by the key-gated e2e test.
"""

import json
from typing import Any

import pytest

from ctgov_agent.planner.base import PlannerError
from ctgov_agent.planner.ir import DistributionPlan, Filters
from ctgov_agent.planner.llm import LLMPlanner, ToolInvocation
from ctgov_agent.planner.prompt import CANNOT_ANSWER_TOOL, EMIT_TOOL


class FakeChatModel:
    """Returns a scripted ToolInvocation per call; records how many calls it received."""

    def __init__(self, invocations: list[ToolInvocation]) -> None:
        self._invocations = invocations
        self.calls = 0

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ToolInvocation:
        invocation = self._invocations[self.calls]
        self.calls += 1
        return invocation


def _emit(payload: dict[str, Any]) -> ToolInvocation:
    # The real emit tool wraps the plan under a "plan" key (see query_plan_tool_schema).
    return ToolInvocation(name=EMIT_TOOL, arguments=json.dumps({"plan": payload}))


_VALID = {"intent": "distribution", "dimension": "phase", "filters": {"condition": "melanoma"}}


async def test_valid_plan_on_first_try() -> None:
    model = FakeChatModel([_emit(_VALID)])
    plan = await LLMPlanner(model).plan("distribution of melanoma trials by phase", Filters())
    assert isinstance(plan, DistributionPlan)
    assert model.calls == 1


async def test_retries_once_then_succeeds() -> None:
    model = FakeChatModel([ToolInvocation(EMIT_TOOL, "{ not valid json"), _emit(_VALID)])
    plan = await LLMPlanner(model).plan("q", Filters())
    assert isinstance(plan, DistributionPlan)
    assert model.calls == 2  # retried with the validation error fed back


async def test_schema_violation_is_retried() -> None:
    bad = _emit(
        {"intent": "distribution", "filters": {"phase": ["PHASE9"]}}
    )  # invalid enum + no dim
    model = FakeChatModel([bad, _emit(_VALID)])
    plan = await LLMPlanner(model).plan("q", Filters())
    assert isinstance(plan, DistributionPlan)
    assert model.calls == 2


async def test_cannot_answer_raises_with_reason() -> None:
    decline = ToolInvocation(
        CANNOT_ANSWER_TOOL, json.dumps({"reason": "out_of_domain", "explanation": "not trials"})
    )
    with pytest.raises(PlannerError) as excinfo:
        await LLMPlanner(FakeChatModel([decline])).plan("what's the weather?", Filters())
    assert excinfo.value.reason == "out_of_domain"


async def test_gives_up_after_retries_exhausted() -> None:
    model = FakeChatModel(
        [ToolInvocation(EMIT_TOOL, "{bad"), ToolInvocation(EMIT_TOOL, "{still bad")]
    )
    with pytest.raises(PlannerError) as excinfo:
        await LLMPlanner(model, max_retries=1).plan("q", Filters())
    assert excinfo.value.reason == "planner_failed"
    assert model.calls == 2
