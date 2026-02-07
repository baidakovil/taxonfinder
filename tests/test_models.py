from __future__ import annotations

from taxonfinder.models import (
    LlmEnrichmentResponse,
    Occurrence,
    TaxonMatch,
    TaxonomyInfo,
    TaxonResult,
)


def test_taxonomy_to_dict_maps_class_field() -> None:
    taxonomy = TaxonomyInfo(
        kingdom="Plantae",
        phylum="Tracheophyta",
        class_="Magnoliopsida",
        order="Malvales",
        family="Malvaceae",
        genus="Tilia",
        species=None,
    )

    data = taxonomy.to_dict()

    assert "class" in data
    assert data["class"] == "Magnoliopsida"


def test_taxonomy_from_dict_maps_class_field() -> None:
    data = {
        "kingdom": "Plantae",
        "phylum": "Tracheophyta",
        "class": "Magnoliopsida",
        "order": "Malvales",
        "family": "Malvaceae",
        "genus": "Tilia",
        "species": None,
    }

    taxonomy = TaxonomyInfo.from_dict(data)

    assert taxonomy.class_ == "Magnoliopsida"


def test_occurrence_roundtrip() -> None:
    occ = Occurrence(line_number=3, source_text="липа", source_context="Липа растет.")

    payload = occ.to_dict()
    restored = Occurrence.from_dict(payload)

    assert restored == occ


def test_taxon_result_roundtrip() -> None:
    taxonomy = TaxonomyInfo(genus="Tilia")
    match = TaxonMatch(
        taxon_id=1,
        taxon_name="Tilia",
        taxon_rank="genus",
        taxonomy=taxonomy,
        taxon_common_name_en="Linden",
        taxon_common_name_loc="Липа",
        taxon_matched_name="липа",
        score=0.9,
        taxon_url="https://www.inaturalist.org/taxa/1",
    )
    result = TaxonResult(
        source_text="липа",
        identified=True,
        extraction_confidence=1.0,
        extraction_method="gazetteer",
        occurrences=[Occurrence(1, "липа", "Липа растет.")],
        matches=[match],
        llm_response=LlmEnrichmentResponse(
            common_names_loc=["липа"],
            common_names_en=["linden"],
            latin_names=["Tilia"],
        ),
        candidate_names=[],
        reason="",
    )

    payload = result.to_dict()
    restored = TaxonResult.from_dict(payload)

    assert restored.source_text == result.source_text
    assert restored.identified == result.identified
    assert restored.extraction_confidence == result.extraction_confidence
    assert restored.extraction_method == result.extraction_method
    assert restored.count == result.count
    assert restored.matches[0].taxon_name == result.matches[0].taxon_name
    assert restored.llm_response is not None
    assert restored.llm_response.latin_names == ["Tilia"]
