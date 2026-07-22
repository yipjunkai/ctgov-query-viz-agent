"""Year and country aggregation."""

from ctgov_agent.ctgov.models import StudyRecord
from ctgov_agent.engine.aggregate import aggregate_by_country, aggregate_by_year


def _rec(
    nct: str, *, start_year: int | None = None, countries: tuple[str, ...] = ()
) -> StudyRecord:
    return StudyRecord(
        nct_id=nct,
        brief_title=None,
        phases=(),
        study_type=None,
        status=None,
        start_date=None,
        start_year=start_year,
        sponsor_name=None,
        sponsor_class=None,
        intervention_types=(),
        intervention_names=(),
        countries=countries,
        raw={},
    )


def test_year_grouping_skips_missing_start_year() -> None:
    records = [
        _rec("N1", start_year=2015),
        _rec("N2", start_year=2016),
        _rec("N3", start_year=2016),
        _rec("N4"),  # no start year -> excluded
    ]
    assert {b.key: b.count for b in aggregate_by_year(records)} == {"2015": 1, "2016": 2}


def test_country_dedupes_within_a_study() -> None:
    records = [
        _rec("N1", countries=("United States", "United States", "France")),
        _rec("N2", countries=("France",)),
    ]
    assert {b.key: b.count for b in aggregate_by_country(records)} == {
        "United States": 1,
        "France": 2,
    }
