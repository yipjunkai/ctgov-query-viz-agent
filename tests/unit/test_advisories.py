"""Deterministic chart-quality advisories: single bar, one value dominating, a sparse series."""

from ctgov_agent.engine.advisories import (
    comparison_advisories,
    distribution_advisories,
    time_trend_advisories,
)
from ctgov_agent.engine.aggregate import Bucket


def _bucket(key: str, count: int) -> Bucket:
    # `total` carries the count directly, so no StudyRecord members are needed here.
    return Bucket(key=key, label=key, members=[], total=count)


def test_single_bucket_is_flagged() -> None:
    notes = distribution_advisories([_bucket("PHASE2", 500)], "phase")
    assert len(notes) == 1
    assert "single data point" in notes[0]


def test_dominant_bucket_is_flagged() -> None:
    buckets = [_bucket("PHASE2", 95), _bucket("PHASE3", 3), _bucket("PHASE1", 2)]
    notes = distribution_advisories(buckets, "phase")
    assert len(notes) == 1
    assert "95%" in notes[0] and "concentrated" in notes[0]


def test_balanced_distribution_has_no_advisory() -> None:
    buckets = [_bucket("PHASE2", 50), _bucket("PHASE3", 30), _bucket("PHASE1", 20)]
    assert distribution_advisories(buckets, "phase") == []


def test_single_year_trend_is_flagged() -> None:
    buckets = [_bucket("2020", 40), _bucket("2021", 0)]
    notes = time_trend_advisories(buckets)
    assert len(notes) == 1
    assert "2020" in notes[0] and "no trend" in notes[0]


def test_multi_year_trend_has_no_advisory() -> None:
    assert time_trend_advisories([_bucket("2019", 5), _bucket("2020", 8)]) == []


def test_sparse_comparison_series_is_flagged() -> None:
    series = [
        ("Pembrolizumab", [_bucket("PHASE2", 900)]),
        ("RareDrug", [_bucket("PHASE2", 1)]),
    ]
    notes = comparison_advisories(series)
    assert len(notes) == 1
    assert "RareDrug" in notes[0]


def test_healthy_comparison_has_no_advisory() -> None:
    series = [
        ("Nivolumab", [_bucket("PHASE2", 300), _bucket("PHASE3", 100)]),
        ("Pembrolizumab", [_bucket("PHASE2", 400), _bucket("PHASE3", 150)]),
    ]
    assert comparison_advisories(series) == []
