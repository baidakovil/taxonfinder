from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def _load_fixture(name: str) -> list[dict]:
    """Load a JSON fixture from the tests/data directory."""
    payload = json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload.get("results", [])
    return payload


# --- one_sentence: gazetteer exact match ---


def test_one_sentence_contains_linden_taxon_id() -> None:
    output = _load_fixture("one_sentence_output.json")

    taxon_ids = {
        match["taxon_id"]
        for item in output
        for match in item.get("matches", [])
    }

    assert 54586 in taxon_ids


def test_one_sentence_has_valid_confidence() -> None:
    output = _load_fixture("one_sentence_output.json")

    for item in output:
        assert "extraction_confidence" in item
        assert 0.0 <= item["extraction_confidence"] <= 1.0


def test_one_sentence_has_valid_method() -> None:
    output = _load_fixture("one_sentence_output.json")

    valid_methods = {"gazetteer", "latin_regex", "llm"}
    for item in output:
        assert item["extraction_method"] in valid_methods


def test_one_sentence_has_deduplicated_structure() -> None:
    output = _load_fixture("one_sentence_output.json")

    for item in output:
        assert "count" in item
        assert item["count"] >= 1
        assert "occurrences" in item
        assert len(item["occurrences"]) == item["count"]

        for occ in item["occurrences"]:
            assert "line_number" in occ
            assert "source_text" in occ
            assert "source_context" in occ


# --- negative: no taxa found ---


def test_negative_case_has_empty_output() -> None:
    output = _load_fixture("negative_sentence_output.json")

    assert output == []


# --- ambiguous: unidentified with multiple matches ---


def test_ambiguous_case_has_multiple_matches() -> None:
    output = _load_fixture("ambiguous_sentence_output.json")

    assert any(len(item.get("matches", [])) >= 2 for item in output)


def test_ambiguous_case_is_not_identified() -> None:
    output = _load_fixture("ambiguous_sentence_output.json")

    assert all(item["identified"] is False for item in output)


def test_ambiguous_case_has_candidate_names_and_reason() -> None:
    output = _load_fixture("ambiguous_sentence_output.json")

    for item in output:
        if item["identified"] is False:
            assert "candidate_names" in item
            assert "reason" in item
            assert len(item["candidate_names"]) > 0
            assert len(item["reason"]) > 0


def test_ambiguous_case_has_deduplicated_structure() -> None:
    output = _load_fixture("ambiguous_sentence_output.json")

    for item in output:
        assert "count" in item
        assert "occurrences" in item
        assert len(item["occurrences"]) >= 1
