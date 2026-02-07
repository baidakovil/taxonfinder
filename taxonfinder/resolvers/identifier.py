from __future__ import annotations

from ..models import CandidateGroup, TaxonMatch
from ..normalizer import normalize


class DefaultIdentificationResolver:
    def resolve(self, group: CandidateGroup, matches: list[TaxonMatch]) -> tuple[bool, str]:
        if not matches:
            return False, "No matches in iNaturalist"

        normalized = group.normalized
        lemmatized = group.lemmatized

        for match in matches:
            if _match_name(normalized, lemmatized, match):
                return True, ""

        if len(matches) > 1:
            return False, "Multiple candidate taxa found"

        return False, "Common name not matched"


def _match_name(normalized: str, lemmatized: str, match: TaxonMatch) -> bool:
    candidates = _match_candidates(match)
    return normalized in candidates or lemmatized in candidates


def _match_candidates(match: TaxonMatch) -> set[str]:
    values = [
        match.taxon_matched_name,
        match.taxon_name,
        match.taxon_common_name_en or "",
        match.taxon_common_name_loc or "",
    ]
    values.extend(match.taxon_names)
    return {normalize(value) for value in values if value}


__all__ = ["DefaultIdentificationResolver"]
