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

        for attempt in range(self.config.max_retries + 1):
            if self.rate_limiter is not None:
                self.rate_limiter.acquire()

            response = self.http.get(
                url,
                params=params,
                headers={"User-Agent": self.user_agent},
                timeout=self.config.timeout,
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code in {429} or response.status_code >= 500:
                if attempt < self.config.max_retries:
                    _sleep_backoff(attempt)
                    continue

            raise httpx.HTTPStatusError(
                f"iNaturalist error: {response.status_code}",
                request=response.request,
                response=response,
            )

        return {"results": []}


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
        taxon_names = _extract_names(result.get("names"))

        matches.append(
            TaxonMatch(
                taxon_id=taxon_id,
                taxon_name=taxon_name,
                taxon_rank=taxon_rank,
                taxonomy=_taxonomy_from_result(result),
                taxon_common_name_en=_extract_common_name(result.get("preferred_common_name")),
                taxon_common_name_loc=_extract_locale_common_name(result, locale),
                taxon_matched_name=matched_name,
                taxon_url=str(taxon_url),
                score=score,
                taxon_names=taxon_names,
            )
        )
    return matches


def _extract_common_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("name")
    if isinstance(value, str):
        return value
    return None


def _extract_locale_common_name(result: dict[str, Any], locale: str) -> str | None:
    names = result.get("names") or []
    for item in names:
        if item.get("locale") == locale and item.get("name"):
            return item.get("name")
    return _extract_common_name(result.get("preferred_common_name"))


def _extract_names(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    return names


def _taxonomy_from_result(result: dict[str, Any]) -> TaxonomyInfo:
    taxonomy = TaxonomyInfo()

    for ancestor in result.get("ancestors", []) or []:
        rank = ancestor.get("rank")
        name = ancestor.get("name")
        _assign_rank(taxonomy, rank, name)

    _assign_rank(taxonomy, result.get("rank"), result.get("name"))
    return taxonomy


def _assign_rank(taxonomy: TaxonomyInfo, rank: str | None, name: str | None) -> None:
    if not rank or not name:
        return
    if rank == "kingdom":
        taxonomy.kingdom = name
    elif rank == "phylum":
        taxonomy.phylum = name
    elif rank == "class":
        taxonomy.class_ = name
    elif rank == "order":
        taxonomy.order = name
    elif rank == "family":
        taxonomy.family = name
    elif rank == "genus":
        taxonomy.genus = name
    elif rank == "species":
        taxonomy.species = name


__all__ = ["INaturalistSearcher"]
