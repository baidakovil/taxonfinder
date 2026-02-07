from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import spacy

from taxonfinder.config import InaturalistConfig
from taxonfinder.extractors import GazetteerExtractor
from taxonfinder.extractors.latin import LatinRegexExtractor, SentenceSpan
from taxonfinder.extractors.llm_extractor import LlmExtractorConfig, LlmExtractorPhase
from taxonfinder.gazetteer.storage import GazetteerStorage
from taxonfinder.loaders import load_text
from taxonfinder.merge import merge_candidates
from taxonfinder.resolvers.identifier import DefaultIdentificationResolver
from taxonfinder.resolvers.inaturalist import INaturalistSearcher


class FakeLlmClient:
    def __init__(self, response: dict) -> None:
        self.response = response

    def complete(self, system_prompt: str, user_content: str, *, response_schema=None) -> str:
        return json.dumps(self.response)


def _create_db(path: Path, rows: list[tuple[int, str, str, str, str]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 1")
        conn.executescript(
            """
            CREATE TABLE taxa (
                taxon_id INTEGER PRIMARY KEY,
                taxon_name TEXT NOT NULL,
                taxon_rank TEXT NOT NULL,
                ancestry TEXT
            );
            CREATE TABLE common_names (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                taxon_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                name_normalized TEXT NOT NULL,
                name_lemmatized TEXT,
                locale TEXT NOT NULL,
                is_preferred BOOLEAN DEFAULT 0,
                lexicon TEXT
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO common_names (taxon_id, name, name_normalized, name_lemmatized, locale)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )


def _sentence_spans(doc) -> list[SentenceSpan]:
    return [SentenceSpan(sent.start_char, sent.end_char, sent.text) for sent in doc.sents]


def test_pipeline_like_integration_identifies_candidates(tmp_path: Path) -> None:
    text = "Липа растет. Мы видели Tilia cordata. Встречалась ель."
    path = tmp_path / "input.txt"
    path.write_text(text, encoding="utf-8")
    loaded = load_text(path, max_file_size_mb=1.0)

    db_path = tmp_path / "gazetteer.db"
    _create_db(db_path, [(1, "липа", "липа", "липа", "ru")])
    storage = GazetteerStorage(db_path)

    nlp = spacy.blank("ru")
    nlp.add_pipe("sentencizer")
    doc = nlp(loaded)

    gazetteer = GazetteerExtractor(storage, locale="ru", nlp=nlp, morph=None)
    gazetteer_candidates = gazetteer.extract(doc)

    latin = LatinRegexExtractor(is_known_name=lambda name: name == "tilia cordata")
    latin_candidates = latin.extract(loaded, sentences=_sentence_spans(doc))

    llm_config = LlmExtractorConfig(
        provider="ollama",
        model="test",
        prompt_file="prompts/llm_extractor.txt",
        timeout=10,
        chunk_strategy="paragraph",
        min_chunk_words=1,
        max_chunk_words=50,
    )
    llm_client = FakeLlmClient(
        {"candidates": [{"name": "ель", "context": "Встречалась ель."}]}
    )
    llm = LlmExtractorPhase(llm_config, locale="ru", llm_client=llm_client)
    llm_candidates = llm.extract(loaded)

    candidates = gazetteer_candidates + latin_candidates + llm_candidates
    groups = merge_candidates(candidates, skip_resolution_check=lambda c: c.method == "gazetteer")

    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("User-Agent") == "TaxonFinder/0.1.0"
        query = request.url.params.get("q")
        queries.append(query)
        if query == "ель":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": 100,
                            "name": "Picea",
                            "rank": "genus",
                            "matched_name": "ель",
                            "preferred_common_name": {"name": "Ель"},
                            "names": [{"name": "Ель", "locale": "ru"}],
                        }
                    ]
                },
            )
        if query == "tilia cordata":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": 101,
                            "name": "Tilia cordata",
                            "rank": "species",
                            "matched_name": "Tilia cordata",
                            "names": [{"name": "Tilia cordata", "locale": "la"}],
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    searcher = INaturalistSearcher(http=http, config=InaturalistConfig())
    identifier = DefaultIdentificationResolver()

    results: dict[str, bool] = {}
    for group in groups:
        if group.skip_resolution:
            results[group.lemmatized] = True
            continue
        matches = searcher.search(group.normalized, locale="ru")
        identified, reason = identifier.resolve(group, matches)
        results[group.lemmatized] = identified
        assert reason == ""

    assert results["липа"] is True
    assert results["tilia cordata"] is True
    assert results["ель"] is True
    assert set(queries) == {"tilia cordata", "ель"}


def test_pipeline_like_integration_unidentified_no_matches(tmp_path: Path) -> None:
    text = "В тексте упоминается зверь."
    path = tmp_path / "input.txt"
    path.write_text(text, encoding="utf-8")
    loaded = load_text(path, max_file_size_mb=1.0)

    llm_config = LlmExtractorConfig(
        provider="ollama",
        model="test",
        prompt_file="prompts/llm_extractor.txt",
        timeout=10,
        chunk_strategy="paragraph",
        min_chunk_words=1,
        max_chunk_words=50,
    )
    llm_client = FakeLlmClient(
        {"candidates": [{"name": "зверь", "context": "В тексте упоминается зверь."}]}
    )
    llm = LlmExtractorPhase(llm_config, locale="ru", llm_client=llm_client)
    candidates = llm.extract(loaded)

    groups = merge_candidates(candidates)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    searcher = INaturalistSearcher(http=http, config=InaturalistConfig())
    identifier = DefaultIdentificationResolver()

    matches = searcher.search(groups[0].normalized, locale="ru")
    identified, reason = identifier.resolve(groups[0], matches)

    assert identified is False
    assert reason == "No matches in iNaturalist"
