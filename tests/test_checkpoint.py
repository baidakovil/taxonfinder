from __future__ import annotations

from pathlib import Path

from taxonfinder.checkpoint import FileCheckpoint
from taxonfinder.config import Config


def _config() -> Config:
    return Config(confidence=0.5, locale="ru")


def test_checkpoint_key_changes_with_text(tmp_path: Path) -> None:
    checkpoint = FileCheckpoint(tmp_path)
    key_a = checkpoint.key("text a", _config())
    key_b = checkpoint.key("text b", _config())

    assert key_a != key_b


def test_checkpoint_round_trip(tmp_path: Path) -> None:
    checkpoint = FileCheckpoint(tmp_path)
    key = checkpoint.key("text", _config())
    payload = {"stage": 1, "items": ["a", "b"]}

    path = checkpoint.save(key, payload)
    loaded = checkpoint.load(key)

    assert path.exists()
    assert loaded == payload


def test_checkpoint_clear(tmp_path: Path) -> None:
    checkpoint = FileCheckpoint(tmp_path)
    key = checkpoint.key("text", _config())

    checkpoint.save(key, {"done": True})
    checkpoint.clear(key)

    assert checkpoint.load(key) is None
