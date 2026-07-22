"""Live smoke test against the real ClinicalTrials.gov API (run via `just e2e`).

Guards the field mappings the mocked unit tests can't: if the API renames a field or changes a
projected path, this fails where the mocks stay green.
"""

import pytest

from ctgov_agent.ctgov.client import CtgovClient
from ctgov_agent.ctgov.models import parse_study

pytestmark = pytest.mark.e2e


async def test_live_count_and_search_parse() -> None:
    client = CtgovClient()
    try:
        total = await client.count({"query.cond": "melanoma"})
        assert total > 100
        studies = await client.search({"query.cond": "melanoma"}, max_records=5)
    finally:
        await client.aclose()

    assert studies
    rec = parse_study(studies[0])
    assert rec.nct_id.startswith("NCT")
    assert rec.study_type in {"INTERVENTIONAL", "OBSERVATIONAL", "EXPANDED_ACCESS", None}
