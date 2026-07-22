"""Count conservation: aggregation counts every (trial, distinct-value) membership exactly once.

Expected totals are computed independently from the raw study dicts, so this checks a semantic law
("no membership dropped or double-counted") rather than restating the implementation.
"""

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from ctgov_agent.ctgov.models import parse_study
from ctgov_agent.engine.aggregate import aggregate_by_dimension, dimension_values, reconcile
from ctgov_agent.planner.ir import CategoricalDim

_PHASES = ["NA", "PHASE1", "PHASE2", "PHASE3", "PHASE4"]
_STATUSES: list[str | None] = ["RECRUITING", "COMPLETED", "TERMINATED", None]


@st.composite
def _study(draw: st.DrawFn) -> dict[str, Any]:
    return {
        "protocolSection": {
            "designModule": {
                "phases": draw(st.lists(st.sampled_from(_PHASES), max_size=3, unique=True))
            },
            "statusModule": {"overallStatus": draw(st.sampled_from(_STATUSES))},
        }
    }


@given(st.lists(_study(), max_size=10))
def test_bucket_counts_conserve(studies: list[dict[str, Any]]) -> None:
    records = [parse_study(s) for s in studies]

    phase_total = sum(b.count for b in aggregate_by_dimension(records, CategoricalDim.phase))
    expected_phase = sum(len(set(s["protocolSection"]["designModule"]["phases"])) for s in studies)
    assert phase_total == expected_phase  # multi-valued: one count per distinct phase

    status_total = sum(b.count for b in aggregate_by_dimension(records, CategoricalDim.status))
    expected_status = sum(
        1 for s in studies if s["protocolSection"]["statusModule"]["overallStatus"] is not None
    )
    assert status_total == expected_status  # single-valued: one count per record with a status


@given(st.lists(_study(), max_size=10))
def test_reconciliation_accounts_for_every_trial(studies: list[dict[str, Any]]) -> None:
    records = [parse_study(s) for s in studies]
    dim = CategoricalDim.phase
    buckets = aggregate_by_dimension(records, dim)
    rec = reconcile(records, buckets, lambda r: dimension_values(r, dim))

    # unclassified == trials with no phase, computed independently from the raw dicts.
    expected_unclassified = sum(
        1 for s in studies if not set(s["protocolSection"]["designModule"]["phases"])
    )
    assert rec.unclassified == expected_unclassified

    # The trials that DO land in a bucket are exactly those with >=1 phase — nothing lost.
    with_value = len(records) - rec.unclassified
    expected_with_value = sum(
        1 for s in studies if set(s["protocolSection"]["designModule"]["phases"])
    )
    assert with_value == expected_with_value

    # multivalue is set exactly when some trial carries more than one distinct phase.
    any_multi = any(len(set(s["protocolSection"]["designModule"]["phases"])) > 1 for s in studies)
    assert rec.multivalue == any_multi
