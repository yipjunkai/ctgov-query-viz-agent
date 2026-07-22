"""Filters → CT.gov query params. The exact strings here were verified against the live API."""

from ctgov_agent.engine.executor import (
    build_query_params,
    candidate_values,
    combine_filters,
    with_any_dimension_value,
    with_dimension_value,
)
from ctgov_agent.planner.ir import CategoricalDim, Filters
from ctgov_agent.vocab.controlled import InterventionType, Phase, SponsorClass, Status, StudyType


def test_entity_and_location_filters() -> None:
    params = build_query_params(
        Filters(condition="melanoma", intervention="UnknownDrug", sponsor="Merck", country="France")
    )
    assert params == {
        "query.cond": "melanoma",
        "query.intr": "UnknownDrug",  # unrecognized drug passes through verbatim
        "query.spons": "Merck",
        "query.locn": "France",
    }


def test_known_drug_is_or_expanded_to_its_synonyms() -> None:
    # A recognized brand name is searched as the union of the drug's names (CT.gov normalizes most
    # of these itself, but imperfectly — the OR recovers the full trial set).
    params = build_query_params(Filters(intervention="Keytruda"))
    assert params["query.intr"] == "Pembrolizumab OR Keytruda OR MK-3475"


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


def test_study_type_and_intervention_type_clauses() -> None:
    params = build_query_params(
        Filters(
            study_type=[StudyType.INTERVENTIONAL],
            intervention_type=[InterventionType.DRUG, InterventionType.BIOLOGICAL],
        )
    )
    assert params["filter.advanced"] == (
        "AREA[StudyType]INTERVENTIONAL AND "
        "(AREA[InterventionType]DRUG OR AREA[InterventionType]BIOLOGICAL)"
    )


def test_combine_filters_overlays_series_onto_base() -> None:
    combined = combine_filters(
        Filters(condition="melanoma", intervention="baseDrug"), Filters(intervention="Nivolumab")
    )
    assert combined.condition == "melanoma"  # shared base kept
    assert combined.intervention == "Nivolumab"  # series value wins


def test_candidate_values_defaults_to_full_vocabulary() -> None:
    values = candidate_values(Filters(condition="melanoma"), CategoricalDim.phase)
    assert list(values) == list(Phase)  # no phase filter -> break down over every phase


def test_candidate_values_respects_an_existing_filter() -> None:
    # A distribution over phase that already pins two phases breaks down over only those.
    values = candidate_values(Filters(phase=[Phase.PHASE2, Phase.PHASE3]), CategoricalDim.phase)
    assert list(values) == [Phase.PHASE2, Phase.PHASE3]


def test_with_dimension_value_narrows_to_one_value() -> None:
    narrowed = with_dimension_value(Filters(condition="cancer"), CategoricalDim.phase, Phase.PHASE1)
    assert narrowed.phase == [Phase.PHASE1]
    assert narrowed.condition == "cancer"  # other filters preserved
    assert build_query_params(narrowed)["filter.advanced"] == "AREA[Phase]PHASE1"


def test_with_any_dimension_value_ors_all_candidate_values() -> None:
    params = build_query_params(with_any_dimension_value(Filters(), CategoricalDim.study_type))
    assert params["filter.advanced"] == (
        "(AREA[StudyType]INTERVENTIONAL OR AREA[StudyType]OBSERVATIONAL OR "
        "AREA[StudyType]EXPANDED_ACCESS)"
    )
