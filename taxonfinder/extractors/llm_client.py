from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class LlmError(RuntimeError):
    pass


class LlmClient(Protocol):
    def complete(
        self,
        system_prompt: str,
        user_content: str,
        *,
        response_schema: dict | None = None,
    ) -> str:
        ...


@dataclass(slots=True)
class OllamaClient:
    base_url: str
    model: str
    timeout: float
    http: httpx.Client
    user_agent: str = "TaxonFinder/0.1.0"

    def complete(
        self,
        system_prompt: str,
        user_content: str,
        *,
        response_schema: dict | None = None,
    ) -> str:
        url = f"{self.base_url.rstrip('/')}/api/generate"
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": user_content,
            "system": system_prompt,
            "stream": False,
        }
        if response_schema is not None:
            payload["format"] = "json"

        response = self.http.post(
            url,
            json=payload,
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise LlmError(f"Ollama request failed: {response.status_code} {response.text}")

        data = response.json()
        if "response" not in data:
            raise LlmError("Ollama response missing 'response' field")
        return str(data["response"])


@dataclass(slots=True)
class OpenAIClient:
    base_url: str
    model: str
    timeout: float
    api_key: str
    http: httpx.Client
    user_agent: str = "TaxonFinder/0.1.0"

    def complete(
        self,
        system_prompt: str,
        user_content: str,
        *,
        response_schema: dict | None = None,
    ) -> str:
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": self.user_agent,
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
        }
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": response_schema,
                    "strict": True,
                },
            }

        response = self.http.post(url, headers=headers, json=payload, timeout=self.timeout)
        if response.status_code >= 400:
            raise LlmError(f"OpenAI request failed: {response.status_code} {response.text}")

        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError("OpenAI response missing content") from exc


@dataclass(slots=True)
class AnthropicClient:
    base_url: str
    model: str
    timeout: float
    api_key: str
    http: httpx.Client
    user_agent: str = "TaxonFinder/0.1.0"

    def complete(
        self,
        system_prompt: str,
        user_content: str,
        *,
        response_schema: dict | None = None,
    ) -> str:
        url = f"{self.base_url.rstrip('/')}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": self.user_agent,
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
            "max_tokens": 1024,
        }
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": response_schema,
            }

        response = self.http.post(url, headers=headers, json=payload, timeout=self.timeout)
        if response.status_code >= 400:
            raise LlmError(f"Anthropic request failed: {response.status_code} {response.text}")

        data = response.json()
        try:
            return data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError("Anthropic response missing content") from exc


def load_json(text: str) -> dict[str, Any]:
    return json.loads(text)


__all__ = [
    "AnthropicClient",
    "LlmClient",
    "LlmError",
    "OllamaClient",
    "OpenAIClient",
    "load_json",
]
