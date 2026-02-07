from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
from dotenv import load_dotenv


@dataclass
class InaturalistConfig:
    base_url: str = "https://api.inaturalist.org"
    timeout: float = 30
    rate_limit: float = 1.0
    burst_limit: int = 5
    max_retries: int = 3
    cache_enabled: bool = True
    cache_path: str = "cache/taxonfinder.db"
    cache_ttl_days: int = 7


@dataclass
class LlmExtractorConfig:
    enabled: bool = True
    provider: str = ""
    model: str = ""
    url: str | None = None
    timeout: float = 60
    prompt_file: str = "prompts/llm_extractor.txt"
    chunk_strategy: str = "paragraph"
    min_chunk_words: int = 50
    max_chunk_words: int = 500
    auto_start: bool = False
    auto_pull_model: bool = False
    stop_after_run: bool = False


@dataclass
class LlmEnricherConfig:
    enabled: bool = True
    provider: str = ""
    model: str = ""
    url: str | None = None
    timeout: float = 30
    prompt_file: str = "prompts/llm_enricher.txt"
    auto_start: bool = False
    auto_pull_model: bool = False
    stop_after_run: bool = False


@dataclass
class Config:
    confidence: float
    locale: str
    gazetteer_path: str = "data/gazetteer.db"
    spacy_model: str = "ru_core_news_md"
    max_file_size_mb: float = 2.0
    degraded_mode: bool = False
    user_agent: str = "TaxonFinder/0.1.0"
    inaturalist: InaturalistConfig = field(default_factory=InaturalistConfig)
    llm_extractor: LlmExtractorConfig | None = None
    llm_enricher: LlmEnricherConfig | None = None


def load_config(path: Path) -> Config:
    load_dotenv()

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    _validate_config(data)

    inaturalist = _load_inaturalist(data.get("inaturalist"))
    llm_extractor = _load_llm_extractor(data.get("llm_extractor"))
    llm_enricher = _load_llm_enricher(data.get("llm_enricher"))

    return Config(
        confidence=float(data["confidence"]),
        locale=str(data["locale"]),
        gazetteer_path=str(data.get("gazetteer_path", Config.gazetteer_path)),
        spacy_model=str(data.get("spacy_model", Config.spacy_model)),
        max_file_size_mb=float(data.get("max_file_size_mb", Config.max_file_size_mb)),
        degraded_mode=bool(data.get("degraded_mode", Config.degraded_mode)),
        user_agent=str(data.get("user_agent", Config.user_agent)),
        inaturalist=inaturalist,
        llm_extractor=llm_extractor,
        llm_enricher=llm_enricher,
    )


def _validate_config(data: dict) -> None:
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "config.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        messages = "; ".join(error.message for error in errors)
        raise ValueError(f"Invalid config: {messages}")


def _load_inaturalist(data: dict | None) -> InaturalistConfig:
    if not data:
        return InaturalistConfig()
    return InaturalistConfig(
        base_url=str(data.get("base_url", InaturalistConfig.base_url)),
        timeout=float(data.get("timeout", InaturalistConfig.timeout)),
        rate_limit=float(data.get("rate_limit", InaturalistConfig.rate_limit)),
        burst_limit=int(data.get("burst_limit", InaturalistConfig.burst_limit)),
        max_retries=int(data.get("max_retries", InaturalistConfig.max_retries)),
        cache_enabled=bool(data.get("cache_enabled", InaturalistConfig.cache_enabled)),
        cache_path=str(data.get("cache_path", InaturalistConfig.cache_path)),
        cache_ttl_days=int(data.get("cache_ttl_days", InaturalistConfig.cache_ttl_days)),
    )


def _require_llm_fields(data: dict, name: str) -> None:
    missing = [field for field in ("provider", "model") if not data.get(field)]
    if missing:
        raise ValueError(f"LLM config '{name}' missing fields: {', '.join(missing)}")


def _load_llm_extractor(data: dict | None) -> LlmExtractorConfig | None:
    if data is None:
        return None
    _require_llm_fields(data, "llm_extractor")
    return LlmExtractorConfig(
        enabled=bool(data.get("enabled", True)),
        provider=str(data.get("provider", "")),
        model=str(data.get("model", "")),
        url=data.get("url"),
        timeout=float(data.get("timeout", LlmExtractorConfig.timeout)),
        prompt_file=str(data.get("prompt_file", LlmExtractorConfig.prompt_file)),
        chunk_strategy=str(data.get("chunk_strategy", LlmExtractorConfig.chunk_strategy)),
        min_chunk_words=int(data.get("min_chunk_words", LlmExtractorConfig.min_chunk_words)),
        max_chunk_words=int(data.get("max_chunk_words", LlmExtractorConfig.max_chunk_words)),
        auto_start=bool(data.get("auto_start", LlmExtractorConfig.auto_start)),
        auto_pull_model=bool(data.get("auto_pull_model", LlmExtractorConfig.auto_pull_model)),
        stop_after_run=bool(data.get("stop_after_run", LlmExtractorConfig.stop_after_run)),
    )


def _load_llm_enricher(data: dict | None) -> LlmEnricherConfig | None:
    if data is None:
        return None
    _require_llm_fields(data, "llm_enricher")
    return LlmEnricherConfig(
        enabled=bool(data.get("enabled", True)),
        provider=str(data.get("provider", "")),
        model=str(data.get("model", "")),
        url=data.get("url"),
        timeout=float(data.get("timeout", LlmEnricherConfig.timeout)),
        prompt_file=str(data.get("prompt_file", LlmEnricherConfig.prompt_file)),
        auto_start=bool(data.get("auto_start", LlmEnricherConfig.auto_start)),
        auto_pull_model=bool(data.get("auto_pull_model", LlmEnricherConfig.auto_pull_model)),
        stop_after_run=bool(data.get("stop_after_run", LlmEnricherConfig.stop_after_run)),
    )
