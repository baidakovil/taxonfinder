from __future__ import annotations

import json
from pathlib import Path

import pytest

from taxonfinder.config import Config, load_config


def test_load_config_valid(tmp_path: Path) -> None:
    payload = {
        "confidence": 0.6,
        "locale": "ru",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    config = load_config(path)

    assert isinstance(config, Config)
    assert config.confidence == 0.6
    assert config.locale == "ru"


def test_load_config_invalid(tmp_path: Path) -> None:
    payload = {
        "locale": "ru",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_config(path)
