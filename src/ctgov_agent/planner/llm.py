"""LLM planner: prompt a model, force a tool call, validate it, retry once on failure.

The model is confined to producing a plan (or an explicit refusal). Its raw arguments always run
through Pydantic ``parse_plan``. If they don't validate, the error is fed back for one more try; if
it still fails we refuse rather than ship a bad plan — nothing the model emits reaches the engine
unvalidated.
"""

import json
from dataclasses import dataclass
from typing import Any, Protocol, cast

from openai import AsyncOpenAI, omit
from pydantic import ValidationError

from ctgov_agent.planner.base import PlannerError
from ctgov_agent.planner.ir import Filters, QueryPlan, parse_plan
from ctgov_agent.planner.prompt import (
    CANNOT_ANSWER_TOOL,
    EMIT_TOOL,
    build_messages,
    build_tools,
    parse_cannot_answer,
)


@dataclass
class ToolInvocation:
    name: str
    arguments: str


def _unwrap_plan(payload: Any) -> Any:
    """The emit tool wraps the plan under a "plan" key; unwrap it (tolerate an unwrapped one)."""
    if isinstance(payload, dict) and "plan" in payload:
        return cast("dict[str, Any]", payload)["plan"]
    return cast("Any", payload)


class ChatModel(Protocol):
    """Domain-free chat interface: given messages + tools, return the chosen tool call."""

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ToolInvocation: ...


class OpenAIChatModel:
    """Thin adapter over any OpenAI-compatible endpoint (OpenRouter or OpenAI direct)."""

    def __init__(
        self, client: AsyncOpenAI, model: str, *, temperature: float | None = None
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ToolInvocation:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # pyright: ignore[reportArgumentType]  (SDK TypedDicts; runtime dicts are fine)
            tools=tools,  # pyright: ignore[reportArgumentType]
            tool_choice="required",
            temperature=self._temperature if self._temperature is not None else omit,
        )
        calls = resp.choices[0].message.tool_calls
        if not calls:
            raise PlannerError("planner_failed", "The model did not call a tool.")
        function = getattr(calls[0], "function", None)
        if function is None:
            raise PlannerError("planner_failed", "The model returned a non-function tool call.")
        name = str(getattr(function, "name", ""))
        arguments = str(getattr(function, "arguments", ""))
        return ToolInvocation(name=name, arguments=arguments)

    async def aclose(self) -> None:
        await self._client.close()


class LLMPlanner:
    def __init__(self, model: ChatModel, *, max_retries: int = 1) -> None:
        self._model = model
        self._max_retries = max_retries

    async def plan(self, query: str, hints: Filters) -> QueryPlan:
        messages = build_messages(query, hints)
        tools = build_tools()
        last_error = ""
        for _ in range(self._max_retries + 1):
            invocation = await self._model.complete(messages, tools)
            if invocation.name == CANNOT_ANSWER_TOOL:
                reason, explanation = parse_cannot_answer(invocation.arguments)
                raise PlannerError(reason, explanation)
            try:
                plan_data = _unwrap_plan(json.loads(invocation.arguments))
                return parse_plan(plan_data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = str(exc)
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your {EMIT_TOOL} arguments were invalid: {last_error}. "
                            f"Call {EMIT_TOOL} again with corrected arguments."
                        ),
                    }
                )
        raise PlannerError(
            "planner_failed", f"Could not produce a valid plan. Last error: {last_error}"
        )

    async def aclose(self) -> None:
        close = getattr(self._model, "aclose", None)
        if close is not None:
            await close()
