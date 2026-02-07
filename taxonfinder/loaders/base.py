from __future__ import annotations

from pathlib import Path
from typing import Protocol


class TextLoader(Protocol):
    def supports(self, path: Path) -> bool:
        ...

    def load(self, path: Path, *, max_file_size_mb: float) -> str:
        ...
