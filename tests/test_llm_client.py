from __future__ import annotations

import httpx
import pytest

from taxonfinder.extractors.llm_client import LlmError, OllamaClient


def test_ollama_client_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("User-Agent") == "TaxonFinder/0.1.0"
        return httpx.Response(200, json={"response": "{\"candidates\": []}"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    ollama = OllamaClient(
        base_url="http://localhost:11434",
        model="llama3",
        timeout=10,
        http=client,
    )

    text = ollama.complete("system", "user")

    assert "candidates" in text


def test_ollama_client_raises_on_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="error")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    ollama = OllamaClient(
        base_url="http://localhost:11434",
        model="llama3",
        timeout=10,
        http=client,
    )

    with pytest.raises(LlmError):
        ollama.complete("system", "user")
