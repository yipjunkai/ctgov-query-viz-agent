"""Client behaviour — paging, count, and cache — with the network mocked."""

from pathlib import Path
from typing import Any

import httpx
import respx

from ctgov_agent.ctgov.client import CtgovClient, ResponseCache

_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


def _study(nct: str) -> dict[str, Any]:
    return {"protocolSection": {"identificationModule": {"nctId": nct}}}


async def test_search_pages_until_no_next_token() -> None:
    page1 = {"studies": [_study("NCT1")], "nextPageToken": "tok2"}
    page2 = {"studies": [_study("NCT2")]}  # no nextPageToken -> stop
    with respx.mock:
        route = respx.get(_STUDIES_URL).mock(
            side_effect=[httpx.Response(200, json=page1), httpx.Response(200, json=page2)]
        )
        client = CtgovClient()
        studies = await client.search({"query.cond": "x"}, fields=("NCTId",))
        await client.aclose()
    ncts = [s["protocolSection"]["identificationModule"]["nctId"] for s in studies]
    assert ncts == ["NCT1", "NCT2"]
    assert route.call_count == 2


async def test_count_reads_total_count() -> None:
    with respx.mock:
        respx.get(_STUDIES_URL).mock(
            return_value=httpx.Response(200, json={"totalCount": 3736, "studies": []})
        )
        client = CtgovClient()
        total = await client.count({"query.cond": "melanoma"})
        await client.aclose()
    assert total == 3736


async def test_cache_avoids_second_request(tmp_path: Path) -> None:
    with respx.mock:
        route = respx.get(_STUDIES_URL).mock(
            return_value=httpx.Response(200, json={"totalCount": 5, "studies": []})
        )
        client = CtgovClient(cache=ResponseCache(tmp_path))
        first = await client.count({"query.cond": "x"})
        second = await client.count({"query.cond": "x"})  # identical params -> cache hit
        await client.aclose()
    assert first == second == 5
    assert route.call_count == 1
