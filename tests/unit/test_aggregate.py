"""Aggregation counting: multi-value membership, per-study dedupe, single-valued dimensions."""

from ctgov_agent.ctgov.models import StudyRecord
from ctgov_agent.engine.aggregate import aggregate_by_dimension
from ctgov_agent.planner.ir import CategoricalDim


def _rec(
    nct: str,
    *,
    phases: tuple[str, ...] = (),
    status: str | None = None,
    itypes: tuple[str, ...] = (),
) -> StudyRecord:
    return StudyRecord(
        nct_id=nct,
        brief_title=None,
        phases=phases,
        study_type=None,
        status=status,
        start_date=None,
        start_year=None,
        sponsor_name=None,
        sponsor_class=None,
        intervention_types=itypes,
        intervention_names=(),
        countries=(),
        raw={},
    )


def _counts(records: list[StudyRecord], dim: CategoricalDim) -> dict[str, int]:
    return {b.key: b.count for b in aggregate_by_dimension(records, dim)}


def test_multi_phase_study_counts_in_each_phase() -> None:
    records = [_rec("N1", phases=("PHASE1", "PHASE2")), _rec("N2", phases=("PHASE2",))]
    assert _counts(records, CategoricalDim.phase) == {"PHASE1": 1, "PHASE2": 2}


def test_repeated_value_within_a_study_counts_once() -> None:
    records = [_rec("N1", itypes=("DRUG", "DRUG", "DEVICE"))]
    assert _counts(records, CategoricalDim.intervention_type) == {"DRUG": 1, "DEVICE": 1}


def test_single_valued_dimension() -> None:
    records = [
        _rec("N1", status="RECRUITING"),
        _rec("N2", status="RECRUITING"),
        _rec("N3", status="COMPLETED"),
    ]
    assert _counts(records, CategoricalDim.status) == {"RECRUITING": 2, "COMPLETED": 1}


def test_missing_dimension_value_contributes_nothing() -> None:
    assert _counts([_rec("N1")], CategoricalDim.phase) == {}
