from __future__ import annotations

from pathlib import Path

import pytest

from taxonfinder.loaders import load_text
from taxonfinder.loaders.plain_text import PlainTextLoader


def test_plain_text_loader_reads_utf8(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("Привет", encoding="utf-8")

    text = load_text(path, max_file_size_mb=1.0)

    assert text == "Привет"


def test_plain_text_loader_detects_encoding(tmp_path: Path) -> None:
    path = tmp_path / "legacy.txt"
    data = "тест".encode("cp1251")
    path.write_bytes(data)

    loader = PlainTextLoader()
    text = loader.load(path, max_file_size_mb=1.0)

    assert "тест" == text


def test_plain_text_loader_detects_koi8r(tmp_path: Path) -> None:
    path = tmp_path / "legacy_koi8.txt"
    data = "тест".encode("koi8-r")
    path.write_bytes(data)

    loader = PlainTextLoader()
    text = loader.load(path, max_file_size_mb=1.0)

    assert "тест" == text


def test_plain_text_loader_rejects_large_file(tmp_path: Path) -> None:
    path = tmp_path / "large.txt"
    path.write_bytes(b"a" * 1024)

    with pytest.raises(ValueError, match="Input file exceeds maximum size"):
        load_text(path, max_file_size_mb=0.0001)


def test_load_text_rejects_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "sample.pdf"
    path.write_text("dummy", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported file format"):
        load_text(path, max_file_size_mb=1.0)
