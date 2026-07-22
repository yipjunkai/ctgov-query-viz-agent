"""Orchestrates a single request: plan → execute → aggregate → visualize → response.

The LLM (via the planner) appears exactly once, at the top, and only produces a validated plan.
Everything after is deterministic. Structured request fields are merged over the plan *after*
planning, so explicit user input always wins over the model.
"""

from typing import Any

import httpx

from ctgov_agent.api.schemas import (
    AgentResponse,
    ClarificationResponse,
    Meta,
    OkResponse,
    RefusedResponse,
    VisualizeRequest,
)
from ctgov_agent.ctgov.client import DEFAULT_MAX_RECORDS, CtgovClient
from ctgov_agent.ctgov.models import StudyRecord, parse_study
from ctgov_agent.engine.aggregate import (
    Bucket,
    aggregate_by_country,
    aggregate_by_dimension,
    aggregate_by_year,
)
from ctgov_agent.engine.executor import build_query_params, combine_filters
from ctgov_agent.engine.network import build_network
from ctgov_agent.engine.vizselect import (
    comparison_chart,
    distribution_chart,
    geographic_chart,
    network_graph,
    time_series_chart,
)
from ctgov_agent.planner.base import Planner, PlannerError
from ctgov_agent.planner.ir import (
    ComparisonPlan,
    DistributionPlan,
    Filters,
    GeographicPlan,
    NetworkPlan,
    QueryPlan,
    TimeTrendPlan,
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


def _build_meta(
    total: int, records: list[StudyRecord], filters: Filters, notes: str | None, sort: str
) -> Meta:
    return Meta(
        total_trials_matched=total,
        trials_aggregated=len(records),
        filters_applied=filters.model_dump(mode="json", exclude_none=True),
        query_interpretation=notes,
        sort=sort,
        truncated=len(records) >= DEFAULT_MAX_RECORDS,
    )


def _no_data(
    message: str = "No trials matched the query, so there is nothing to visualize.",
) -> RefusedResponse:
    return RefusedResponse(reason="no_data", message=message)


# Refuse rather than aggregate a match set too large to count exactly. Well under the paging
# backstop so exact aggregation stays exact.
DEFAULT_TOO_BROAD_THRESHOLD = 10000


class RefusalSignal(Exception):
    """Raised inside the engine to abort a run into a typed refusal (e.g. the too-broad guard)."""

    def __init__(self, reason: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.detail = detail or {}


class Pipeline:
    def __init__(
        self,
        planner: Planner,
        client: CtgovClient,
        *,
        too_broad_threshold: int = DEFAULT_TOO_BROAD_THRESHOLD,
    ) -> None:
        self._planner = planner
        self._client = client
        self._too_broad_threshold = too_broad_threshold

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
            if exc.reason == "ambiguous":
                return ClarificationResponse(question=exc.message)
            return RefusedResponse(reason=exc.reason, message=exc.message)
        plan = _merge_hints(plan, request)
        try:
            return await self._dispatch(plan)
        except RefusalSignal as exc:
            return RefusedResponse(reason=exc.reason, message=exc.message, detail=exc.detail)
        except httpx.HTTPError as exc:
            return RefusedResponse(
                reason="upstream_error",
                message=f"The ClinicalTrials.gov request failed: {exc}",
            )

    async def _dispatch(self, plan: QueryPlan) -> AgentResponse:
        if isinstance(plan, DistributionPlan):
            return await self._run_distribution(plan)
        if isinstance(plan, TimeTrendPlan):
            return await self._run_time_trend(plan)
        if isinstance(plan, GeographicPlan):
            return await self._run_geographic(plan)
        if isinstance(plan, ComparisonPlan):
            return await self._run_comparison(plan)
        # NetworkPlan is the only remaining variant; a new intent would fail typecheck here,
        # which is the signal to add its branch.
        return await self._run_network(plan)

    async def _fetch(self, filters: Filters) -> tuple[int, list[StudyRecord]]:
        params = build_query_params(filters)
        total = await self._client.count(params)
        if total > self._too_broad_threshold:
            raise RefusalSignal(
                "too_broad",
                f"About {total:,} trials match — too many to aggregate exactly. Add a filter "
                f"(condition, drug, phase, or year range) to narrow the query.",
                {"total": total, "threshold": self._too_broad_threshold},
            )
        studies = await self._client.search(params)
        return total, [parse_study(study) for study in studies]

    async def _run_distribution(self, plan: DistributionPlan) -> AgentResponse:
        total, records = await self._fetch(plan.filters)
        buckets = aggregate_by_dimension(records, plan.dimension)
        if not buckets:
            return _no_data()
        viz, sort_desc = distribution_chart(plan, buckets)
        return OkResponse(
            visualization=viz, meta=_build_meta(total, records, plan.filters, plan.notes, sort_desc)
        )

    async def _run_time_trend(self, plan: TimeTrendPlan) -> AgentResponse:
        total, records = await self._fetch(plan.filters)
        buckets = aggregate_by_year(records)
        if not buckets:
            return _no_data("No trials with a known start date matched the query.")
        viz, sort_desc = time_series_chart(plan.filters, buckets)
        return OkResponse(
            visualization=viz, meta=_build_meta(total, records, plan.filters, plan.notes, sort_desc)
        )

    async def _run_geographic(self, plan: GeographicPlan) -> AgentResponse:
        total, records = await self._fetch(plan.filters)
        buckets = aggregate_by_country(records)
        if not buckets:
            return _no_data("No trials with a known location matched the query.")
        viz, sort_desc = geographic_chart(plan.filters, buckets)
        return OkResponse(
            visualization=viz, meta=_build_meta(total, records, plan.filters, plan.notes, sort_desc)
        )

    async def _run_comparison(self, plan: ComparisonPlan) -> AgentResponse:
        series_results: list[tuple[str, list[Bucket]]] = []
        aggregated = 0
        for series in plan.series:
            filters = combine_filters(plan.base_filters, series.filters)
            _total, records = await self._fetch(filters)
            aggregated += len(records)
            series_results.append((series.label, aggregate_by_dimension(records, plan.dimension)))
        if all(not buckets for _label, buckets in series_results):
            return _no_data()
        viz, sort_desc = comparison_chart(plan, series_results)
        meta = Meta(
            total_trials_matched=aggregated,
            trials_aggregated=aggregated,
            filters_applied={
                "base": plan.base_filters.model_dump(mode="json", exclude_none=True),
                "series": [
                    {
                        "label": s.label,
                        "filters": s.filters.model_dump(mode="json", exclude_none=True),
                    }
                    for s in plan.series
                ],
            },
            query_interpretation=plan.notes,
            sort=sort_desc,
            truncated=False,
        )
        return OkResponse(visualization=viz, meta=meta)

    async def _run_network(self, plan: NetworkPlan) -> AgentResponse:
        total, records = await self._fetch(plan.filters)
        nodes, edges = build_network(records, plan.endpoints)
        if not edges:
            return _no_data("No co-occurring entities were found to build a network.")
        viz, sort_desc = network_graph(plan, nodes, edges)
        return OkResponse(
            visualization=viz, meta=_build_meta(total, records, plan.filters, plan.notes, sort_desc)
        )
