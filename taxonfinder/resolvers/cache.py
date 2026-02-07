from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DiskCacheConfig:
    path: Path
    ttl_days: int = 7
    schema_version: int = 1


class DiskCache:
    def __init__(self, config: DiskCacheConfig) -> None:
        self._config = config
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._config.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        self._config.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, self._config.schema_version):
                raise ValueError(
                    "Cache schema version mismatch: expected "
                    f"{self._config.schema_version}, got {version}"
                )
            if version == 0:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS api_cache (
                        query TEXT NOT NULL,
                        locale TEXT NOT NULL,
                        response_json TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        PRIMARY KEY (query, locale)
                    );
                    """
                )
                conn.execute(f"PRAGMA user_version = {self._config.schema_version}")

    def get(self, query: str, locale: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT response_json, created_at
                FROM api_cache
                WHERE query = ? AND locale = ?
                """,
                (query, locale),
            ).fetchone()
            if row is None:
                return None

            created_at = datetime.fromisoformat(row["created_at"])
            if datetime.utcnow() - created_at > timedelta(days=self._config.ttl_days):
                conn.execute(
                    "DELETE FROM api_cache WHERE query = ? AND locale = ?",
                    (query, locale),
                )
                return None

            return json.loads(row["response_json"])

    def put(self, query: str, locale: str, response: dict[str, Any]) -> None:
        payload = json.dumps(response, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO api_cache (query, locale, response_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (query, locale, payload, datetime.utcnow().isoformat()),
            )


__all__ = ["DiskCache", "DiskCacheConfig"]
