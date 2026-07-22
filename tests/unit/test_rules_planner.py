"""The no-key fallback classifies intent by keywords and refuses what it can't handle."""

import pytest

from ctgov_agent.planner.base import PlannerError
from ctgov_agent.planner.ir import (
    CategoricalDim,
    DistributionPlan,
    EntityDim,
    Filters,
    GeographicPlan,
    NetworkPlan,
    TimeTrendPlan,
)
from ctgov_agent.planner.rules import RuleBasedPlanner


async def test_distribution_by_phase_is_default() -> None:
    plan = await RuleBasedPlanner().plan(
        "How are melanoma trials distributed across phases?", Filters(condition="melanoma")
    )
    assert isinstance(plan, DistributionPlan)
    assert plan.dimension is CategoricalDim.phase
    assert plan.filters.condition == "melanoma"


async def test_status_dimension_detected() -> None:
    plan = await RuleBasedPlanner().plan("distribution of trials by recruitment status", Filters())
    assert isinstance(plan, DistributionPlan)
    assert plan.dimension is CategoricalDim.status


async def test_time_trend_detected() -> None:
    plan = await RuleBasedPlanner().plan(
        "How has the number of trials changed per year?", Filters(intervention="Pembrolizumab")
    )
    assert isinstance(plan, TimeTrendPlan)
    assert plan.filters.intervention == "Pembrolizumab"


async def test_geographic_detected() -> None:
    plan = await RuleBasedPlanner().plan(
        "Which countries have the most recruiting trials?", Filters(condition="ALS")
    )
    assert isinstance(plan, GeographicPlan)


async def test_network_pair_detected() -> None:
    plan = await RuleBasedPlanner().plan(
        "Show a network of sponsors and drugs.", Filters(condition="melanoma")
    )
    assert isinstance(plan, NetworkPlan)
    assert plan.endpoints == (EntityDim.sponsor, EntityDim.intervention)


async def test_comparison_is_refused() -> None:
    with pytest.raises(PlannerError) as excinfo:
        await RuleBasedPlanner().plan("Compare Nivolumab vs Pembrolizumab", Filters())
    assert excinfo.value.reason == "unsupported"
