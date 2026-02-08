from __future__ import annotations

import json
from pathlib import Path

from taxonfinder.extractors.llm_extractor import LlmExtractorConfig, LlmExtractorPhase


class FakeLlmClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_content: str, *, response_schema=None) -> str:
        self.calls.append((system_prompt, user_content))
        return json.dumps(self.response)


class FakeRawLlmClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_content: str, *, response_schema=None) -> str:
        self.calls.append((system_prompt, user_content))
        return self.response_text


def test_llm_extractor_uses_prompt(tmp_path: Path) -> None:
    """Test that extractor loads locale-specific prompt file if available."""
    # Create base prompt
    base_prompt = tmp_path / "prompt.txt"
    base_prompt.write_text("Base prompt in English", encoding="utf-8")
    
    # Create locale-specific prompt
    ru_prompt = tmp_path / "prompt.ru.txt"
    ru_prompt.write_text("Промпт на русском", encoding="utf-8")

    config = LlmExtractorConfig(
        provider="ollama",
        model="test",
        prompt_file=str(base_prompt),
        timeout=10,
        chunk_strategy="paragraph",
        min_chunk_words=1,
        max_chunk_words=10,
    )
    llm = FakeLlmClient({"candidates": []})

    # Test with Russian locale - should use ru-specific prompt
    extractor_ru = LlmExtractorPhase(config, locale="ru", llm_client=llm)
    extractor_ru.extract("text")

    assert llm.calls
    system_prompt, _ = llm.calls[0]
    assert system_prompt == "Промпт на русском"
    
    # Test with English locale - should fall back to base prompt
    llm.calls.clear()
    extractor_en = LlmExtractorPhase(config, locale="en", llm_client=llm)
    extractor_en.extract("text")
    
    assert llm.calls
    system_prompt, _ = llm.calls[0]
    assert system_prompt == "Base prompt in English"


def test_llm_extractor_parses_candidates() -> None:
    config = LlmExtractorConfig(
        provider="ollama",
        model="test",
        prompt_file="prompts/llm_extractor.txt",
        timeout=10,
        chunk_strategy="paragraph",
        min_chunk_words=1,
        max_chunk_words=10,
    )
    llm = FakeLlmClient({"candidates": [{"name": "липа", "context": "Липа растет"}]})

    extractor = LlmExtractorPhase(config, locale="ru", llm_client=llm)
    candidates = extractor.extract("Липа растет в лесу.")

    assert len(candidates) == 1
    assert candidates[0].source_text == "липа"
    assert candidates[0].method == "llm"
    assert candidates[0].confidence == 0.6


def test_chunk_text_merges_small_paragraphs() -> None:
    config = LlmExtractorConfig(
        provider="ollama",
        model="test",
        prompt_file="prompts/llm_extractor.txt",
        timeout=10,
        chunk_strategy="paragraph",
        min_chunk_words=5,
        max_chunk_words=10,
    )
    llm = FakeLlmClient({"candidates": []})

    extractor = LlmExtractorPhase(config, locale="ru", llm_client=llm)
    extractor.extract("one two\n\nthree four five")

    assert len(llm.calls) == 1


def test_chunk_text_page_strategy_splits_by_words() -> None:
    config = LlmExtractorConfig(
        provider="ollama",
        model="test",
        prompt_file="prompts/llm_extractor.txt",
        timeout=10,
        chunk_strategy="page",
        min_chunk_words=1,
        max_chunk_words=5,
    )
    llm = FakeLlmClient({"candidates": []})

    extractor = LlmExtractorPhase(config, locale="ru", llm_client=llm)
    extractor.extract("one two three four five six seven")

    assert len(llm.calls) == 2


def test_llm_extractor_skips_invalid_json() -> None:
    config = LlmExtractorConfig(
        provider="ollama",
        model="test",
        prompt_file="prompts/llm_extractor.txt",
        timeout=10,
        chunk_strategy="page",
        min_chunk_words=1,
        max_chunk_words=5,
    )
    llm = FakeRawLlmClient("not-json")

    extractor = LlmExtractorPhase(config, locale="ru", llm_client=llm, max_retries=0)
    candidates = extractor.extract("one two three")

    assert candidates == []
    assert len(llm.calls) == 1


def test_chunk_text_uses_sentence_splitter() -> None:
    config = LlmExtractorConfig(
        provider="ollama",
        model="test",
        prompt_file="prompts/llm_extractor.txt",
        timeout=10,
        chunk_strategy="page",
        min_chunk_words=1,
        max_chunk_words=3,
    )
    llm = FakeLlmClient({"candidates": []})

    def split_sentences(_: str) -> list[str]:
        return ["one two three", "four five six"]

    extractor = LlmExtractorPhase(
        config,
        locale="ru",
        llm_client=llm,
        sentence_splitter=split_sentences,
    )
    extractor.extract("ignored")

    assert len(llm.calls) == 2
