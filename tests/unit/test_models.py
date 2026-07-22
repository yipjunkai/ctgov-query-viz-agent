"""Record parsing: correct on real data, and *total* on anything malformed."""

import json
from pathlib import Path
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from ctgov_agent.ctgov.models import StudyRecord, parse_study

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "ctgov_search_melanoma.json"


def _studies() -> list[dict[str, Any]]:
    return json.loads(_FIXTURE.read_text())["studies"]


def test_parse_real_study_extracts_fields() -> None:
    rec = parse_study(_studies()[0])
    assert rec.nct_id.startswith("NCT")
    assert rec.study_type == "INTERVENTIONAL"
    assert rec.phases  # non-empty tuple of raw phase tokens
    assert rec.start_year is not None and 1990 <= rec.start_year <= 2100
    assert rec.sponsor_class is not None
    # The raw projection is retained so a citation can prove its excerpt occurs in the source.
    assert rec.nct_id in json.dumps(rec.raw)


def test_parse_handles_missing_and_wrong_typed_fields() -> None:
    junk_inputs: list[dict[str, Any]] = [
        {},
        {"protocolSection": None},
        {"protocolSection": []},
        {"protocolSection": {"designModule": {"phases": "PHASE1"}}},  # phases should be a list
        {"protocolSection": {"armsInterventionsModule": {"interventions": "nope"}}},
    ]
    for junk in junk_inputs:
        rec = parse_study(junk)
        assert isinstance(rec, StudyRecord)
        assert rec.phases == ()
        assert rec.intervention_types == ()


# Recursive JSON-shaped values: the parser must be total over adversarial nesting.
_json_like = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(), children, max_size=4)
    ),
    max_leaves=25,
)


@given(st.dictionaries(st.text(), _json_like, max_size=6))
def test_parse_never_raises(data: dict[str, Any]) -> None:
    parse_study(data)  # totality: no input shape may raise
