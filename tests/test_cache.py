from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from taxonfinder.resolvers.cache import DiskCache, DiskCacheConfig


def test_disk_cache_put_get(tmp_path: Path) -> None:
    cache = DiskCache(DiskCacheConfig(path=tmp_path / "cache.db", ttl_days=7))
    payload = {"results": [{"id": 1}]}

    cache.put("липа", "ru", payload)
    loaded = cache.get("липа", "ru")

    assert loaded == payload


def test_disk_cache_expires_entries(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    cache = DiskCache(DiskCacheConfig(path=path, ttl_days=1))
    payload = {"results": []}
    cache.put("query", "ru", payload)

    expired = datetime.utcnow() - timedelta(days=2)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE api_cache SET created_at = ? WHERE query = ? AND locale = ?",
            (expired.isoformat(), "query", "ru"),
        )

    assert cache.get("query", "ru") is None


def test_disk_cache_schema_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 2")
    with pytest.raises(ValueError):
        DiskCache(DiskCacheConfig(path=path, ttl_days=7))
