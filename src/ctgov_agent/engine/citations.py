"""Deep citations: link each visualized datum back to the source trial records.

Because the engine computes every number from real records, each datum already knows which trials
produced it. A citation carries the ``nct_id``, the ``field`` the evidence came from, and an
``excerpt`` that is the *exact* field value — which means it is a verifiable substring of the source
record. ``tests/property/test_citations_invariant.py`` enforces exactly that: no excerpt may be
anything the source record doesn't actually contain. That is the anti-hallucination guarantee made
concrete and testable.

We cap citations per datum (a heavy bucket can have thousands of members); the datum's ``value`` is
the true total, the citations are a traceable sample.
"""

from ctgov_agent.api.schemas import Citation
from ctgov_agent.engine.aggregate import Bucket
from ctgov_agent.engine.network import GraphEdge

CITATIONS_PER_DATUM = 3


def bucket_citations(bucket: Bucket, field: str, *, use_start_date: bool = False) -> list[Citation]:
    """Citations for a categorical/temporal datum.

    The excerpt is the exact value that placed the record in this bucket — the bucket key itself
    (e.g. ``"PHASE3"``, ``"United States"``), or the record's raw start date for time buckets.
    """
    citations: list[Citation] = []
    for record in bucket.members[:CITATIONS_PER_DATUM]:
        excerpt = record.start_date if use_start_date else bucket.key
        if excerpt is None:
            continue
        citations.append(Citation(nct_id=record.nct_id, excerpt=excerpt, field=field))
    return citations


def edge_citations(edge: GraphEdge) -> list[Citation]:
    """Citations for a network edge: the trials in which the two entities co-occur."""
    citations: list[Citation] = []
    for record in edge.members[:CITATIONS_PER_DATUM]:
        if record.brief_title:
            citations.append(
                Citation(nct_id=record.nct_id, excerpt=record.brief_title, field="brief_title")
            )
        else:
            citations.append(Citation(nct_id=record.nct_id, excerpt=record.nct_id, field="nct_id"))
    return citations
