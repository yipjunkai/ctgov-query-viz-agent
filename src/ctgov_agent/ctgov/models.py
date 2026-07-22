"""Typed, defensive views over ClinicalTrials.gov study records.

The API returns deeply-nested, partially-populated JSON. :func:`parse_study` is deliberately
*total* — it never raises on a missing or wrong-typed field; it returns ``None``/empties instead —
because a wrong parse must never surface downstream as a wrong number. The retained ``raw``
projection is what lets a citation later prove its excerpt actually occurs in the source record.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class StudyRecord:
    """The fields we project from a study, normalized to flat Python types."""

    nct_id: str
    brief_title: str | None
    phases: tuple[str, ...]
    study_type: str | None
    status: str | None
    start_date: str | None
    start_year: int | None
    sponsor_name: str | None
    sponsor_class: str | None
    intervention_types: tuple[str, ...]
    intervention_names: tuple[str, ...]
    countries: tuple[str, ...]
    raw: Mapping[str, Any]
    conditions: tuple[str, ...] = ()


def _section(value: Any) -> dict[str, Any]:
    """Return value as a dict if it is one, else an empty dict (keeps navigation total)."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _str_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(v for v in cast("list[Any]", value) if isinstance(v, str))


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [cast("dict[str, Any]", v) for v in cast("list[Any]", value) if isinstance(v, dict)]


def parse_study(study: Mapping[str, Any]) -> StudyRecord:
    """Parse one raw study dict into a StudyRecord. Never raises."""
    ps = _section(study.get("protocolSection"))

    ident = _section(ps.get("identificationModule"))
    status_mod = _section(ps.get("statusModule"))
    design = _section(ps.get("designModule"))
    sponsor = _section(_section(ps.get("sponsorCollaboratorsModule")).get("leadSponsor"))

    start_date = _opt_str(_section(status_mod.get("startDateStruct")).get("date"))
    start_year: int | None = None
    if start_date is not None and len(start_date) >= 4 and start_date[:4].isdigit():
        start_year = int(start_date[:4])

    intervention_types: list[str] = []
    intervention_names: list[str] = []
    for iv in _dict_list(_section(ps.get("armsInterventionsModule")).get("interventions")):
        itype = _opt_str(iv.get("type"))
        if itype is not None:
            intervention_types.append(itype)
        iname = _opt_str(iv.get("name"))
        if iname is not None:
            intervention_names.append(iname)

    countries: list[str] = []
    for loc in _dict_list(_section(ps.get("contactsLocationsModule")).get("locations")):
        country = _opt_str(loc.get("country"))
        if country is not None and country not in countries:  # dedupe, preserve order
            countries.append(country)

    return StudyRecord(
        nct_id=_opt_str(ident.get("nctId")) or "",
        brief_title=_opt_str(ident.get("briefTitle")),
        conditions=_str_list(_section(ps.get("conditionsModule")).get("conditions")),
        phases=_str_list(design.get("phases")),
        study_type=_opt_str(design.get("studyType")),
        status=_opt_str(status_mod.get("overallStatus")),
        start_date=start_date,
        start_year=start_year,
        sponsor_name=_opt_str(sponsor.get("name")),
        sponsor_class=_opt_str(sponsor.get("class")),
        intervention_types=tuple(intervention_types),
        intervention_names=tuple(intervention_names),
        countries=tuple(countries),
        raw=study,
    )
