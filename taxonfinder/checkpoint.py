from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import Config


class FileCheckpoint:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def key(self, text: str, config: Config) -> str:
        config_json = json.dumps(asdict(config), sort_keys=True, ensure_ascii=True)
        payload = f"{text}\n{config_json}".encode()
        return hashlib.sha256(payload).hexdigest()

    def save(self, key: str, data: dict[str, Any]) -> Path:
        path = self._path_for(key)
        path.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
        return path

    def load(self, key: str) -> dict[str, Any] | None:
        path = self._path_for(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def clear(self, key: str) -> None:
        path = self._path_for(key)
        if path.exists():
            path.unlink()

    def _path_for(self, key: str) -> Path:
        return self._base_dir / f"{key}.json"


__all__ = ["FileCheckpoint"]
