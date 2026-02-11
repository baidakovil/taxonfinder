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


def test_load_config_llm_disabled_no_fields_required(tmp_path: Path) -> None:
    """Test that disabled LLM configs don't require provider/model fields."""
    payload = {
        "confidence": 0.6,
        "locale": "ru",
        "llm_extractor": {
            "enabled": False
        },
        "llm_enricher": {
            "enabled": False
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    config = load_config(path)

    assert isinstance(config, Config)
    assert config.llm_extractor is not None
    assert config.llm_extractor.enabled is False
    assert config.llm_enricher is not None
    assert config.llm_enricher.enabled is False


def test_load_config_llm_enabled_requires_fields(tmp_path: Path) -> None:
    """Test that enabled LLM configs require provider and model fields."""
    payload = {
        "confidence": 0.6,
        "locale": "ru",
        "llm_extractor": {
            "enabled": True
            # Missing provider and model
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="provider.*model"):
        load_config(path)
