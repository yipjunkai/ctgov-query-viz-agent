"""cannot_answer parsing defaults safely, so a malformed refusal still refuses cleanly."""

from ctgov_agent.planner.prompt import parse_cannot_answer


def test_malformed_json_defaults_to_out_of_domain() -> None:
    reason, explanation = parse_cannot_answer("not json at all")
    assert reason == "out_of_domain"
    assert explanation  # a non-empty default message


def test_invalid_reason_defaults_but_keeps_explanation() -> None:
    assert parse_cannot_answer('{"reason": "bogus", "explanation": "off topic"}') == (
        "out_of_domain",
        "off topic",
    )


def test_empty_explanation_gets_a_default() -> None:
    reason, explanation = parse_cannot_answer('{"reason": "ambiguous", "explanation": ""}')
    assert reason == "ambiguous"
    assert explanation


def test_valid_arguments_pass_through() -> None:
    assert parse_cannot_answer('{"reason": "ambiguous", "explanation": "which drug?"}') == (
        "ambiguous",
        "which drug?",
    )
