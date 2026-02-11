"""
TDD test for iNaturalist taxonomy parsing.

This test uses real API response data to ensure taxonomy fields are correctly parsed.
Initially RED (failing), then will be GREEN after fix.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from taxonfinder.resolvers.inaturalist import _parse_matches


@pytest.fixture
def autocomplete_response() -> dict:
    """Load real autocomplete API response for Capreolus pygargus."""
    path = Path(__file__).parent / "data" / "inaturalist_autocomplete_capreolus_response.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def taxa_detail_response() -> dict:
    """Load real taxa/{id} API response for Capreolus pygargus (taxon_id=42183)."""
    path = Path(__file__).parent / "data" / "inaturalist_taxon_42183_response.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_parse_taxonomy_from_autocomplete_response(autocomplete_response: dict) -> None:
    """
    Test that _parse_matches can handle autocomplete response (without ancestors).
    
    Note: autocomplete endpoint does NOT include 'ancestors' field,
    so _parse_matches() will create incomplete taxonomy (only species rank filled).
    Full taxonomy is enriched later in INaturalistSearcher.search() via detail endpoint.
    
    This test verifies that _parse_matches() doesn't crash on autocomplete data.
    """
    matches = _parse_matches(autocomplete_response, locale="ru", query="Capreolus pygargus")
    
    assert len(matches) > 0, "Should have at least one match"
    match = matches[0]
    
    # Check basic fields work
    assert match.taxon_id == 42183
    assert match.taxon_name == "Capreolus pygargus"
    assert match.taxon_rank == "species"
    
    # Taxonomy from autocomplete is incomplete (no ancestors available)
    taxonomy = match.taxonomy
    assert taxonomy.species == "Capreolus pygargus", "Species should be filled from result.rank+result.name"
    # Other fields are None because autocomplete lacks 'ancestors'
    assert taxonomy.kingdom is None
    assert taxonomy.phylum is None
    assert taxonomy.class_ is None


def test_parse_taxonomy_from_detail_response(taxa_detail_response: dict) -> None:
    """
    Test that taxonomy is properly extracted from /v1/taxa/{id} API response.
    
    This response DOES include the 'ancestors' field, so this test should work
    with the current implementation.
    """
    matches = _parse_matches(taxa_detail_response, locale="ru", query="Capreolus pygargus")
    
    assert len(matches) > 0, "Should have at least one match"
    match = matches[0]
    
    # Check taxonomy fields work with detail response
    taxonomy = match.taxonomy
    assert taxonomy.kingdom == "Animalia"
    assert taxonomy.phylum == "Chordata"
    assert taxonomy.class_ == "Mammalia"
    assert taxonomy.order == "Artiodactyla"
    assert taxonomy.family == "Cervidae"
    assert taxonomy.genus == "Capreolus"
    assert taxonomy.species == "Capreolus pygargus"


def test_autocomplete_response_has_no_ancestors_field(autocomplete_response: dict) -> None:
    """
    Document the actual problem: autocomplete response lacks 'ancestors' field.
    
    This test verifies our understanding of the API structure.
    """
    result = autocomplete_response["results"][0]
    
    # These fields ARE present:
    assert "id" in result
    assert "rank" in result
    assert "name" in result
    assert "ancestry" in result  # String like "48460/1/2/355675/40151/..."
    assert "ancestor_ids" in result  # List of IDs: [48460, 1, 2, 355675, 40151, ...]
    
    # But 'ancestors' (with full details) is NOT:
    assert "ancestors" not in result, "autocomplete should not have 'ancestors' field"


def test_detail_response_has_ancestors_field(taxa_detail_response: dict) -> None:
    """
    Verify that detail endpoint (/v1/taxa/{id}) DOES include ancestors.
    """
    result = taxa_detail_response["results"][0]
    
    assert "ancestors" in result, "detail endpoint should have 'ancestors' field"
    ancestors = result["ancestors"]
    assert isinstance(ancestors, list)
    assert len(ancestors) > 0
    
    # Each ancestor should have rank and name
    for ancestor in ancestors:
        assert "rank" in ancestor
        assert "name" in ancestor


def test_inaturalist_searcher_enriches_taxonomy_from_detail_endpoint() -> None:
    """
    Integration test: INaturalistSearcher.search() should fetch full taxonomy
    from /v1/taxa/{id} endpoint for the top result.
    
    This is the main test that verifies the FIX works end-to-end.
    """
    import httpx
    from taxonfinder.config import InaturalistConfig
    from taxonfinder.resolvers.inaturalist import INaturalistSearcher
    
    config = InaturalistConfig()
    http_client = httpx.Client(timeout=30)
    
    searcher = INaturalistSearcher(
        http=http_client,
        config=config,
        user_agent="TaxonFinder/0.1.0 (test)",
    )
    
    # Search for Capreolus pygargus
    matches = searcher.search("Capreolus pygargus", "ru")
    http_client.close()
    
    assert len(matches) > 0, "Should have at least one match"
    match = matches[0]
    
    # Verify basic fields
    assert match.taxon_id == 42183
    assert match.taxon_name == "Capreolus pygargus"
    assert match.taxon_rank == "species"
    
    # Verify FULL taxonomy is now populated (enriched from detail endpoint)
    taxonomy = match.taxonomy
    assert taxonomy.kingdom == "Animalia", f"Expected kingdom='Animalia', got '{taxonomy.kingdom}'"
    assert taxonomy.phylum == "Chordata", f"Expected phylum='Chordata', got '{taxonomy.phylum}'"
    assert taxonomy.class_ == "Mammalia", f"Expected class='Mammalia', got '{taxonomy.class_}'"
    assert taxonomy.order == "Artiodactyla", f"Expected order='Artiodactyla', got '{taxonomy.order}'"
    assert taxonomy.family == "Cervidae", f"Expected family='Cervidae', got '{taxonomy.family}'"
    assert taxonomy.genus == "Capreolus", f"Expected genus='Capreolus', got '{taxonomy.genus}'"
    assert taxonomy.species == "Capreolus pygargus", f"Expected species='Capreolus pygargus', got '{taxonomy.species}'"
