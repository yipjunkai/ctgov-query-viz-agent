"""The controlled-vocab enums must exactly mirror the API's own reported value sets."""

from ctgov_agent.vocab.controlled import (
    SNAPSHOT_PIECE,
    Status,
    humanize,
    load_snapshot,
)


def test_enums_mirror_api_snapshot() -> None:
    by_piece = {
        field["piece"]: {v["value"] for v in field["topValues"]} for field in load_snapshot()
    }
    for enum_cls, piece in SNAPSHOT_PIECE.items():
        assert {member.value for member in enum_cls} == by_piece[piece], (
            f"{enum_cls.__name__} has drifted from the API vocabulary for '{piece}'"
        )


def test_status_has_expected_size() -> None:
    # Guards against a silent partial-enum regression independent of the snapshot comparison.
    assert len(Status) == 14


def test_humanize_generic_and_overrides() -> None:
    assert humanize("PHASE2") == "Phase 2"  # override
    assert humanize("RECRUITING") == "Recruiting"  # generic title-case
    assert humanize("DIAGNOSTIC_TEST") == "Diagnostic Test"  # generic, underscores
    assert humanize("NIH") == "NIH"  # override preserves acronym
