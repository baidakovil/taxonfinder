from __future__ import annotations

from taxonfinder.extractors.latin import LatinRegexExtractor, SentenceSpan


def test_latin_extractor_accepts_known_name() -> None:
    text = "We saw Tilia cordata."
    sentences = [SentenceSpan(0, len(text), text)]
    extractor = LatinRegexExtractor(is_known_name=lambda name: name == "tilia cordata")

    candidates = extractor.extract(text, sentences=sentences)

    assert len(candidates) == 1
    assert candidates[0].source_text == "Tilia cordata"
    assert candidates[0].confidence == 0.9
    assert candidates[0].source_context == text


def test_latin_extractor_filters_stop_phrase() -> None:
    text = "This is in situ and should be ignored."
    sentences = [SentenceSpan(0, len(text), text)]
    extractor = LatinRegexExtractor()

    candidates = extractor.extract(text, sentences=sentences)

    assert candidates == []


def test_latin_extractor_filters_short_words() -> None:
    text = "We saw Ab ca in the notes."
    sentences = [SentenceSpan(0, len(text), text)]
    extractor = LatinRegexExtractor()

    candidates = extractor.extract(text, sentences=sentences)

    assert candidates == []


def test_latin_extractor_filters_titles() -> None:
    text = "Mr. Tilia cordata visited yesterday."
    sentences = [SentenceSpan(0, len(text), text)]
    extractor = LatinRegexExtractor()

    candidates = extractor.extract(text, sentences=sentences)

    assert candidates == []


def test_latin_extractor_line_number() -> None:
    text = "Line one\nTilia cordata."
    sentences = [SentenceSpan(0, len(text), text)]
    extractor = LatinRegexExtractor()

    candidates = extractor.extract(text, sentences=sentences)

    tilia = [c for c in candidates if c.source_text == "Tilia cordata"][0]
    assert tilia.line_number == 2
    assert tilia.normalized == "tilia cordata"
    assert tilia.lemmatized == "tilia cordata"


def test_latin_extractor_ignores_lowercase() -> None:
    text = "We saw tilia cordata near the river."
    sentences = [SentenceSpan(0, len(text), text)]
    extractor = LatinRegexExtractor()

    candidates = extractor.extract(text, sentences=sentences)

    assert candidates == []
