"""Deterministic aggregation over parsed study records.

A study can legitimately carry several values for a dimension (multiple phases, several intervention
types). We count a study once *per distinct value* it has, so bucket counts can sum to more than the
number of trials — that is faithful to the data, and the meta block reports both numbers. Each
bucket retains its member records so citations can be attached without a second pass.
"""

from dataclasses import dataclass

from ctgov_agent.ctgov.models import StudyRecord
from ctgov_agent.planner.ir import CategoricalDim
from ctgov_agent.vocab.controlled import humanize


@dataclass
class Bucket:
    key: str
    label: str
    members: list[StudyRecord]

    @property
    def count(self) -> int:
        return len(self.members)


def dimension_values(record: StudyRecord, dim: CategoricalDim) -> list[str]:
    """The value(s) a record contributes to for a categorical dimension."""
    if dim is CategoricalDim.phase:
        return list(record.phases)
    if dim is CategoricalDim.status:
        return [record.status] if record.status else []
    if dim is CategoricalDim.study_type:
        return [record.study_type] if record.study_type else []
    if dim is CategoricalDim.sponsor_class:
        return [record.sponsor_class] if record.sponsor_class else []
    return list(record.intervention_types)  # CategoricalDim.intervention_type


def aggregate_by_dimension(records: list[StudyRecord], dim: CategoricalDim) -> list[Bucket]:
    grouped: dict[str, list[StudyRecord]] = {}
    for record in records:
        for value in dict.fromkeys(dimension_values(record, dim)):  # distinct, order-preserving
            grouped.setdefault(value, []).append(record)
    return [
        Bucket(key=key, label=humanize(key), members=members) for key, members in grouped.items()
    ]


def aggregate_by_year(records: list[StudyRecord]) -> list[Bucket]:
    """Group by start year. Records with no parseable start date are excluded (reported in meta)."""
    grouped: dict[str, list[StudyRecord]] = {}
    for record in records:
        if record.start_year is None:
            continue
        grouped.setdefault(str(record.start_year), []).append(record)
    return [Bucket(key=year, label=year, members=members) for year, members in grouped.items()]


def aggregate_by_country(records: list[StudyRecord]) -> list[Bucket]:
    """Group by country; a multi-country trial counts once per distinct country."""
    grouped: dict[str, list[StudyRecord]] = {}
    for record in records:
        for country in dict.fromkeys(record.countries):
            grouped.setdefault(country, []).append(record)
    return [
        Bucket(key=country, label=country, members=members) for country, members in grouped.items()
    ]
