from __future__ import annotations

from pathlib import Path

from .base import TextLoader
from .plain_text import PlainTextLoader

_LOADERS: list[TextLoader] = [PlainTextLoader()]


def load_text(path: Path, *, max_file_size_mb: float = 2.0) -> str:
    for loader in _LOADERS:
        if loader.supports(path):
            return loader.load(path, max_file_size_mb=max_file_size_mb)

    raise ValueError(f"Unsupported file format: {path.suffix}")


__all__ = ["TextLoader", "PlainTextLoader", "load_text"]
