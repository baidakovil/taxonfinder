from __future__ import annotations

import json
from pathlib import Path

import pytest


DATA_DIR = Path(__file__).parent / "data"


def _load_fixture(name: str) -> list[dict]:
    """Load a JSON fixture from the tests/data directory."""
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def test_first_case_contains_linden_taxon_id() -> None:
    output = _load_fixture("one_sentence_output.json")

    taxon_ids = {
        match["taxon_id"]
        for item in output
        for match in item.get("matches", [])
        if "taxon_id" in match
    }

    assert 54586 in taxon_ids


def test_first_case_has_extraction_confidence() -> None:
    output = _load_fixture("one_sentence_output.json")

    for item in output:
        assert "extraction_confidence" in item
        assert 0.0 <= item["extraction_confidence"] <= 1.0


def test_first_case_has_extraction_method() -> None:
    output = _load_fixture("one_sentence_output.json")

    valid_methods = {"gazetteer", "latin_regex", "llm"}
    for item in output:
        assert "extraction_method" in item
        assert item["extraction_method"] in valid_methods


def test_negative_case_has_empty_output() -> None:
    output = _load_fixture("negative_sentence_output.json")

    assert output == []


def test_ambiguous_case_has_multiple_matches() -> None:
    output = _load_fixture("ambiguous_sentence_output.json")

    assert any(len(item.get("matches", [])) >= 2 for item in output)


def test_ambiguous_case_is_not_identified() -> None:
    output = _load_fixture("ambiguous_sentence_output.json")

    assert all(item["identified"] == "no" for item in output)


def test_ambiguous_case_has_candidate_names_and_reason() -> None:
    output = _load_fixture("ambiguous_sentence_output.json")

    for item in output:
        if item["identified"] == "no":
            assert "candidate_names" in item
            assert "reason" in item
            assert len(item["candidate_names"]) > 0
            assert len(item["reason"]) > 0
