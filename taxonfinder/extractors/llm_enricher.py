from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import structlog

from ..models import CandidateGroup, LlmEnrichmentResponse
from ..normalizer import normalize
from .llm_client import LlmClient, LlmError


@dataclass(slots=True)
class LlmEnricherConfig:
    provider: str
    model: str
    prompt_file: str
    timeout: float


@dataclass(slots=True)
class SentenceSpan:
    start: int
    end: int
    text: str


class LlmEnricherPhase:
    def __init__(
        self,
        config: LlmEnricherConfig,
        *,
        locale: str,
        llm_client: LlmClient,
        sentence_splitter: Callable[[str], list[str]] | None = None,
        max_retries: int = 2,
    ) -> None:
        self._config = config
        self._locale = locale
        self._llm_client = llm_client
        self._sentence_splitter = sentence_splitter
        self._max_retries = max_retries
        self._system_prompt = _load_prompt(Path(config.prompt_file), locale)
        self._logger = structlog.get_logger()

    def enrich(
        self,
        text: str,
        group: CandidateGroup,
        *,
        sentences: Sequence[SentenceSpan] | None = None,
    ) -> LlmEnrichmentResponse:
        candidate = group.normalized
        occurrence = group.occurrences[0] if group.occurrences else None
        start, end = _find_span(text, occurrence.source_text if occurrence else candidate)

        spans = list(sentences) if sentences else None
        if spans is None and self._sentence_splitter is not None:
            spans = _build_spans(text, self._sentence_splitter(text))

        context = _expanded_context(text, start, end, spans, occurrence)
        user_content = f"Candidate: {candidate}\nContext: {context}"
        response = self._call_llm(user_content)
        return _parse_response(response, candidate)

    def _call_llm(self, user_content: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                raw = self._llm_client.complete(
                    self._system_prompt,
                    user_content,
                    response_schema=_response_schema(),
                )
                return _parse_json(raw)
            except (LlmError, json.JSONDecodeError) as exc:
                last_error = exc
                self._logger.warning(
                    "llm_enricher_invalid_json",
                    attempt=attempt + 1,
                    error=str(exc),
                )
        self._logger.warning("llm_enricher_request_skipped", error=str(last_error))
        return {}


def _load_prompt(path: Path, locale: str) -> str:
    content = path.read_text(encoding="utf-8")
    return content.replace("{{locale}}", locale)


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "common_names_loc": {"type": "array", "items": {"type": "string"}},
            "common_names_en": {"type": "array", "items": {"type": "string"}},
            "latin_names": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["common_names_loc", "common_names_en", "latin_names"],
    }


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = _strip_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        return json.loads(cleaned)


def _strip_fences(text: str) -> str:
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = text.strip().removesuffix("```")
    return text.strip()


def _parse_response(data: dict[str, Any], candidate: str) -> LlmEnrichmentResponse:
    return LlmEnrichmentResponse(
        common_names_loc=_filter_names(data.get("common_names_loc"), candidate),
        common_names_en=_filter_names(data.get("common_names_en"), None),
        latin_names=_filter_names(data.get("latin_names"), None),
    )


def _filter_names(value: Any, candidate: str | None) -> list[str]:
    if not isinstance(value, list):
        return []
    filtered: list[str] = []
    candidate_norm = normalize(candidate) if candidate else None
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name:
            continue
        if candidate_norm and normalize(name) == candidate_norm:
            continue
        if name not in filtered:
            filtered.append(name)
    return filtered


def _expanded_context(
    text: str,
    start: int,
    end: int,
    spans: Sequence[SentenceSpan] | None,
    occurrence,
) -> str:
    if spans:
        index = _sentence_index(spans, start, end)
        if index is not None:
            parts: list[str] = []
            for offset in (-1, 0, 1):
                idx = index + offset
                if 0 <= idx < len(spans):
                    parts.append(spans[idx].text)
            return " ".join(parts)

    if occurrence is not None and occurrence.source_context:
        return occurrence.source_context

    return _line_context(text, start)


def _sentence_index(spans: Sequence[SentenceSpan], start: int, end: int) -> int | None:
    for index, span in enumerate(spans):
        if span.start <= start < span.end or span.start < end <= span.end:
            return index
    return None


def _build_spans(text: str, sentences: list[str]) -> list[SentenceSpan]:
    spans: list[SentenceSpan] = []
    cursor = 0
    for sentence in sentences:
        if not sentence:
            continue
        start = text.find(sentence, cursor)
        if start == -1:
            continue
        end = start + len(sentence)
        spans.append(SentenceSpan(start=start, end=end, text=sentence))
        cursor = end
    return spans


def _find_span(text: str, needle: str) -> tuple[int, int]:
    index = text.find(needle)
    if index == -1:
        index = text.lower().find(needle.lower())
    if index == -1:
        return 0, len(needle)
    return index, index + len(needle)


def _line_context(text: str, start: int) -> str:
    line_start = text.rfind("\n", 0, start)
    line_end = text.find("\n", start)
    if line_start == -1:
        line_start = 0
    else:
        line_start += 1
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end]


__all__ = ["LlmEnricherConfig", "LlmEnricherPhase", "SentenceSpan"]
