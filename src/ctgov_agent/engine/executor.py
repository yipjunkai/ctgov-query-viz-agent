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

from ctgov_agent.planner.ir import Filters


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
