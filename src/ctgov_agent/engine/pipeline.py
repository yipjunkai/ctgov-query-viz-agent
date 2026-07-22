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
    ResolvedEntity,
    VisualizeRequest,
)
from ctgov_agent.ctgov.client import DEFAULT_MAX_RECORDS, CtgovClient
from ctgov_agent.ctgov.models import StudyRecord, parse_study
from ctgov_agent.engine.advisories import (
    comparison_advisories,
    distribution_advisories,
    time_trend_advisories,
)
from ctgov_agent.engine.aggregate import (
    Bucket,
    Reconciliation,
    aggregate_by_country,
    aggregate_by_dimension,
    aggregate_by_year,
    dimension_values,
    reconcile,
)
from ctgov_agent.engine.citations import CITATIONS_PER_DATUM
from ctgov_agent.engine.executor import (
    build_query_params,
    candidate_values,
    combine_filters,
    with_any_dimension_value,
    with_dimension_value,
)
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
    CategoricalDim,
    ComparisonPlan,
    DistributionPlan,
    Filters,
    GeographicPlan,
    NetworkPlan,
    QueryPlan,
    TimeTrendPlan,
)
from ctgov_agent.vocab.controlled import humanize
from ctgov_agent.vocab.entities import resolve_drug


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


def _year_values(record: StudyRecord) -> tuple[int, ...]:
    return (record.start_year,) if record.start_year is not None else ()


def _reconciliation_notes(
    rec: Reconciliation, total: int, value_noun: str, breakdown: str
) -> list[str]:
    """Human-readable meta notes explaining any gap between the bars and the trial total."""
    notes: list[str] = []
    if rec.unclassified:
        notes.append(
            f"{rec.unclassified:,} of {total:,} trials report no {value_noun} and are excluded "
            f"from the {breakdown}."
        )
    if rec.multivalue:
        notes.append(
            f"A trial can report more than one {value_noun}; it is counted once per {value_noun}, "
            f"so counts can exceed the trial total."
        )
    return notes


def _resolved_entities(*names: str | None) -> list[ResolvedEntity]:
    """Canonicalize any recognized drug names, one entry per distinct canonical entity."""
    out: list[ResolvedEntity] = []
    seen: set[str] = set()
    for name in names:
        if not name:
            continue
        entity = resolve_drug(name)
        if entity is None or entity.canonical in seen:
            continue
        seen.add(entity.canonical)
        out.append(
            ResolvedEntity(input=name, canonical=entity.canonical, synonyms=list(entity.synonyms))
        )
    return out


def _same_drug_advisories(plan: ComparisonPlan) -> list[str]:
    """Flag comparison series that resolve to the same drug (e.g. Keytruda vs Pembrolizumab)."""
    groups: dict[str, list[str]] = {}
    for series in plan.series:
        if not series.filters.intervention:
            continue
        entity = resolve_drug(series.filters.intervention)
        if entity is not None:
            groups.setdefault(entity.canonical, []).append(series.label)
    return [
        f"Series {' and '.join(labels)} resolve to the same drug ({canonical}) — "
        f"this compares it with itself."
        for canonical, labels in groups.items()
        if len(labels) > 1
    ]


def _build_meta(
    total: int,
    records: list[StudyRecord],
    filters: Filters,
    notes: str | None,
    sort: str,
    *,
    unclassified: int = 0,
    assumptions: list[str] | None = None,
    advisories: list[str] | None = None,
) -> Meta:
    return Meta(
        total_trials_matched=total,
        trials_aggregated=len(records),
        trials_unclassified=unclassified,
        filters_applied=filters.model_dump(mode="json", exclude_none=True),
        query_interpretation=notes,
        sort=sort,
        assumptions=assumptions or [],
        advisories=advisories or [],
        resolved_entities=_resolved_entities(filters.intervention),
        truncated=len(records) >= DEFAULT_MAX_RECORDS,
    )


def _no_data(
    message: str = "No trials matched the query, so there is nothing to visualize.",
) -> RefusedResponse:
    return RefusedResponse(reason="no_data", message=message)


def _missing_dimension_message(dim: CategoricalDim, count: int) -> str:
    """Honest no-data message when trials *did* match but none carry the grouped dimension.

    Without this, an all-null dimension (e.g. a phase breakdown over a purely observational match
    set) would wrongly report "no trials matched" when thousands did.
    """
    label = dim.value.replace("_", " ")
    return (
        f"Matched {count:,} trials, but none report a {label} value, so there is nothing to "
        f"break down."
    )


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

    async def _page(self, filters: Filters) -> list[StudyRecord]:
        """Page every matching study and parse it. No count guard — callers gate on the count."""
        studies = await self._client.search(build_query_params(filters))
        return [parse_study(study) for study in studies]

    def _too_broad(self, total: int) -> RefusalSignal:
        return RefusalSignal(
            "too_broad",
            f"About {total:,} trials match — too many to aggregate exactly. Add a filter "
            f"(condition, drug, phase, or year range) to narrow the query.",
            {"total": total, "threshold": self._too_broad_threshold},
        )

    async def _fetch(self, filters: Filters) -> tuple[int, list[StudyRecord]]:
        """Count pre-flight, then page all matches. Refuses above the threshold — used by the
        intents that genuinely need every record (time trend, geographic, comparison, network)."""
        total = await self._client.count(build_query_params(filters))
        if total > self._too_broad_threshold:
            raise self._too_broad(total)
        return total, await self._page(filters)

    async def _run_distribution(self, plan: DistributionPlan) -> AgentResponse:
        total = await self._client.count(build_query_params(plan.filters))
        if total > self._too_broad_threshold:
            # A distribution is over a small controlled-vocab enum, so instead of refusing we count
            # each value server-side — exact, no paging. This retires the too-broad dead-end.
            return await self._run_distribution_by_facets(plan, total)
        records = await self._page(plan.filters)
        buckets = aggregate_by_dimension(records, plan.dimension)
        if not buckets:
            if records:
                return _no_data(_missing_dimension_message(plan.dimension, len(records)))
            return _no_data()
        viz, sort_desc = distribution_chart(plan, buckets)
        rec = reconcile(records, buckets, lambda r: dimension_values(r, plan.dimension))
        noun = plan.dimension.value.replace("_", " ")
        return OkResponse(
            visualization=viz,
            meta=_build_meta(
                total,
                records,
                plan.filters,
                plan.notes,
                sort_desc,
                unclassified=rec.unclassified,
                assumptions=_reconciliation_notes(rec, len(records), noun, "breakdown"),
                advisories=distribution_advisories(buckets, noun),
            ),
        )

    async def _run_distribution_by_facets(
        self, plan: DistributionPlan, total: int
    ) -> AgentResponse:
        """Too-broad distribution via one server-side count per value (no full paging).

        Each value's count is the API's exact ``totalCount`` for that filtered slice; a few sample
        records per value back the deep citations. One extra "any value" count yields the exact
        classified total, so the reconciliation stays honest.
        """
        dim = plan.dimension
        buckets: list[Bucket] = []
        for value in candidate_values(plan.filters, dim):
            params = build_query_params(with_dimension_value(plan.filters, dim, value))
            count, sample = await self._client.count_and_sample(params, CITATIONS_PER_DATUM)
            if count == 0:
                continue
            buckets.append(
                Bucket(
                    key=value.value,
                    label=humanize(value.value),
                    members=[parse_study(study) for study in sample],
                    total=count,
                )
            )
        if not buckets:
            return _no_data(_missing_dimension_message(dim, total))
        classified = await self._client.count(
            build_query_params(with_any_dimension_value(plan.filters, dim))
        )
        viz, sort_desc = distribution_chart(plan, buckets)
        bar_sum = sum(bucket.count for bucket in buckets)
        rec = Reconciliation(unclassified=total - classified, multivalue=bar_sum > classified)
        noun = dim.value.replace("_", " ")
        assumptions = [
            f"This query matches {total:,} trials — too many to page individually. Each {noun} "
            f"count is an exact server-side total; the deep citations are a small per-value "
            f"sample.",
            *_reconciliation_notes(rec, total, noun, "breakdown"),
        ]
        meta = Meta(
            total_trials_matched=total,
            trials_aggregated=total,
            trials_unclassified=rec.unclassified,
            filters_applied=plan.filters.model_dump(mode="json", exclude_none=True),
            query_interpretation=plan.notes,
            sort=sort_desc,
            assumptions=assumptions,
            advisories=distribution_advisories(buckets, noun),
            resolved_entities=_resolved_entities(plan.filters.intervention),
            truncated=False,
        )
        return OkResponse(visualization=viz, meta=meta)

    async def _run_time_trend(self, plan: TimeTrendPlan) -> AgentResponse:
        total, records = await self._fetch(plan.filters)
        buckets = aggregate_by_year(records)
        if not buckets:
            return _no_data("No trials with a known start date matched the query.")
        viz, sort_desc = time_series_chart(plan.filters, buckets)
        rec = reconcile(records, buckets, _year_values)
        return OkResponse(
            visualization=viz,
            meta=_build_meta(
                total,
                records,
                plan.filters,
                plan.notes,
                sort_desc,
                unclassified=rec.unclassified,
                assumptions=_reconciliation_notes(rec, len(records), "start date", "trend"),
                advisories=time_trend_advisories(buckets),
            ),
        )

    async def _run_geographic(self, plan: GeographicPlan) -> AgentResponse:
        total, records = await self._fetch(plan.filters)
        buckets = aggregate_by_country(records)
        if not buckets:
            return _no_data("No trials with a known location matched the query.")
        viz, sort_desc = geographic_chart(plan.filters, buckets)
        rec = reconcile(records, buckets, lambda r: r.countries)
        return OkResponse(
            visualization=viz,
            meta=_build_meta(
                total,
                records,
                plan.filters,
                plan.notes,
                sort_desc,
                unclassified=rec.unclassified,
                assumptions=_reconciliation_notes(rec, len(records), "country", "map"),
                advisories=distribution_advisories(buckets, "country"),
            ),
        )

    async def _run_comparison(self, plan: ComparisonPlan) -> AgentResponse:
        series_results: list[tuple[str, list[Bucket]]] = []
        aggregated = 0
        unclassified = 0
        multivalue = False
        for series in plan.series:
            filters = combine_filters(plan.base_filters, series.filters)
            _total, records = await self._fetch(filters)
            aggregated += len(records)
            buckets = aggregate_by_dimension(records, plan.dimension)
            rec = reconcile(records, buckets, lambda r: dimension_values(r, plan.dimension))
            unclassified += rec.unclassified
            multivalue = multivalue or rec.multivalue
            series_results.append((series.label, buckets))
        if all(not buckets for _label, buckets in series_results):
            if aggregated:
                return _no_data(_missing_dimension_message(plan.dimension, aggregated))
            return _no_data()
        viz, sort_desc = comparison_chart(plan, series_results)
        noun = plan.dimension.value.replace("_", " ")
        meta = Meta(
            total_trials_matched=aggregated,
            trials_aggregated=aggregated,
            trials_unclassified=unclassified,
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
            assumptions=_reconciliation_notes(
                Reconciliation(unclassified, multivalue), aggregated, noun, "comparison"
            ),
            advisories=comparison_advisories(series_results) + _same_drug_advisories(plan),
            resolved_entities=_resolved_entities(
                plan.base_filters.intervention, *(s.filters.intervention for s in plan.series)
            ),
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
