from __future__ import annotations

import json

from taxonfinder.extractors.llm_enricher import LlmEnricherConfig, LlmEnricherPhase, SentenceSpan
from taxonfinder.models import CandidateGroup, Occurrence


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

    def complete(self, system_prompt: str, user_content: str, *, response_schema=None) -> str:
        return self.response_text


def _group(name: str, context: str) -> CandidateGroup:
    return CandidateGroup(
        normalized=name,
        lemmatized=name,
        method="llm",
        confidence=0.5,
        occurrences=[Occurrence(1, name, context)],
        gazetteer_taxon_ids=[],
        skip_resolution=False,
    )


def test_llm_enricher_builds_expanded_context() -> None:
    text = "First sentence. Target appears here. Last sentence."
    spans = [
        SentenceSpan(0, 16, "First sentence."),
        SentenceSpan(17, 38, "Target appears here."),
        SentenceSpan(39, 53, "Last sentence."),
    ]
    config = LlmEnricherConfig(
        provider="ollama",
        model="test",
        prompt_file="prompts/llm_enricher.txt",
        timeout=10,
    )
    llm = FakeLlmClient(
        {"common_names_loc": ["foo"], "common_names_en": [], "latin_names": []}
    )

    enricher = LlmEnricherPhase(config, locale="ru", llm_client=llm)
    response = enricher.enrich(text, _group("target", "Target appears here."), sentences=spans)

    assert response.common_names_loc == ["foo"]
    assert llm.calls
    _, user_content = llm.calls[0]
    assert "Candidate: target" in user_content
    assert "First sentence. Target appears here. Last sentence." in user_content


def test_llm_enricher_skips_invalid_json() -> None:
    text = "Only one sentence."
    config = LlmEnricherConfig(
        provider="ollama",
        model="test",
        prompt_file="prompts/llm_enricher.txt",
        timeout=10,
    )
    llm = FakeRawLlmClient("not-json")

    enricher = LlmEnricherPhase(config, locale="ru", llm_client=llm, max_retries=0)
    response = enricher.enrich(text, _group("candidate", "Only one sentence."))

    assert response.common_names_loc == []
    assert response.common_names_en == []
    assert response.latin_names == []
