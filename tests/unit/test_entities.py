"""Drug entity resolution: brand / code / generic all map to one canonical, verified vs the API."""

from ctgov_agent.vocab.entities import resolve_drug


def test_brand_resolves_to_generic() -> None:
    entity = resolve_drug("Keytruda")
    assert entity is not None
    assert entity.canonical == "Pembrolizumab"


def test_development_code_resolves() -> None:
    entity = resolve_drug("MK-3475")
    assert entity is not None and entity.canonical == "Pembrolizumab"


def test_generic_resolves_to_itself_and_keeps_aliases() -> None:
    entity = resolve_drug("Pembrolizumab")
    assert entity is not None
    assert entity.canonical == "Pembrolizumab"
    assert "Keytruda" in entity.synonyms


def test_resolution_is_case_and_whitespace_insensitive() -> None:
    assert resolve_drug("  keytruda  ") == resolve_drug("Keytruda")


def test_unknown_drug_is_unresolved() -> None:
    assert resolve_drug("Aspirin") is None


def test_query_term_ors_the_union_of_names() -> None:
    entity = resolve_drug("Keytruda")
    assert entity is not None
    assert entity.query_term == "Pembrolizumab OR Keytruda OR MK-3475"
