"""Structured request fields deterministically override the plan — explicit input beats the LLM.

This encodes a core design claim: a user-supplied field never depends on the model's interpretation.
"""

from ctgov_agent.api.schemas import VisualizeRequest
from ctgov_agent.engine.pipeline import _hints_from_request, _merge_hints
from ctgov_agent.planner.ir import (
    CategoricalDim,
    ComparisonPlan,
    DistributionPlan,
    Filters,
    Series,
)


def _dist(filters: Filters) -> DistributionPlan:
    return DistributionPlan(intent="distribution", dimension=CategoricalDim.phase, filters=filters)


def test_structured_fields_override_plan_filters() -> None:
    merged = _merge_hints(
        _dist(Filters(condition="melanoma")),
        VisualizeRequest(
            query="q", condition="lung cancer", drug_name="Osimertinib", start_year=2018
        ),
    )
    assert isinstance(merged, DistributionPlan)
    assert merged.filters.condition == "lung cancer"  # overrides the plan's "melanoma"
    assert merged.filters.intervention == "Osimertinib"
    assert merged.filters.start_year_min == 2018


def test_original_plan_is_not_mutated() -> None:
    plan = _dist(Filters(condition="melanoma"))
    _merge_hints(plan, VisualizeRequest(query="q", condition="lung cancer"))
    assert plan.filters.condition == "melanoma"


def test_comparison_hints_merge_into_base_filters() -> None:
    plan = ComparisonPlan(
        intent="comparison",
        dimension=CategoricalDim.phase,
        series=[
            Series(label="A", filters=Filters(intervention="A")),
            Series(label="B", filters=Filters(intervention="B")),
        ],
    )
    merged = _merge_hints(plan, VisualizeRequest(query="q", condition="melanoma"))
    assert isinstance(merged, ComparisonPlan)
    assert merged.base_filters.condition == "melanoma"


def test_no_structured_fields_is_identity() -> None:
    merged = _merge_hints(_dist(Filters(condition="melanoma")), VisualizeRequest(query="q"))
    assert isinstance(merged, DistributionPlan)
    assert merged.filters.condition == "melanoma"


def test_hints_from_request_maps_fields() -> None:
    hints = _hints_from_request(
        VisualizeRequest(query="q", drug_name="Pembrolizumab", start_year=2015, end_year=2020)
    )
    assert hints.intervention == "Pembrolizumab"
    assert hints.start_year_min == 2015
    assert hints.start_year_max == 2020
