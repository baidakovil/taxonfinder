from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol


class MorphAnalyzer(Protocol):
    def parse(self, word: str) -> Iterable[object]: ...


_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def lemmatize(text: str, morph: MorphAnalyzer | None) -> str:
    tokens = _TOKEN_RE.findall(text)
    lemmas: list[str] = []
    for token in tokens:
        if _CYRILLIC_RE.search(token) and morph is not None:
            parsed = next(iter(morph.parse(token)), None)
            lemma = getattr(parsed, "normal_form", token)
            lemmas.append(normalize(lemma))
        else:
            lemmas.append(token.lower())
    return " ".join(lemmas)


def search_variants(text: str, morph: MorphAnalyzer | None) -> list[str]:
    original = text.lower()
    normalized = normalize(text)
    lemmatized = lemmatize(text, morph)
    lemmatized_normalized = normalize(lemmatized)

    variants: list[str] = []
    for value in (original, normalized, lemmatized, lemmatized_normalized):
        if value and value not in variants:
            variants.append(value)
    return variants
