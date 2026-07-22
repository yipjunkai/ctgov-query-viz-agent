"""Deterministic "is this chart actually informative?" advisories, surfaced in ``meta``.

These never change a number or refuse a query — they flag *degenerate-but-valid* visualizations so a
reader is not misled by a technically-correct yet uninformative chart: a distribution that is really
one bar, one value that dwarfs the rest, or a comparison series with almost nothing in it. The rules
are deterministic (no LLM); ``docs/EVAL.md`` names an offline chart-fitness judge as the richer,
future version of this.
"""

from ctgov_agent.engine.aggregate import Bucket

# One value holding at least this share of the total makes the "distribution" barely a distribution.
DOMINANT_FRACTION = 0.9
# A comparison arm with at most this many trials is too thin to read anything into.
SPARSE_SERIES_MAX = 2


def distribution_advisories(buckets: list[Bucket], noun: str) -> list[str]:
    """Flag a single-value or highly-concentrated categorical/geographic distribution."""
    total = sum(bucket.count for bucket in buckets)
    if len(buckets) == 1:
        return [
            f"Only one {noun} value is present, so this is effectively a single data point rather "
            f"than a distribution."
        ]
    if total > 0:
        top = max(buckets, key=lambda bucket: bucket.count)
        fraction = top.count / total
        if fraction >= DOMINANT_FRACTION:
            return [
                f"{top.label} accounts for {fraction:.0%} of the total — a highly concentrated "
                f"{noun} distribution."
            ]
    return []


def time_trend_advisories(buckets: list[Bucket]) -> list[str]:
    """Flag a 'trend' that is really a single year of data."""
    populated = [bucket for bucket in buckets if bucket.count > 0]
    if len(populated) == 1:
        return [f"Only {populated[0].key} has any trials, so there is no trend to read."]
    return []


def comparison_advisories(series_results: list[tuple[str, list[Bucket]]]) -> list[str]:
    """Flag any comparison arm too sparse to compare against the others."""
    notes: list[str] = []
    for label, buckets in series_results:
        count = sum(bucket.count for bucket in buckets)
        if count <= SPARSE_SERIES_MAX:
            notes.append(
                f"The '{label}' series has {count} trial(s) — too few to compare meaningfully."
            )
    return notes
