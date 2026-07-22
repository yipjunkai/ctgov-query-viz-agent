"""Translate IR :class:`Filters` into ClinicalTrials.gov v2 query parameters.

Two mechanisms, both verified against the live API:

* Entity/text constraints and status use dedicated params (``query.cond``, ``query.intr``,
  ``query.spons``, ``query.locn``, ``filter.overallStatus`` with ``|`` for OR).
* Enum and date constraints use an Essie ``filter.advanced`` expression: each field becomes an
  ``AREA[Field](V1 OR V2)`` clause and start-year becomes ``AREA[StartDate]RANGE[lo,hi]``; clauses
  are joined with ``AND``.
"""

from collections.abc import Sequence
from enum import StrEnum

from ctgov_agent.planner.ir import CategoricalDim, Filters
from ctgov_agent.vocab.controlled import (
    InterventionType,
    Phase,
    SponsorClass,
    Status,
    StudyType,
)


def _append_enum_clause(clauses: list[str], area: str, values: Sequence[StrEnum] | None) -> None:
    if not values:
        return
    terms = " OR ".join(f"AREA[{area}]{v.value}" for v in values)
    clauses.append(f"({terms})" if len(values) > 1 else terms)


def _date_range_clause(lo: int | None, hi: int | None) -> str:
    if lo is None and hi is None:
        return ""
    low = str(lo) if lo is not None else "MIN"
    high = str(hi) if hi is not None else "MAX"
    return f"AREA[StartDate]RANGE[{low},{high}]"


def _build_advanced(filters: Filters) -> str:
    clauses: list[str] = []
    _append_enum_clause(clauses, "Phase", filters.phase)
    _append_enum_clause(clauses, "StudyType", filters.study_type)
    _append_enum_clause(clauses, "LeadSponsorClass", filters.sponsor_class)
    _append_enum_clause(clauses, "InterventionType", filters.intervention_type)
    date_clause = _date_range_clause(filters.start_year_min, filters.start_year_max)
    if date_clause:
        clauses.append(date_clause)
    return " AND ".join(clauses)


def combine_filters(base: Filters, override: Filters) -> Filters:
    """Overlay a comparison series' filters onto the shared base filters (series values win)."""
    return base.model_copy(update=override.model_dump(exclude_none=True))


def build_query_params(filters: Filters) -> dict[str, str]:
    """Build the CT.gov ``/studies`` query params for a filter set (no pagination/projection)."""
    params: dict[str, str] = {}
    if filters.condition:
        params["query.cond"] = filters.condition
    if filters.intervention:
        params["query.intr"] = filters.intervention
    if filters.sponsor:
        params["query.spons"] = filters.sponsor
    if filters.country:
        params["query.locn"] = filters.country
    if filters.status:
        params["filter.overallStatus"] = "|".join(s.value for s in filters.status)
    advanced = _build_advanced(filters)
    if advanced:
        params["filter.advanced"] = advanced
    return params


# Each categorical dimension's controlled vocabulary and the Filters field that selects it. This is
# what lets a too-broad distribution be answered with one server-side count per value instead of
# paging every record (see the pipeline's facet fast path).
_DIMENSION_VOCAB: dict[CategoricalDim, Sequence[StrEnum]] = {
    CategoricalDim.phase: list(Phase),
    CategoricalDim.status: list(Status),
    CategoricalDim.study_type: list(StudyType),
    CategoricalDim.sponsor_class: list(SponsorClass),
    CategoricalDim.intervention_type: list(InterventionType),
}
_DIMENSION_FIELD: dict[CategoricalDim, str] = {
    CategoricalDim.phase: "phase",
    CategoricalDim.status: "status",
    CategoricalDim.study_type: "study_type",
    CategoricalDim.sponsor_class: "sponsor_class",
    CategoricalDim.intervention_type: "intervention_type",
}


def _filter_values(filters: Filters, dim: CategoricalDim) -> Sequence[StrEnum] | None:
    """The values a filter already constrains the dimension to, if any (typed, no ``getattr``)."""
    if dim is CategoricalDim.phase:
        return filters.phase
    if dim is CategoricalDim.status:
        return filters.status
    if dim is CategoricalDim.study_type:
        return filters.study_type
    if dim is CategoricalDim.sponsor_class:
        return filters.sponsor_class
    return filters.intervention_type


def candidate_values(filters: Filters, dim: CategoricalDim) -> Sequence[StrEnum]:
    """The values to break a distribution down over: the filter's own values if it already
    constrains the dimension, else the full controlled vocabulary."""
    return _filter_values(filters, dim) or _DIMENSION_VOCAB[dim]


def with_dimension_value(filters: Filters, dim: CategoricalDim, value: StrEnum) -> Filters:
    """Narrow filters to a single value of the dimension (for that value's server-side count)."""
    return filters.model_copy(update={_DIMENSION_FIELD[dim]: [value]})


def with_any_dimension_value(filters: Filters, dim: CategoricalDim) -> Filters:
    """Narrow filters to trials carrying *any* candidate value of the dimension — counting this set
    gives the classified total, so ``matched - classified`` is the exact unclassified count."""
    return filters.model_copy(update={_DIMENSION_FIELD[dim]: list(candidate_values(filters, dim))})
