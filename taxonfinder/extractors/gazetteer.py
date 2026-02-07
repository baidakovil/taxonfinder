from __future__ import annotations

from dataclasses import dataclass, replace

from spacy.matcher import PhraseMatcher
from spacy.tokens import Doc

from ..gazetteer.storage import GazetteerNameMappings, GazetteerStorage
from ..models import Candidate
from ..normalizer import lemmatize, normalize


@dataclass(slots=True)
class GazetteerMatch:
    candidate: Candidate
    taxon_ids: list[int]


class GazetteerExtractor:
    def __init__(
        self,
        storage: GazetteerStorage,
        *,
        locale: str,
        nlp,
        morph: object | None = None,
    ) -> None:
        self._storage = storage
        self._locale = locale
        self._nlp = nlp
        self._morph = morph
        self._mappings = storage.load_name_mappings(locale)
        self._matcher = PhraseMatcher(self._nlp.vocab, attr="LOWER")
        self._register_patterns(self._mappings)

    def extract(self, doc: Doc) -> list[Candidate]:
        matches = self._matcher(doc)
        by_span: dict[tuple[int, int], GazetteerMatch] = {}

        for _, start, end in matches:
            span = doc[start:end]
            normalized = normalize(span.text)
            lemmatized = lemmatize(span.text, self._morph)

            taxon_ids, exact_match = _match_taxon_ids(self._mappings, normalized, lemmatized)
            if not taxon_ids:
                continue

            confidence = _confidence(exact_match, len(taxon_ids))
            source_context = _sentence_context(span, doc.text)
            line_number = _line_number(doc.text, span.start_char)

            candidate = Candidate(
                source_text=span.text,
                source_context=source_context,
                line_number=line_number,
                start_char=span.start_char,
                end_char=span.end_char,
                normalized=normalized,
                lemmatized=lemmatized,
                method="gazetteer",
                confidence=confidence,
                gazetteer_taxon_ids=list(taxon_ids),
            )

            key = (span.start_char, span.end_char)
            existing = by_span.get(key)
            if existing is None:
                by_span[key] = GazetteerMatch(candidate=candidate, taxon_ids=list(taxon_ids))
            else:
                merged_ids = sorted(set(existing.taxon_ids).union(taxon_ids))
                existing.taxon_ids = merged_ids
                if candidate.confidence > existing.candidate.confidence:
                    existing.candidate = replace(candidate, gazetteer_taxon_ids=merged_ids)
                else:
                    existing.candidate = replace(
                        existing.candidate,
                        gazetteer_taxon_ids=merged_ids,
                    )

        return [match.candidate for match in by_span.values()]

    def _register_patterns(self, mappings: GazetteerNameMappings) -> None:
        patterns: list[str] = list(mappings.normalized.keys()) + list(mappings.lemmatized.keys())
        unique = sorted(set(patterns))
        docs = [self._nlp.make_doc(name) for name in unique]
        if docs:
            self._matcher.add("gazetteer", docs)


def _match_taxon_ids(
    mappings: GazetteerNameMappings,
    normalized: str,
    lemmatized: str,
) -> tuple[list[int], bool]:
    if normalized in mappings.normalized:
        return mappings.normalized[normalized], True
    if lemmatized in mappings.lemmatized:
        return mappings.lemmatized[lemmatized], False
    return [], False


def _confidence(exact_match: bool, taxon_count: int) -> float:
    if exact_match:
        return 1.0 if taxon_count == 1 else 0.8
    return 0.9 if taxon_count == 1 else 0.7


def _line_context(text: str, start: int) -> str:
    line_start = text.rfind("\n", 0, start)
    line_end = text.find("\n", start)
    if line_start == -1:
        line_start = 0
    else:
        line_start += 1
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end]


def _line_number(text: str, start: int) -> int:
    return text.count("\n", 0, start) + 1


def _sentence_context(span, text: str) -> str:
    try:
        return span.sent.text
    except ValueError:
        return _line_context(text, span.start_char)


__all__ = ["GazetteerExtractor"]
