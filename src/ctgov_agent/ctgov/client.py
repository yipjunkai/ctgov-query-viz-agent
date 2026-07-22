"""Async client for the ClinicalTrials.gov v2 ``/studies`` endpoint.

Two operations back the whole engine:

* :meth:`CtgovClient.count` — a cheap ``countTotal`` used as the pre-flight for the too-broad
  guardrail (refuse rather than aggregate a set too large to count exactly).
* :meth:`CtgovClient.search` — page through *all* matching studies (``pageToken`` at
  ``pageSize=1000``), projecting only the fields we need.

An optional on-disk :class:`ResponseCache` makes example runs reproducible and keeps us from
hammering a public API during tests and demos. Filtered aggregation is client-side by necessity:
the API's ``/stats/field/values`` facets are global-only (they reject a query filter), so counts
for a *filtered* question must be computed from the real records we page here.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import httpx

DEFAULT_BASE_URL = "https://clinicaltrials.gov/api/v2"
MAX_PAGE_SIZE = 1000
# Hard backstop on paging. The too-broad guardrail refuses long before this; it only guards against
# a runaway loop if that check is ever bypassed.
DEFAULT_MAX_RECORDS = 15000

# Field projection covering every dimension the engine aggregates on. Verified against the live API.
DEFAULT_FIELDS: tuple[str, ...] = (
    "NCTId",
    "BriefTitle",
    "Phase",
    "StudyType",
    "OverallStatus",
    "StartDate",
    "LeadSponsorName",
    "LeadSponsorClass",
    "InterventionType",
    "InterventionName",
    "LocationCountry",
)


class ResponseCache:
    """Content-addressed on-disk cache of raw API responses."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        return cast("dict[str, Any]", json.loads(path.read_text()))

    def put(self, key: str, value: Mapping[str, Any]) -> None:
        self._path(key).write_text(json.dumps(value, sort_keys=True))


def _cache_key(path: str, params: Mapping[str, Any]) -> str:
    blob = path + "?" + json.dumps(dict(sorted(params.items())), sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


class CtgovClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        http_client: httpx.AsyncClient | None = None,
        cache: ResponseCache | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = http_client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = http_client is None
        self._cache = cache

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        key = _cache_key(path, params)
        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
        resp = await self._client.get(f"{self._base_url}{path}", params=dict(params))
        resp.raise_for_status()
        data = cast("dict[str, Any]", resp.json())
        if self._cache is not None:
            self._cache.put(key, data)
        return data

    async def count(self, query_params: Mapping[str, str]) -> int:
        """Total number of studies matching ``query_params`` (cheap; no record bodies)."""
        params = {**query_params, "countTotal": "true", "pageSize": "1", "fields": "NCTId"}
        data = await self._get("/studies", params)
        total = data.get("totalCount")
        return total if isinstance(total, int) else 0

    async def search(
        self,
        query_params: Mapping[str, str],
        fields: Sequence[str] = DEFAULT_FIELDS,
        *,
        max_records: int = DEFAULT_MAX_RECORDS,
    ) -> list[dict[str, Any]]:
        """Page through all matching studies (bounded by ``max_records``), projecting ``fields``."""
        page_size = min(MAX_PAGE_SIZE, max_records)
        collected: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, str] = {
                **query_params,
                "pageSize": str(page_size),
                "fields": ",".join(fields),
            }
            if page_token is not None:
                params["pageToken"] = page_token
            data = await self._get("/studies", params)
            batch = data.get("studies")
            if isinstance(batch, list):
                for item in cast("list[Any]", batch):
                    if isinstance(item, dict):
                        collected.append(cast("dict[str, Any]", item))
            token = data.get("nextPageToken")
            page_token = token if isinstance(token, str) else None
            if page_token is None or len(collected) >= max_records:
                break
        return collected
