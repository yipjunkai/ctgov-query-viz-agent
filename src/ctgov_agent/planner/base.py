"""The planner seam: an interface the pipeline depends on, plus test/placeholder implementations.

Keeping the pipeline behind a :class:`Planner` Protocol lets us swap the real LLM planner for a
deterministic fake in tests (asserting an exact plan → spec) and a rule-based fallback when no API
key is configured.
"""

from typing import Protocol

from ctgov_agent.planner.ir import Filters, QueryPlan


class PlannerError(Exception):
    """Raised when a query cannot be turned into a valid plan (out-of-domain, unconfigured, etc.).

    ``reason`` is a stable machine code echoed into a RefusedResponse.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class Planner(Protocol):
    async def plan(self, query: str, hints: Filters) -> QueryPlan: ...


class FakePlanner:
    """Test double: returns a preset plan regardless of input (DI'd in integration tests)."""

    def __init__(self, plan: QueryPlan) -> None:
        self._plan = plan

    async def plan(self, query: str, hints: Filters) -> QueryPlan:
        return self._plan


class UnconfiguredPlanner:
    """Default until the LLM planner + rule fallback are wired — refuses cleanly rather than 500."""

    async def plan(self, query: str, hints: Filters) -> QueryPlan:
        raise PlannerError(
            "planner_unavailable",
            "No planner configured. Set OPENROUTER_API_KEY or OPENAI_API_KEY.",
        )
