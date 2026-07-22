"""Orchestrates a single request: plan → execute → aggregate → visualize → response.

The LLM (via the planner) appears exactly once, at the top, and only produces a validated plan.
Everything after is deterministic. Structured request fields are merged over the plan *after*
planning, so explicit user input always wins over the model.
"""

from typing import Any

from ctgov_agent.api.schemas import (
    AgentResponse,
    Meta,
    OkResponse,
    RefusedResponse,
    VisualizeRequest,
)
from ctgov_agent.ctgov.client import DEFAULT_MAX_RECORDS, CtgovClient
from ctgov_agent.ctgov.models import parse_study
from ctgov_agent.engine.aggregate import aggregate_by_dimension
from ctgov_agent.engine.executor import build_query_params
from ctgov_agent.engine.vizselect import distribution_chart
from ctgov_agent.planner.base import Planner, PlannerError
from ctgov_agent.planner.ir import (
    ComparisonPlan,
    DistributionPlan,
    Filters,
    QueryPlan,
)


def _hints_from_request(req: VisualizeRequest) -> Filters:
    """The structured request fields as a Filters block, passed to the planner as strong hints."""
    return Filters(
        condition=req.condition,
        intervention=req.drug_name,
        sponsor=req.sponsor,
        country=req.country,
        phase=req.phase,
        start_year_min=req.start_year,
        start_year_max=req.end_year,
    )


def _merge_hints(plan: QueryPlan, req: VisualizeRequest) -> QueryPlan:
    """Override the plan's filters with any structured fields the user gave (explicit wins)."""
    overrides: dict[str, Any] = {}
    if req.condition is not None:
        overrides["condition"] = req.condition
    if req.drug_name is not None:
        overrides["intervention"] = req.drug_name
    if req.sponsor is not None:
        overrides["sponsor"] = req.sponsor
    if req.country is not None:
        overrides["country"] = req.country
    if req.phase is not None:
        overrides["phase"] = req.phase
    if req.start_year is not None:
        overrides["start_year_min"] = req.start_year
    if req.end_year is not None:
        overrides["start_year_max"] = req.end_year
    if not overrides:
        return plan
    if isinstance(plan, ComparisonPlan):
        merged = plan.base_filters.model_copy(update=overrides)
        return plan.model_copy(update={"base_filters": merged})
    merged = plan.filters.model_copy(update=overrides)
    return plan.model_copy(update={"filters": merged})


class Pipeline:
    def __init__(self, planner: Planner, client: CtgovClient) -> None:
        self._planner = planner
        self._client = client

    async def aclose(self) -> None:
        await self._client.aclose()
        planner_close = getattr(self._planner, "aclose", None)
        if planner_close is not None:
            await planner_close()

    async def run(self, request: VisualizeRequest) -> AgentResponse:
        hints = _hints_from_request(request)
        try:
            plan = await self._planner.plan(request.query, hints)
        except PlannerError as exc:
            return RefusedResponse(reason=exc.reason, message=exc.message)
        plan = _merge_hints(plan, request)
        return await self._dispatch(plan)

    async def _dispatch(self, plan: QueryPlan) -> AgentResponse:
        if isinstance(plan, DistributionPlan):
            return await self._run_distribution(plan)
        return RefusedResponse(
            reason="unsupported_intent",
            message=f"The '{plan.intent}' intent is not yet supported.",
        )

    async def _run_distribution(self, plan: DistributionPlan) -> AgentResponse:
        params = build_query_params(plan.filters)
        total = await self._client.count(params)
        studies = await self._client.search(params)
        records = [parse_study(study) for study in studies]
        buckets = aggregate_by_dimension(records, plan.dimension)
        if not buckets:
            return RefusedResponse(
                reason="no_data",
                message="No trials matched the query, so there is nothing to visualize.",
            )
        viz, sort_desc = distribution_chart(plan, buckets)
        meta = Meta(
            total_trials_matched=total,
            trials_aggregated=len(records),
            filters_applied=plan.filters.model_dump(mode="json", exclude_none=True),
            query_interpretation=plan.notes,
            sort=sort_desc,
            truncated=len(studies) >= DEFAULT_MAX_RECORDS,
        )
        return OkResponse(visualization=viz, meta=meta)
