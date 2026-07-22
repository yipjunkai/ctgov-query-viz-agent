"""Deterministic, no-key fallback planner.

Not a replacement for the LLM — a floor. It classifies intent by keywords and takes filters from the
*structured* request fields (it does no free-text entity extraction), so a reviewer without an API
key can still exercise the full pipeline by supplying `condition`/`drug_name`/etc. Anything it can't
handle (notably multi-series comparisons) it refuses rather than guesses.
"""

from ctgov_agent.planner.base import PlannerError
from ctgov_agent.planner.ir import (
    CategoricalDim,
    DistributionPlan,
    EntityDim,
    Filters,
    GeographicPlan,
    NetworkPlan,
    QueryPlan,
    TimeTrendPlan,
)

_COMPARE_WORDS = (" vs ", " versus ", "compare", "comparison")
_NETWORK_WORDS = ("network", "co-occur", "co occur", "relationship", "graph of")
_TIME_WORDS = ("over time", "per year", "each year", "by year", "since", "trend", "changed")
_GEO_WORDS = ("country", "countries", "geographic", "geography", " where ")

_NOTE = "Planned by the deterministic rule-based fallback (no LLM key configured)."


def _detect_intent(q: str) -> str:
    if any(w in q for w in _COMPARE_WORDS):
        return "comparison"
    if any(w in q for w in _NETWORK_WORDS):
        return "network"
    if any(w in q for w in _TIME_WORDS):
        return "time_trend"
    if any(w in q for w in _GEO_WORDS):
        return "geographic"
    return "distribution"


def _detect_dimension(q: str) -> CategoricalDim:
    if "status" in q or "recruit" in q:
        return CategoricalDim.status
    if "sponsor" in q:
        return CategoricalDim.sponsor_class
    if "intervention type" in q or "type of intervention" in q:
        return CategoricalDim.intervention_type
    return CategoricalDim.phase


def _detect_pair(q: str) -> tuple[EntityDim, EntityDim]:
    if "combination" in q or ("drug" in q and "sponsor" not in q):
        return (EntityDim.intervention, EntityDim.intervention)
    if "condition" in q or "disease" in q:
        return (EntityDim.condition, EntityDim.intervention)
    return (EntityDim.sponsor, EntityDim.intervention)


class RuleBasedPlanner:
    async def plan(self, query: str, hints: Filters) -> QueryPlan:
        q = query.lower()
        intent = _detect_intent(q)
        if intent == "comparison":
            raise PlannerError(
                "unsupported",
                "Comparison queries need the LLM planner or explicit series; the no-key fallback "
                "can't split them. Configure OPENROUTER_API_KEY or OPENAI_API_KEY.",
            )
        if intent == "time_trend":
            return TimeTrendPlan(intent="time_trend", filters=hints, notes=_NOTE)
        if intent == "geographic":
            return GeographicPlan(intent="geographic", filters=hints, notes=_NOTE)
        if intent == "network":
            return NetworkPlan(
                intent="network", endpoints=_detect_pair(q), filters=hints, notes=_NOTE
            )
        return DistributionPlan(
            intent="distribution", dimension=_detect_dimension(q), filters=hints, notes=_NOTE
        )
