from __future__ import annotations

from ..models import CandidateGroup, TaxonMatch
from ..normalizer import lemmatize, normalize


class DefaultIdentificationResolver:
    def __init__(self, morph: object | None = None):
        self.morph = morph

    def resolve(self, group: CandidateGroup, matches: list[TaxonMatch]) -> tuple[bool, str]:
        if not matches:
            return False, "No matches in iNaturalist"

        normalized = group.normalized
        lemmatized = group.lemmatized

        for match in matches:
            if _match_name(normalized, lemmatized, match, self.morph):
                return True, ""

        if len(matches) > 1:
            return False, "Multiple candidate taxa found"

        return False, "Common name not matched"


def _match_name(
    normalized: str, lemmatized: str, match: TaxonMatch, morph: object | None
) -> bool:
    candidates = _match_candidates(match, morph)
    return normalized in candidates or lemmatized in candidates


def _match_candidates(match: TaxonMatch, morph: object | None) -> set[str]:
    values = [
        match.taxon_matched_name,
        match.taxon_name,
        match.taxon_common_name_en or "",
        match.taxon_common_name_loc or "",
    ]
    values.extend(match.taxon_names)

    candidates: set[str] = set()
    for value in values:
        if value:
            candidates.add(normalize(value))
            # Also add lemmatized form
            lemmatized_value = lemmatize(value, morph)
            candidates.add(lemmatized_value)

    return candidates


__all__ = ["DefaultIdentificationResolver"]
