from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class GazetteerNameMappings:
    normalized: dict[str, list[int]]
    lemmatized: dict[str, list[int]]


@dataclass(slots=True)
class GazetteerTaxonRecord:
    taxon_id: int
    taxon_name: str
    taxon_rank: str
    ancestry: str | None
    taxon_common_name_en: str | None
    taxon_common_name_loc: str | None


class GazetteerStorage:
    def __init__(
        self,
        path: Path,
        *,
        schema_version: int = 1,
        validate_schema: bool = True,
    ) -> None:
        self._path = path
        self._schema_version = schema_version
        if validate_schema:
            self._validate_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _validate_schema(self) -> None:
        with self._connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version != self._schema_version:
                raise ValueError(
                    "Gazetteer schema version mismatch: expected "
                    f"{self._schema_version}, got {version}"
                )

    def load_name_mappings(self, locale: str) -> GazetteerNameMappings:
        normalized: dict[str, list[int]] = {}
        lemmatized: dict[str, list[int]] = {}

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT taxon_id, name_normalized, name_lemmatized
                FROM common_names
                WHERE locale = ?
                """,
                (locale,),
            ).fetchall()

        for row in rows:
            taxon_id = int(row["taxon_id"])
            name_normalized = row["name_normalized"]
            name_lemmatized = row["name_lemmatized"]

            if name_normalized:
                normalized.setdefault(name_normalized, []).append(taxon_id)
            if name_lemmatized:
                lemmatized.setdefault(name_lemmatized, []).append(taxon_id)

        return GazetteerNameMappings(normalized=normalized, lemmatized=lemmatized)

    def get_taxon_ids(self, name_normalized: str, locale: str) -> list[int]:
        """Get list of taxon IDs for a normalized name in given locale."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT taxon_id
                FROM common_names
                WHERE name_normalized = ? AND locale = ?
                """,
                (name_normalized, locale),
            ).fetchall()
        return [int(row["taxon_id"]) for row in rows]

    def get_full_record(self, taxon_id: int, locale: str) -> GazetteerTaxonRecord | None:
        """Get full taxon record with preferred common names for skip_resolution."""

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT taxon_id, taxon_name, taxon_rank, ancestry
                FROM taxa
                WHERE taxon_id = ?
                """,
                (taxon_id,),
            ).fetchone()

            if row is None:
                return None

            names = conn.execute(
                """
                SELECT name, locale, is_preferred
                FROM common_names
                WHERE taxon_id = ? AND locale IN (?, 'en')
                """,
                (taxon_id, locale),
            ).fetchall()

        common_en = _preferred_name(names, "en")
        common_loc = _preferred_name(names, locale)

        return GazetteerTaxonRecord(
            taxon_id=int(row["taxon_id"]),
            taxon_name=str(row["taxon_name"]),
            taxon_rank=str(row["taxon_rank"]),
            ancestry=row["ancestry"],
            taxon_common_name_en=common_en,
            taxon_common_name_loc=common_loc,
        )


def _preferred_name(rows: list[sqlite3.Row], locale: str) -> str | None:
    preferred: str | None = None
    fallback: str | None = None
    for row in rows:
        if row["locale"] != locale:
            continue
        if row["is_preferred"]:
            preferred = row["name"]
            break
        if fallback is None:
            fallback = row["name"]
    return preferred or fallback


__all__ = ["GazetteerStorage", "GazetteerNameMappings", "GazetteerTaxonRecord"]
