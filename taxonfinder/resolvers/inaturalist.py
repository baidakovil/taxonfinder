from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import InaturalistConfig
from ..models import TaxonMatch, TaxonomyInfo
from .cache import DiskCache


@dataclass(slots=True)
class INaturalistSearcher:
    http: httpx.Client
    config: InaturalistConfig
    user_agent: str = "TaxonFinder/0.1.0"
    rate_limiter: object | None = None
    cache: DiskCache | None = None

    def search(self, query: str, locale: str) -> list[TaxonMatch]:
        cached = self.cache.get(query, locale) if self.cache else None
        if cached is not None:
            return _parse_matches(cached, locale, query)

        response_json = self._request(query, locale)
        if self.cache is not None:
            self.cache.put(query, locale, response_json)
        return _parse_matches(response_json, locale, query)

    def _request(self, query: str, locale: str) -> dict[str, Any]:
        params = {"q": query, "locale": locale}
        url = f"{self.config.base_url.rstrip('/')}/v1/taxa/autocomplete"
        last_response: httpx.Response | None = None
        for attempt in range(self.config.max_retries + 1):
            if self.rate_limiter is not None:
                self.rate_limiter.acquire()

            response = self.http.get(
                url,
                params=params,
                headers={"User-Agent": self.user_agent},
                timeout=self.config.timeout,
            )
            last_response = response

            if response.status_code == 200:
                return response.json()

            if response.status_code in {429} or response.status_code >= 500:
                if attempt < self.config.max_retries:
                    _sleep_backoff(attempt)
                    continue

            break

        # Exhausted retries or non-retryable error
        message = "iNaturalist error"
        if last_response is not None:
            raise httpx.HTTPStatusError(
                f"{message}: {last_response.status_code}",
                request=last_response.request,
                response=last_response,
            )
        raise httpx.HTTPError(message)


def _sleep_backoff(attempt: int) -> None:
    base_delay = 3 * (2**attempt)
    jitter = 0.5 + random.random() * 0.5
    time.sleep(base_delay * jitter)


def _parse_matches(data: dict[str, Any], locale: str, query: str) -> list[TaxonMatch]:
    results = data.get("results", [])
    matches: list[TaxonMatch] = []
    for result in results[:5]:
        taxon_id = int(result.get("id") or result.get("taxon_id") or 0)
        taxon_name = str(result.get("name", ""))
        taxon_rank = str(result.get("rank", ""))
        matched_name = str(result.get("matched_name") or result.get("matched_term") or query)
        taxon_url = result.get("uri") or f"https://www.inaturalist.org/taxa/{taxon_id}"
        score = float(result.get("score") or 0)
        names = result.get("names")
        taxon_names = _extract_names(names)

        matches.append(
            TaxonMatch(
                taxon_id=taxon_id,
                taxon_name=taxon_name,
                taxon_rank=taxon_rank,
                taxonomy=_taxonomy_from_result(result),
                taxon_common_name_en=_extract_common_name_en(result, names),
                taxon_common_name_loc=_extract_locale_common_name(names, locale),
                taxon_matched_name=matched_name,
                taxon_url=str(taxon_url),
                score=score,
                taxon_names=taxon_names,
            )
        )
    return matches

def _extract_common_name_en(result: dict[str, Any], names: Any) -> str | None:
    """Prefer an English common name regardless of request locale."""

    if isinstance(names, list):
        preferred: str | None = None
        fallback: str | None = None
        for item in names:
            if item.get("locale") != "en" or not item.get("name"):
                continue
            if item.get("is_preferred"):
                preferred = item["name"]
                break
            if fallback is None:
                fallback = item["name"]
        if preferred:
            return preferred
        if fallback:
            return fallback

    value = result.get("preferred_common_name")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):  # non-standard, but keep compatibility with tests
        return value.get("name")
    return None


def _extract_locale_common_name(names: Any, locale: str) -> str | None:
    if not isinstance(names, list):
        return None
    for item in names:
        if item.get("locale") == locale and item.get("name"):
            return item.get("name")
    return None


def _extract_names(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    return names


def _taxonomy_from_result(result: dict[str, Any]) -> TaxonomyInfo:
    fields: dict[str, str | None] = {
        "kingdom": None,
        "phylum": None,
        "class_": None,
        "order": None,
        "family": None,
        "genus": None,
        "species": None,
    }

    for ancestor in result.get("ancestors", []) or []:
        _assign_rank(fields, ancestor.get("rank"), ancestor.get("name"))

    _assign_rank(fields, result.get("rank"), result.get("name"))
    return TaxonomyInfo(**fields)


def _assign_rank(target: dict[str, str | None], rank: str | None, name: str | None) -> None:
    if not rank or not name:
        return
    key = "class_" if rank == "class" else rank
    if key in target:
        target[key] = name


__all__ = ["INaturalistSearcher"]
