from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .models import Candidate, CandidateGroup, Occurrence


_METHOD_PRIORITY = {"gazetteer": 3, "latin_regex": 2, "llm": 1}


def merge_candidates(
    candidates: list[Candidate],
    *,
    skip_resolution_check: Callable[[Candidate], bool] | None = None,
) -> list[CandidateGroup]:
    best_candidates = _select_best_overlaps(candidates)
    groups: list[CandidateGroup] = []
    grouped: dict[str, list[_GroupBuilder]] = {}

    for candidate in best_candidates:
        builders = grouped.setdefault(candidate.lemmatized, [])
        placed = False
        for builder in builders:
            if _can_merge(candidate.gazetteer_taxon_ids, builder.gazetteer_taxon_ids):
                builder.add(candidate)
                placed = True
                break
        if not placed:
            new_builder = _GroupBuilder.from_candidate(candidate)
            builders.append(new_builder)

    for builders in grouped.values():
        for builder in builders:
            skip_resolution = False
            if skip_resolution_check is not None:
                skip_resolution = any(skip_resolution_check(c) for c in builder.members)
            groups.append(builder.build(skip_resolution))

    return groups


def _select_best_overlaps(candidates: list[Candidate]) -> list[Candidate]:
    if not candidates:
        return []

    ordered = sorted(candidates, key=lambda c: (c.start_char, c.end_char))
    groups: list[list[Candidate]] = []
    current: list[Candidate] = [ordered[0]]
    current_end = ordered[0].end_char

    for cand in ordered[1:]:
        if cand.start_char <= current_end:
            current.append(cand)
            current_end = max(current_end, cand.end_char)
        else:
            groups.append(current)
            current = [cand]
            current_end = cand.end_char
    groups.append(current)

    return [_select_best(group) for group in groups]


def _select_best(candidates: list[Candidate]) -> Candidate:
    def score(candidate: Candidate) -> tuple[float, int, int]:
        return (
            candidate.confidence,
            _METHOD_PRIORITY.get(candidate.method, 0),
            candidate.end_char - candidate.start_char,
        )

    return max(candidates, key=score)


def _can_merge(ids_a: list[int], ids_b: list[int]) -> bool:
    if not ids_a or not ids_b:
        return True
    return bool(set(ids_a).intersection(ids_b))


@dataclass(slots=True)
class _GroupBuilder:
    lemmatized: str
    normalized: str
    method: str
    confidence: float
    gazetteer_taxon_ids: list[int]
    occurrences: list[Occurrence] = field(default_factory=list)
    members: list[Candidate] = field(default_factory=list)

    @classmethod
    def from_candidate(cls, candidate: Candidate) -> _GroupBuilder:
        return cls(
            lemmatized=candidate.lemmatized,
            normalized=candidate.normalized,
            method=candidate.method,
            confidence=candidate.confidence,
            gazetteer_taxon_ids=list(candidate.gazetteer_taxon_ids),
            occurrences=[candidate.to_occurrence()],
            members=[candidate],
        )

    def add(self, candidate: Candidate) -> None:
        self.occurrences.append(candidate.to_occurrence())
        self.members.append(candidate)
        self.gazetteer_taxon_ids = _merge_taxon_ids(
            self.gazetteer_taxon_ids,
            candidate.gazetteer_taxon_ids,
        )

        if _select_best([candidate, self._representative()]) is candidate:
            self.normalized = candidate.normalized
            self.method = candidate.method
            self.confidence = candidate.confidence

    def _representative(self) -> Candidate:
        return Candidate(
            source_text="",
            source_context="",
            line_number=0,
            start_char=0,
            end_char=0,
            normalized=self.normalized,
            lemmatized=self.lemmatized,
            method=self.method,
            confidence=self.confidence,
            gazetteer_taxon_ids=list(self.gazetteer_taxon_ids),
        )

    def build(self, skip_resolution: bool) -> CandidateGroup:
        return CandidateGroup(
            normalized=self.normalized,
            lemmatized=self.lemmatized,
            method=self.method,
            confidence=self.confidence,
            occurrences=list(self.occurrences),
            gazetteer_taxon_ids=list(self.gazetteer_taxon_ids),
            skip_resolution=skip_resolution,
        )


def _merge_taxon_ids(ids_a: list[int], ids_b: list[int]) -> list[int]:
    if not ids_a:
        return list(ids_b)
    if not ids_b:
        return list(ids_a)
    return sorted(set(ids_a).union(ids_b))


__all__ = ["merge_candidates"]
