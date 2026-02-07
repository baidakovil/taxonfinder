from __future__ import annotations

from collections.abc import Iterable

from taxonfinder.normalizer import lemmatize, normalize, search_variants


class FakeParse:
    def __init__(self, normal_form: str) -> None:
        self.normal_form = normal_form


class FakeMorph:
    def parse(self, word: str) -> Iterable[FakeParse]:
        mapping = {
            "липой": "липа",
            "липы": "липа",
        }
        return [FakeParse(mapping.get(word, word))]


def test_normalize_replaces_yo() -> None:
    assert normalize("Ёлка") == "елка"


def test_lemmatize_russian_tokens() -> None:
    morph = FakeMorph()
    assert lemmatize("липой", morph) == "липа"


def test_lemmatize_latin_tokens() -> None:
    assert lemmatize("Tilia cordata", None) == "tilia cordata"


def test_search_variants_unique() -> None:
    morph = FakeMorph()
    variants = search_variants("липы", morph)

    assert "липы" in variants
    assert "липа" in variants
    assert len(variants) == len(set(variants))
