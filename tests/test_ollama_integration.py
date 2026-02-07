from __future__ import annotations

import os

import httpx
import pytest

from taxonfinder.extractors.llm_client import OllamaClient
from taxonfinder.extractors.llm_enricher import LlmEnricherConfig, LlmEnricherPhase
from taxonfinder.extractors.llm_extractor import LlmExtractorConfig, LlmExtractorPhase
from taxonfinder.models import CandidateGroup, Occurrence


def _ollama_settings() -> tuple[str, str]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    return base_url, model


def _require_ollama(base_url: str) -> None:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=2.0)
    except httpx.HTTPError:
        pytest.skip("Ollama server is not reachable")
    if response.status_code >= 400:
        pytest.skip("Ollama server responded with error")


@pytest.mark.ollama
def test_ollama_client_returns_json() -> None:
    base_url, model = _ollama_settings()
    _require_ollama(base_url)

    client = OllamaClient(
        base_url=base_url,
        model=model,
        timeout=60,
        http=httpx.Client(),
    )

    system_prompt = "You must respond with JSON only."
    user_content = 'Return ONLY JSON: {"candidates": []}'
    text = client.complete(system_prompt, user_content)

    assert text.strip()
    assert "candidates" in text


@pytest.mark.ollama
def test_ollama_extractor_real_model() -> None:
    base_url, model = _ollama_settings()
    _require_ollama(base_url)

    config = LlmExtractorConfig(
        provider="ollama",
        model=model,
        prompt_file="prompts/llm_extractor.txt",
        timeout=60,
        chunk_strategy="paragraph",
        min_chunk_words=1,
        max_chunk_words=50,
    )
    client = OllamaClient(
        base_url=base_url,
        model=model,
        timeout=60,
        http=httpx.Client(),
    )
    extractor = LlmExtractorPhase(config, locale="ru", llm_client=client)

    candidates = extractor.extract("We saw Tilia cordata in the forest.")

    assert isinstance(candidates, list)
    for candidate in candidates:
        assert candidate.method == "llm"


@pytest.mark.ollama
def test_ollama_enricher_real_model() -> None:
    base_url, model = _ollama_settings()
    _require_ollama(base_url)

    config = LlmEnricherConfig(
        provider="ollama",
        model=model,
        prompt_file="prompts/llm_enricher.txt",
        timeout=60,
    )
    client = OllamaClient(
        base_url=base_url,
        model=model,
        timeout=60,
        http=httpx.Client(),
    )
    enricher = LlmEnricherPhase(config, locale="ru", llm_client=client)

    group = CandidateGroup(
        normalized="липа",
        lemmatized="липа",
        method="llm",
        confidence=0.5,
        occurrences=[Occurrence(1, "липа", "Липа росла у дороги.")],
        gazetteer_taxon_ids=[],
        skip_resolution=False,
    )
    response = enricher.enrich("Липа росла у дороги.", group)

    assert isinstance(response.common_names_loc, list)
    assert isinstance(response.common_names_en, list)
    assert isinstance(response.latin_names, list)
