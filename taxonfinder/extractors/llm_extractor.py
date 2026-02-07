from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import structlog

from ..models import Candidate
from ..normalizer import lemmatize, normalize
from .llm_client import LlmClient, LlmError


@dataclass(slots=True)
class LlmExtractorConfig:
    provider: str
    model: str
    prompt_file: str
    timeout: float
    chunk_strategy: str
    min_chunk_words: int
    max_chunk_words: int


class LlmExtractorPhase:
    def __init__(
        self,
        config: LlmExtractorConfig,
        *,
        locale: str,
        llm_client: LlmClient,
        morph: object | None = None,
        sentence_splitter: Callable[[str], list[str]] | None = None,
        max_retries: int = 2,
    ) -> None:
        self._config = config
        self._locale = locale
        self._llm_client = llm_client
        self._morph = morph
        self._sentence_splitter = sentence_splitter
        self._max_retries = max_retries
        self._system_prompt = _load_prompt(Path(config.prompt_file), locale)
        self._logger = structlog.get_logger()

    def extract(self, text: str) -> list[Candidate]:
        chunks = chunk_text(
            text,
            strategy=self._config.chunk_strategy,
            min_words=self._config.min_chunk_words,
            max_words=self._config.max_chunk_words,
            sentence_splitter=self._sentence_splitter,
        )
        candidates: list[Candidate] = []
        for chunk in chunks:
            response = self._call_llm(chunk)
            items = response.get("candidates", [])
            for item in items:
                name = str(item.get("name", "")).strip()
                context = str(item.get("context", "")).strip()
                if not name:
                    continue
                start_char, end_char = _find_span(text, name)
                line_number = _line_number(text, start_char)
                candidates.append(
                    Candidate(
                        source_text=name,
                        source_context=context or _line_context(text, start_char),
                        line_number=line_number,
                        start_char=start_char,
                        end_char=end_char,
                        normalized=normalize(name),
                        lemmatized=lemmatize(name, self._morph),
                        method="llm",
                        confidence=0.6,
                        gazetteer_taxon_ids=[],
                    )
                )
        return candidates

    def _call_llm(self, chunk: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                raw = self._llm_client.complete(
                    self._system_prompt,
                    chunk,
                    response_schema=_response_schema(),
                )
                return _parse_json(raw)
            except (LlmError, json.JSONDecodeError) as exc:
                last_error = exc
                self._logger.warning(
                    "llm_extractor_invalid_json",
                    attempt=attempt + 1,
                    error=str(exc),
                )
        self._logger.warning("llm_extractor_chunk_skipped", error=str(last_error))
        return {"candidates": []}


def _load_prompt(path: Path, locale: str) -> str:
    content = path.read_text(encoding="utf-8")
    return content.replace("{{locale}}", locale)


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


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "context": {"type": "string"},
                    },
                    "required": ["name", "context"],
                },
            }
        },
        "required": ["candidates"],
    }


def chunk_text(
    text: str,
    *,
    strategy: str,
    min_words: int,
    max_words: int,
    sentence_splitter: Callable[[str], list[str]] | None = None,
) -> list[str]:
    if strategy not in {"paragraph", "page"}:
        raise ValueError(f"Unknown chunk strategy: {strategy}")

    if strategy == "paragraph":
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[str] = []
        buffer: list[str] = []
        buffer_words = 0
        for paragraph in paragraphs:
            words = _word_count(paragraph)
            if words > max_words:
                if buffer:
                    chunks.append("\n\n".join(buffer))
                    buffer = []
                    buffer_words = 0
                if sentence_splitter is not None:
                    chunks.extend(_split_by_sentences(sentence_splitter(paragraph), max_words))
                else:
                    chunks.extend(_split_by_words(paragraph, max_words))
                continue

            if buffer_words < min_words:
                buffer.append(paragraph)
                buffer_words += words
                if buffer_words >= min_words:
                    chunks.append("\n\n".join(buffer))
                    buffer = []
                    buffer_words = 0
                continue

            chunks.append(paragraph)
        if buffer:
            chunks.append("\n\n".join(buffer))
        return chunks

    if sentence_splitter is not None:
        return _split_by_sentences(sentence_splitter(text), max_words)
    return _split_by_words(text, max_words)


def _split_by_words(text: str, max_words: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    for start in range(0, len(words), max_words):
        part = " ".join(words[start : start + max_words])
        chunks.append(part)
    return chunks


def _split_by_sentences(sentences: list[str], max_words: int) -> list[str]:
    chunks: list[str] = []
    buffer: list[str] = []
    buffer_words = 0
    for sentence in sentences:
        words = _word_count(sentence)
        if words > max_words:
            if buffer:
                chunks.append(" ".join(buffer))
                buffer = []
                buffer_words = 0
            chunks.extend(_sliding_window(sentence, max_words, 50))
            continue
        if buffer_words + words <= max_words:
            buffer.append(sentence)
            buffer_words += words
            continue
        chunks.append(" ".join(buffer))
        buffer = [sentence]
        buffer_words = words
    if buffer:
        chunks.append(" ".join(buffer))
    return chunks


def _sliding_window(text: str, max_words: int, overlap: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    step = max(max_words - overlap, 1)
    chunks: list[str] = []
    for start in range(0, len(words), step):
        part = " ".join(words[start : start + max_words])
        chunks.append(part)
        if start + max_words >= len(words):
            break
    return chunks


def _word_count(text: str) -> int:
    return len(text.split())


def _find_span(text: str, name: str) -> tuple[int, int]:
    index = text.find(name)
    if index == -1:
        index = text.lower().find(name.lower())
    if index == -1:
        return 0, len(name)
    return index, index + len(name)


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


def _line_number(text: str, start: int) -> int:
    return text.count("\n", 0, start) + 1


__all__ = ["LlmExtractorConfig", "LlmExtractorPhase", "chunk_text"]
