from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from ..models import Candidate
from ..normalizer import lemmatize, normalize

_STOP_PHRASES = {
    "et cetera",
    "ad libitum",
    "in situ",
    "ex vivo",
    "de facto",
    "pro rata",
    "per se",
    "ab initio",
    "status quo",
    "modus operandi",
    "alma mater",
    "anno domini",
}

_TITLES = {"mr", "dr", "prof", "von", "van"}

_PATTERN = re.compile(r"\b[A-Z][a-z]+ [a-z]{2,}(?: [a-z]{2,})?\b")


@dataclass(slots=True)
class SentenceSpan:
    start: int
    end: int
    text: str


class LatinRegexExtractor:
    def __init__(
        self,
        *,
        morph: object | None = None,
        is_known_name: Callable[[str], bool] | None = None,
        stop_phrases: Iterable[str] | None = None,
    ) -> None:
        self._morph = morph
        self._is_known_name = is_known_name
        self._stop_phrases = {phrase.lower() for phrase in (stop_phrases or _STOP_PHRASES)}

    def extract(
        self,
        text: str,
        *,
        sentences: Sequence[SentenceSpan] | None = None,
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        for match in _PATTERN.finditer(text):
            source_text = match.group(0)
            lower = source_text.lower()
            if not _passes_length_filter(source_text):
                continue
            if lower in self._stop_phrases:
                continue
            if _has_person_title(text, match.start()):
                continue

            known = False
            if self._is_known_name is not None:
                known = self._is_known_name(lower)

            confidence = 0.9 if known else 0.7
            source_context = _find_context(text, match.start(), sentences)
            line_number = _line_number(text, match.start())

            candidates.append(
                Candidate(
                    source_text=source_text,
                    source_context=source_context,
                    line_number=line_number,
                    start_char=match.start(),
                    end_char=match.end(),
                    normalized=normalize(source_text),
                    lemmatized=lemmatize(source_text, self._morph),
                    method="latin_regex",
                    confidence=confidence,
                    gazetteer_taxon_ids=[],
                )
            )

        return candidates


def _passes_length_filter(source_text: str) -> bool:
    words = source_text.split()
    return all(len(word) >= 3 for word in words)


def _has_person_title(text: str, start: int) -> bool:
    prefix = text[:start].rstrip()
    match = re.search(r"(\b\w+)[\s\.]+$", prefix)
    if not match:
        return False
    return match.group(1).lower() in _TITLES


def _find_context(text: str, start: int, sentences: Sequence[SentenceSpan] | None) -> str:
    if sentences:
        for sentence in sentences:
            if sentence.start <= start < sentence.end:
                return sentence.text
    return _line_context(text, start)


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


__all__ = ["LatinRegexExtractor", "SentenceSpan"]
