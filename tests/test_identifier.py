from __future__ import annotations

from taxonfinder.models import CandidateGroup, Occurrence, TaxonMatch, TaxonomyInfo
from taxonfinder.resolvers.identifier import DefaultIdentificationResolver


def _group(lemmatized: str, normalized: str) -> CandidateGroup:
    return CandidateGroup(
        normalized=normalized,
        lemmatized=lemmatized,
        method="gazetteer",
        confidence=1.0,
        occurrences=[Occurrence(1, normalized, normalized)],
        gazetteer_taxon_ids=[],
        skip_resolution=False,
    )


def _match(**kwargs) -> TaxonMatch:
    taxonomy = TaxonomyInfo(genus="Tilia")
    return TaxonMatch(
        taxon_id=1,
        taxon_name=kwargs.get("taxon_name", "Tilia"),
        taxon_rank="genus",
        taxonomy=taxonomy,
        taxon_common_name_en=kwargs.get("taxon_common_name_en"),
        taxon_common_name_loc=kwargs.get("taxon_common_name_loc"),
        taxon_matched_name=kwargs.get("taxon_matched_name", "липа"),
        taxon_url="https://www.inaturalist.org/taxa/1",
        score=1.0,
        taxon_names=kwargs.get("taxon_names", []),
    )


def test_identifier_match_by_common_name() -> None:
    resolver = DefaultIdentificationResolver()
    group = _group("липа", "липа")
    matches = [_match(taxon_common_name_loc="Липа")]

    identified, reason = resolver.resolve(group, matches)

    assert identified is True
    assert reason == ""


def test_identifier_no_matches() -> None:
    resolver = DefaultIdentificationResolver()
    group = _group("липа", "липа")

    identified, reason = resolver.resolve(group, [])

    assert identified is False
    assert reason == "No matches in iNaturalist"


def test_identifier_multiple_candidates() -> None:
    resolver = DefaultIdentificationResolver()
    group = _group("липа", "липа")
    matches = [
        _match(taxon_common_name_loc="Береза", taxon_matched_name="береза"),
        _match(taxon_common_name_loc="Дуб", taxon_matched_name="дуб"),
    ]

    identified, reason = resolver.resolve(group, matches)

    assert identified is False
    assert reason == "Multiple candidate taxa found"


def test_identifier_common_name_not_matched() -> None:
    resolver = DefaultIdentificationResolver()
    group = _group("липа", "липа")
    matches = [_match(taxon_common_name_loc="Береза", taxon_matched_name="береза")]

    identified, reason = resolver.resolve(group, matches)

    assert identified is False
    assert reason == "Common name not matched"


def test_identifier_match_by_taxon_names() -> None:
    resolver = DefaultIdentificationResolver()
    group = _group("липа", "липа")
    matches = [_match(taxon_names=["Липа"])]

    identified, reason = resolver.resolve(group, matches)

    assert identified is True
    assert reason == ""
