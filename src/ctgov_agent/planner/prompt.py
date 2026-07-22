"""System prompt, tool definitions, and message construction for the LLM planner.

The model is given exactly two tools and told to call one: ``emit_query_plan`` (whose parameters are
the QueryPlan JSON Schema, so the allowed enum values are the API's own vocabulary) or
``cannot_answer`` (an explicit escape hatch so the model refuses instead of forcing a bad plan).
"""

import json
from typing import Any, cast

from ctgov_agent.planner.ir import Filters, query_plan_json_schema

EMIT_TOOL = "emit_query_plan"
CANNOT_ANSWER_TOOL = "cannot_answer"

_CANNOT_ANSWER_REASONS = ("out_of_domain", "ambiguous", "unsupported")

SYSTEM_PROMPT = """\
You translate a natural-language question about clinical trials into a structured query \
plan for the ClinicalTrials.gov API. You never compute or output counts or data — only the \
plan; the system fetches and counts real records from the plan.

Call `emit_query_plan` with the ONE intent that best fits the question:
- distribution: how trials split across a categorical dimension \
(phase, status, study_type, sponsor_class, intervention_type).
- time_trend: trial counts over time (per year).
- comparison: two or more named series compared across a dimension (e.g. Drug A vs Drug B).
- geographic: trial counts by country.
- network: co-occurrence between two entity types (sponsor, intervention, condition).

Put constraints in `filters` using ONLY enum values allowed by the schema; never invent \
values. Use `notes` to state your interpretation in one sentence.

If the question is not about clinical trials, or cannot be mapped to one of these intents, \
call `cannot_answer` instead of guessing.

Examples:
- "How are melanoma trials distributed across phases?" -> distribution, dimension=phase, \
filters.condition="melanoma".
- "How has the number of Pembrolizumab trials changed per year since 2015?" -> time_trend, \
filters.intervention="Pembrolizumab", filters.start_year_min=2015.
- "Which countries have the most recruiting trials for ALS?" -> geographic, \
filters.condition="ALS", filters.status=["RECRUITING"].
- "Show a network of sponsors and drugs for melanoma trials." -> network, \
endpoints=["sponsor","intervention"], filters.condition="melanoma".
- "Compare phases for Nivolumab vs Pembrolizumab." -> comparison, dimension=phase, series=[\
{"label":"Nivolumab","filters":{"intervention":"Nivolumab"}},\
{"label":"Pembrolizumab","filters":{"intervention":"Pembrolizumab"}}].
"""


def _describe_hints(hints: Filters) -> str:
    provided = hints.model_dump(mode="json", exclude_none=True)
    if not provided:
        return ""
    return (
        f"\n\nStructured fields the user supplied (treat as authoritative): {json.dumps(provided)}"
    )


def build_messages(query: str, hints: Filters) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Question: {query}{_describe_hints(hints)}"},
    ]


def build_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": EMIT_TOOL,
                "description": "Emit the structured query plan for the question.",
                "parameters": query_plan_json_schema(),
            },
        },
        {
            "type": "function",
            "function": {
                "name": CANNOT_ANSWER_TOOL,
                "description": "Decline when the question is out of domain or cannot be mapped.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "reason": {"type": "string", "enum": list(_CANNOT_ANSWER_REASONS)},
                        "explanation": {"type": "string"},
                    },
                    "required": ["reason", "explanation"],
                },
            },
        },
    ]


def parse_cannot_answer(arguments: str) -> tuple[str, str]:
    """Extract (reason, explanation) from a cannot_answer tool call, defaulting safely."""
    fallback = "The question could not be processed."
    try:
        raw: Any = json.loads(arguments)
    except json.JSONDecodeError:
        return "out_of_domain", fallback
    if not isinstance(raw, dict):
        return "out_of_domain", fallback
    data = cast("dict[str, Any]", raw)
    reason = data.get("reason")
    explanation = data.get("explanation")
    valid_reason = (
        reason if isinstance(reason, str) and reason in _CANNOT_ANSWER_REASONS else "out_of_domain"
    )
    valid_explanation = explanation if isinstance(explanation, str) and explanation else fallback
    return valid_reason, valid_explanation
