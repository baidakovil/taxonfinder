from __future__ import annotations

from taxonfinder.merge import merge_candidates
from taxonfinder.models import Candidate


def _cand(
    *,
    start: int,
    end: int,
    method: str,
    confidence: float,
    lemma: str,
    normalized: str,
    ids: list[int] | None = None,
) -> Candidate:
    return Candidate(
        source_text="x",
        source_context="ctx",
        line_number=1,
        start_char=start,
        end_char=end,
        normalized=normalized,
        lemmatized=lemma,
        method=method,
        confidence=confidence,
        gazetteer_taxon_ids=ids or [],
    )


def test_merge_overlapping_prefers_confidence() -> None:
    candidates = [
        _cand(start=0, end=5, method="llm", confidence=0.6, lemma="a", normalized="a"),
        _cand(start=2, end=6, method="gazetteer", confidence=0.9, lemma="a", normalized="a"),
    ]

    groups = merge_candidates(candidates)

    assert len(groups) == 1
    assert groups[0].confidence == 0.9
    assert groups[0].method == "gazetteer"


def test_merge_overlapping_prefers_method_on_tie() -> None:
    candidates = [
        _cand(start=0, end=5, method="llm", confidence=0.8, lemma="a", normalized="a"),
        _cand(start=2, end=6, method="latin_regex", confidence=0.8, lemma="a", normalized="a"),
    ]

    groups = merge_candidates(candidates)

    assert len(groups) == 1
    assert groups[0].method == "latin_regex"


def test_merge_splits_disjoint_gazetteer_ids() -> None:
    candidates = [
        _cand(start=0, end=4, method="gazetteer", confidence=1.0, lemma="a", normalized="a", ids=[1]),
        _cand(start=6, end=10, method="gazetteer", confidence=1.0, lemma="a", normalized="a", ids=[2]),
    ]

    groups = merge_candidates(candidates)

    assert len(groups) == 2


def test_merge_allows_empty_gazetteer_ids() -> None:
    candidates = [
        _cand(start=0, end=4, method="gazetteer", confidence=1.0, lemma="a", normalized="a", ids=[1]),
        _cand(start=6, end=10, method="llm", confidence=0.6, lemma="a", normalized="a", ids=[]),
    ]

    groups = merge_candidates(candidates)

    assert len(groups) == 1


def test_merge_skip_resolution_flag() -> None:
    candidates = [
        _cand(start=0, end=4, method="gazetteer", confidence=1.0, lemma="a", normalized="a", ids=[1]),
    ]

    groups = merge_candidates(
        candidates,
        skip_resolution_check=lambda candidate: candidate.method == "gazetteer",
    )

    assert groups[0].skip_resolution is True


def test_merge_adjacent_spans_not_overlapping() -> None:
    """Test that adjacent spans (e.g., [0,5) and [5,10)) are treated as non-overlapping."""
    candidates = [
        _cand(start=0, end=5, method="gazetteer", confidence=1.0, lemma="a", normalized="a"),
        _cand(start=5, end=10, method="latin_regex", confidence=0.8, lemma="b", normalized="b"),
    ]

    groups = merge_candidates(candidates)

    # Adjacent spans should NOT overlap - both should be kept
    assert len(groups) == 2
    assert groups[0].method == "gazetteer"
    assert groups[1].method == "latin_regex"
