"""Refresh the controlled-vocabulary snapshot from the live API.

Run manually: ``python -m ctgov_agent.tools.refresh_vocab``. Re-pulls ``/stats/field/values`` and
rewrites ``vocab/snapshot.json`` so the committed golden witness stays in sync with the source
system. ``test_vocab.py`` then tells us whether the Python enums need updating to match.
"""

import json

import httpx

from ctgov_agent.vocab.controlled import (
    SNAPSHOT_FIELDS,
    SNAPSHOT_PATH,
    STATS_FIELD_VALUES_URL,
)


def main() -> None:
    resp = httpx.get(
        STATS_FIELD_VALUES_URL,
        params={"fields": ",".join(SNAPSHOT_FIELDS)},
        timeout=30.0,
    )
    resp.raise_for_status()
    data: object = resp.json()
    SNAPSHOT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {SNAPSHOT_PATH}")


if __name__ == "__main__":
    main()
