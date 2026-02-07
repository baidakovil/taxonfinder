from __future__ import annotations

from typing import Protocol

from ..models import CandidateGroup, TaxonMatch


class TaxonSearcher(Protocol):
    def search(self, query: str, locale: str) -> list[TaxonMatch]:
        ...


class IdentificationResolver(Protocol):
    def resolve(self, group: CandidateGroup, matches: list[TaxonMatch]) -> tuple[bool, str]:
        ...
