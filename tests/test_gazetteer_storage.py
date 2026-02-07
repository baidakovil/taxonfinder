from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from taxonfinder.gazetteer.storage import GazetteerStorage


def _create_db(path: Path, *, version: int = 1) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(f"PRAGMA user_version = {int(version)}")
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
        conn.execute(
            """
            INSERT INTO taxa (taxon_id, taxon_name, taxon_rank, ancestry)
            VALUES (1, 'Tilia cordata', 'species', '{"kingdom": "Plantae"}')
            """
        )
        conn.execute(
            """
            INSERT INTO common_names (taxon_id, name, name_normalized, name_lemmatized, locale)
            VALUES (1, 'Tilia cordata', 'tilia cordata', 'tilia cordata', 'en')
            """
        )


def test_storage_loads_name_mappings(tmp_path: Path) -> None:
    db_path = tmp_path / "gazetteer.db"
    _create_db(db_path)

    storage = GazetteerStorage(db_path)
    mappings = storage.load_name_mappings("en")

    assert mappings.normalized["tilia cordata"] == [1]
    assert mappings.lemmatized["tilia cordata"] == [1]


def test_storage_rejects_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "gazetteer.db"
    _create_db(db_path, version=2)

    with pytest.raises(ValueError, match="schema version mismatch"):
        GazetteerStorage(db_path)


def test_storage_get_taxon_ids(tmp_path: Path) -> None:
    """Test get_taxon_ids returns list of taxon IDs for normalized name."""
    db_path = tmp_path / "gazetteer.db"
    _create_db(db_path)

    with sqlite3.connect(db_path) as conn:
        # Add another common name for same taxon
        conn.execute(
            """
            INSERT INTO common_names (taxon_id, name, name_normalized, name_lemmatized, locale)
            VALUES (1, 'Linden', 'linden', 'linden', 'en')
            """
        )
        # Add different taxon with same normalized name (ambiguous)
        conn.execute(
            """
            INSERT INTO common_names (taxon_id, name, name_normalized, name_lemmatized, locale)
            VALUES (2, 'Linden', 'linden', 'linden', 'en')
            """
        )

    storage = GazetteerStorage(db_path)
    # Single taxon ID
    ids = storage.get_taxon_ids("tilia cordata", "en")
    assert ids == [1]

    # Multiple taxon IDs (ambiguous name)
    ids = storage.get_taxon_ids("linden", "en")
    assert set(ids) == {1, 2}

    # Non-existent name
    ids = storage.get_taxon_ids("nonexistent", "en")
    assert ids == []


def test_storage_get_full_record(tmp_path: Path) -> None:
    """Test get_full_record returns complete taxon record with common names."""
    db_path = tmp_path / "gazetteer.db"
    _create_db(db_path)

    storage = GazetteerStorage(db_path)

    # Existing record
    record = storage.get_full_record(1, locale="ru")
    assert record is not None
    assert record.taxon_id == 1
    assert record.taxon_name == "Tilia cordata"
    assert record.taxon_rank == "species"
    assert record.ancestry == '{"kingdom": "Plantae"}'
    assert record.taxon_common_name_en == "Tilia cordata"
    assert record.taxon_common_name_loc is None

    # Non-existent record
    record = storage.get_full_record(999, locale="ru")
    assert record is None
