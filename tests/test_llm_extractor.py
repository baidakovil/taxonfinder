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
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Locale: {{locale}}", encoding="utf-8")

    config = LlmExtractorConfig(
        provider="ollama",
        model="test",
        prompt_file=str(prompt_file),
        timeout=10,
        chunk_strategy="paragraph",
        min_chunk_words=1,
        max_chunk_words=10,
    )
    llm = FakeLlmClient({"candidates": []})

    extractor = LlmExtractorPhase(config, locale="ru", llm_client=llm)
    extractor.extract("text")

    assert llm.calls
    system_prompt, _ = llm.calls[0]
    assert system_prompt == "Locale: ru"


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


def test_llm_extractor_handles_multiple_occurrences() -> None:
    """Test that multiple occurrences of same name get different spans."""
    config = LlmExtractorConfig(
        provider="ollama",
        model="test",
        prompt_file="prompts/llm_extractor.txt",
        timeout=10,
        chunk_strategy="paragraph",
        min_chunk_words=1,
        max_chunk_words=50,
    )
    # LLM returns "берёза" three times
    llm = FakeLlmClient(
        {
            "candidates": [
                {"name": "берёза", "context": "первая берёза"},
                {"name": "берёза", "context": "вторая берёза"},
                {"name": "берёза", "context": "третья берёза"},
            ]
        }
    )

    extractor = LlmExtractorPhase(config, locale="ru", llm_client=llm)
    text = "Первая берёза росла у дома. Вторая берёза была выше. Третья берёза самая старая."
    candidates = extractor.extract(text)

    # All three candidates should be extracted
    assert len(candidates) == 3
    
    # Each should have different span (not all pointing to first occurrence)
    spans = [(c.start_char, c.end_char) for c in candidates]
    assert len(set(spans)) == 3, "All spans should be unique"
    
    # Verify they point to correct positions
    first_pos = text.find("берёза")
    second_pos = text.find("берёза", first_pos + 1)
    third_pos = text.find("берёза", second_pos + 1)
    
    assert (first_pos, first_pos + 6) in spans
    assert (second_pos, second_pos + 6) in spans
    assert (third_pos, third_pos + 6) in spans
