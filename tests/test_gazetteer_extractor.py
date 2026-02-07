from __future__ import annotations

import sqlite3
from pathlib import Path

import spacy

from taxonfinder.extractors import GazetteerExtractor
from taxonfinder.gazetteer.storage import GazetteerStorage


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


def test_gazetteer_extractor_finds_candidate(tmp_path: Path) -> None:
    db_path = tmp_path / "gazetteer.db"
    _create_db(
        db_path,
        [(1, "Tilia cordata", "tilia cordata", "tilia cordata", "en")],
    )
    storage = GazetteerStorage(db_path)
    nlp = spacy.blank("en")

    extractor = GazetteerExtractor(storage, locale="en", nlp=nlp, morph=None)
    doc = nlp("We saw Tilia cordata today.")

    candidates = extractor.extract(doc)

    assert len(candidates) == 1
    assert candidates[0].source_text == "Tilia cordata"
    assert candidates[0].method == "gazetteer"
    assert candidates[0].confidence == 1.0
    assert candidates[0].gazetteer_taxon_ids == [1]


def test_gazetteer_extractor_confidence_exact_match_multiple_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "gazetteer.db"
    _create_db(
        db_path,
        [
            (2, "липа", "липа", "липа", "ru"),
            (4, "липа", "липа", "липа", "ru"),
        ],
    )
    storage = GazetteerStorage(db_path)
    nlp = spacy.blank("ru")

    extractor = GazetteerExtractor(storage, locale="ru", nlp=nlp, morph=None)
    doc = nlp("липа")

    candidates = extractor.extract(doc)

    assert len(candidates) == 1
    assert candidates[0].confidence == 0.8


def test_gazetteer_extractor_confidence_lemma_match(tmp_path: Path) -> None:
    db_path = tmp_path / "gazetteer.db"
    _create_db(
        db_path,
        [(3, "липы", "липы", "липа", "ru")],
    )
    storage = GazetteerStorage(db_path)
    nlp = spacy.blank("ru")

    extractor = GazetteerExtractor(storage, locale="ru", nlp=nlp, morph=None)
    doc = nlp("липа")

    candidates = extractor.extract(doc)

    assert len(candidates) == 1
    assert candidates[0].confidence == 0.9
