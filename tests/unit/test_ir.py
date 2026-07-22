"""The IR must parse every intent it claims to support and reject everything off-target.

These negative cases are the point: they encode "the planner's output is structurally constrained",
which is how we keep a wrong plan from ever reaching the executor.
"""

import pytest
from pydantic import ValidationError

from ctgov_agent.planner.ir import (
    CategoricalDim,
    ComparisonPlan,
    DistributionPlan,
    EntityDim,
    GeographicPlan,
    NetworkPlan,
    TimeTrendPlan,
    parse_plan,
    query_plan_json_schema,
    query_plan_tool_schema,
)


def test_distribution_parses() -> None:
    plan = parse_plan(
        {"intent": "distribution", "dimension": "phase", "filters": {"condition": "melanoma"}}
    )
    assert isinstance(plan, DistributionPlan)
    assert plan.dimension is CategoricalDim.phase
    assert plan.filters.condition == "melanoma"


def test_time_trend_parses_with_year_filter() -> None:
    plan = parse_plan(
        {
            "intent": "time_trend",
            "filters": {"intervention": "Pembrolizumab", "start_year_min": 2015},
        }
    )
    assert isinstance(plan, TimeTrendPlan)
    assert plan.filters.start_year_min == 2015


def test_geographic_parses() -> None:
    plan = parse_plan(
        {"intent": "geographic", "filters": {"condition": "melanoma", "status": ["RECRUITING"]}}
    )
    assert isinstance(plan, GeographicPlan)


def test_comparison_parses_two_series() -> None:
    plan = parse_plan(
        {
            "intent": "comparison",
            "dimension": "phase",
            "series": [
                {"label": "Drug A", "filters": {"intervention": "A"}},
                {"label": "Drug B", "filters": {"intervention": "B"}},
            ],
        }
    )
    assert isinstance(plan, ComparisonPlan)
    assert len(plan.series) == 2


def test_network_parses_entity_pair() -> None:
    plan = parse_plan(
        {
            "intent": "network",
            "endpoints": ["sponsor", "intervention"],
            "filters": {"condition": "als"},
        }
    )
    assert isinstance(plan, NetworkPlan)
    assert plan.endpoints == (EntityDim.sponsor, EntityDim.intervention)


# --- rejection cases: illegal states must not be representable ---


def test_unknown_intent_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_plan({"intent": "mystery", "filters": {}})


def test_distribution_without_dimension_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_plan({"intent": "distribution", "filters": {}})


def test_comparison_with_one_series_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_plan(
            {
                "intent": "comparison",
                "dimension": "phase",
                "series": [{"label": "A", "filters": {"intervention": "A"}}],
            }
        )


def test_invalid_phase_value_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_plan(
            {"intent": "distribution", "dimension": "phase", "filters": {"phase": ["PHASE5"]}}
        )


def test_extra_field_rejected() -> None:
    # A smuggled field (e.g. an injection attempt) is refused, not silently ignored.
    with pytest.raises(ValidationError):
        parse_plan(
            {
                "intent": "distribution",
                "dimension": "phase",
                "filters": {},
                "sql": "DROP TABLE studies",
            }
        )


def test_cross_intent_field_rejected() -> None:
    # 'endpoints' belongs to network, not distribution — extra=forbid rejects the mismatch.
    with pytest.raises(ValidationError):
        parse_plan(
            {
                "intent": "distribution",
                "dimension": "phase",
                "endpoints": ["sponsor", "intervention"],
            }
        )


def test_inverted_year_range_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_plan(
            {"intent": "time_trend", "filters": {"start_year_min": 2020, "start_year_max": 2010}}
        )


def test_json_schema_is_discriminated() -> None:
    schema = query_plan_json_schema()
    # The union should surface as a discriminated oneOf/anyOf so the LLM sees the intent choice.
    assert "oneOf" in schema or "anyOf" in schema


def test_tool_schema_is_openai_compatible_object() -> None:
    # OpenAI function `parameters` must be a type:object schema (a bare union is rejected).
    schema = query_plan_tool_schema()
    assert schema["type"] == "object"
    assert "plan" in schema["properties"]
    assert "$defs" in schema  # hoisted so $refs resolve at the root
    assert "discriminator" not in schema  # OpenAI function-calling rejects this keyword
