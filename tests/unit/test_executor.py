"""Filters → CT.gov query params. The exact strings here were verified against the live API."""

from ctgov_agent.engine.executor import build_query_params
from ctgov_agent.planner.ir import Filters
from ctgov_agent.vocab.controlled import Phase, SponsorClass, Status


def test_entity_and_location_filters() -> None:
    params = build_query_params(
        Filters(
            condition="melanoma", intervention="Pembrolizumab", sponsor="Merck", country="France"
        )
    )
    assert params == {
        "query.cond": "melanoma",
        "query.intr": "Pembrolizumab",
        "query.spons": "Merck",
        "query.locn": "France",
    }


def test_status_is_pipe_joined() -> None:
    params = build_query_params(Filters(status=[Status.RECRUITING, Status.ACTIVE_NOT_RECRUITING]))
    assert params["filter.overallStatus"] == "RECRUITING|ACTIVE_NOT_RECRUITING"


def test_single_enum_clause_has_no_parens() -> None:
    params = build_query_params(Filters(phase=[Phase.PHASE3]))
    assert params["filter.advanced"] == "AREA[Phase]PHASE3"


def test_multi_value_enum_and_daterange_are_and_joined() -> None:
    params = build_query_params(
        Filters(
            phase=[Phase.PHASE2, Phase.PHASE3],
            sponsor_class=[SponsorClass.INDUSTRY],
            start_year_min=2015,
            start_year_max=2020,
        )
    )
    assert params["filter.advanced"] == (
        "(AREA[Phase]PHASE2 OR AREA[Phase]PHASE3) AND "
        "AREA[LeadSponsorClass]INDUSTRY AND "
        "AREA[StartDate]RANGE[2015,2020]"
    )


def test_open_ended_date_range_uses_min_max_sentinels() -> None:
    assert build_query_params(Filters(start_year_min=2015))["filter.advanced"] == (
        "AREA[StartDate]RANGE[2015,MAX]"
    )
    assert build_query_params(Filters(start_year_max=2020))["filter.advanced"] == (
        "AREA[StartDate]RANGE[MIN,2020]"
    )


def test_empty_filters_produce_no_params() -> None:
    assert build_query_params(Filters()) == {}
