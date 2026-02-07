"""Tests for pipeline orchestrator — process(), process_all(), estimate(),
format_deduplicated(), format_full().

Uses mock searcher and LLM client to avoid real HTTP requests.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import spacy

from taxonfinder.config import Config, InaturalistConfig
from taxonfinder.events import (
    PipelineEstimate,
    PipelineEvent,
    PipelineFinished,
    PhaseProgress,
    PhaseStarted,
    PipelineSummary,
    ResultReady,
)
from taxonfinder.models import (
    CandidateGroup,
    LlmEnrichmentResponse,
    Occurrence,
    ResolvedCandidate,
    TaxonMatch,
    TaxonomyInfo,
    TaxonResult,
)
from taxonfinder.pipeline import (
    format_deduplicated,
    format_full,
    process,
    process_all,
)


# ---------------------------------------------------------------------------
# Helpers / Mocks
# ---------------------------------------------------------------------------

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _test_nlp():
    """Create a minimal spaCy pipeline for testing (no downloaded model needed)."""
    nlp = spacy.blank("ru")
    nlp.add_pipe("sentencizer")
    return nlp


class FakeSearcher:
    """Mock TaxonSearcher that returns pre-configured responses."""

    def __init__(self, responses: dict[str, list[TaxonMatch]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str]] = []

    def search(self, query: str, locale: str) -> list[TaxonMatch]:
        self.calls.append((query, locale))
        return self.responses.get(query, [])


class FakeIdentifier:
    """Mock IdentificationResolver."""

    def __init__(self, identify_all: bool = True) -> None:
        self._identify_all = identify_all

    def resolve(
        self, group: CandidateGroup, matches: list[TaxonMatch]
    ) -> tuple[bool, str]:
        if not matches:
            return False, "No matches in iNaturalist"
        if self._identify_all:
            return True, ""
        return False, "Common name not matched"


class FakeLlmClient:
    """Mock LlmClient that returns a fixed JSON response."""

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def complete(
        self,
        system_prompt: str,
        user_content: str,
        *,
        response_schema: dict | None = None,
    ) -> str:
        return json.dumps(self.response)


def _linden_match() -> TaxonMatch:
    return TaxonMatch(
        taxon_id=54586,
        taxon_name="Tilia",
        taxon_rank="genus",
        taxonomy=TaxonomyInfo(
            kingdom="Plantae",
            phylum="Tracheophyta",
            class_="Magnoliopsida",
            order="Malvales",
            family="Malvaceae",
            genus="Tilia",
        ),
        taxon_common_name_en="Lindens",
        taxon_common_name_loc="Липа",
        taxon_matched_name="липа",
        taxon_url="https://www.inaturalist.org/taxa/54586",
        score=10.0,
        taxon_names=["Липа", "Linden"],
    )


def _spruce_match() -> TaxonMatch:
    return TaxonMatch(
        taxon_id=100,
        taxon_name="Picea",
        taxon_rank="genus",
        taxonomy=TaxonomyInfo(
            kingdom="Plantae",
            genus="Picea",
        ),
        taxon_common_name_en="Spruces",
        taxon_common_name_loc="Ель",
        taxon_matched_name="ель",
        taxon_url="https://www.inaturalist.org/taxa/100",
        score=9.0,
        taxon_names=["Ель"],
    )


def _create_test_db(path: Path) -> None:
    """Create a minimal gazetteer database for testing."""
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 1")
        conn.executescript(
            """
            CREATE TABLE taxa (
                taxon_id INTEGER PRIMARY KEY,
                taxon_name TEXT NOT NULL,
                taxon_rank TEXT NOT NULL,
                ancestry TEXT
            );
            CREATE TABLE common_names (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                taxon_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                name_normalized TEXT NOT NULL,
                name_lemmatized TEXT,
                locale TEXT NOT NULL,
                is_preferred BOOLEAN DEFAULT 0,
                lexicon TEXT
            );
            INSERT INTO taxa VALUES (54586, 'Tilia', 'genus', '48460/47126/211194/47125/47124');
            INSERT INTO common_names (taxon_id, name, name_normalized, name_lemmatized, locale, is_preferred)
                VALUES (54586, 'Липа', 'липа', 'липа', 'ru', 1);
            INSERT INTO common_names (taxon_id, name, name_normalized, name_lemmatized, locale, is_preferred)
                VALUES (54586, 'Lindens', 'lindens', 'linden', 'en', 1);
            """
        )


def _minimal_config(
    tmp_path: Path,
    *,
    degraded_mode: bool = True,
    gazetteer_path: str | None = None,
) -> Config:
    """Create a minimal Config for testing."""
    return Config(
        confidence=0.5,
        locale="ru",
        gazetteer_path=gazetteer_path or str(tmp_path / "nonexistent.db"),
        spacy_model="ru_core_news_sm",
        max_file_size_mb=2.0,
        degraded_mode=degraded_mode,
        user_agent="TaxonFinder/0.1.0-test",
        inaturalist=InaturalistConfig(
            cache_enabled=False,
        ),
    )


# ---------------------------------------------------------------------------
# Tests: process() event stream
# ---------------------------------------------------------------------------


class TestProcessEventStream:
    """Test that process() yields the expected events in order."""

    def test_yields_phase_started_and_finished(self, tmp_path: Path) -> None:
        """Even with no candidates, we should get phase events and finish."""
        config = _minimal_config(tmp_path)
        text = "Простой текст без таксонов."

        events = list(process(
            text, config,
            searcher=FakeSearcher(),
            identifier=FakeIdentifier(),
            nlp=_test_nlp(),
        ))

        phase_names = [e.phase for e in events if isinstance(e, PhaseStarted)]
        assert "extraction" in phase_names
        assert "merge" in phase_names
        assert "resolution" in phase_names
        assert "enrichment" in phase_names
        assert "assembly" in phase_names

        finished = [e for e in events if isinstance(e, PipelineFinished)]
        assert len(finished) == 1

    def test_pipeline_finished_has_summary(self, tmp_path: Path) -> None:
        config = _minimal_config(tmp_path)
        text = "Нет таксонов в этом тексте."

        events = list(process(
            text, config,
            searcher=FakeSearcher(),
            identifier=FakeIdentifier(),
            nlp=_test_nlp(),
        ))

        finished = [e for e in events if isinstance(e, PipelineFinished)][0]
        summary = finished.summary
        assert isinstance(summary, PipelineSummary)
        assert summary.total_time > 0
        assert isinstance(summary.phase_times, dict)

    def test_result_ready_yielded_for_identified_candidate(self, tmp_path: Path) -> None:
        """When gazetteer finds a candidate and resolution succeeds, we get ResultReady."""
        db_path = tmp_path / "gazetteer.db"
        _create_test_db(db_path)
        config = _minimal_config(tmp_path, gazetteer_path=str(db_path))

        text = "На перевале росла огромная липа."
        searcher = FakeSearcher({"липа": [_linden_match()]})

        events = list(process(
            text, config,
            searcher=searcher,
            identifier=FakeIdentifier(identify_all=True),
            nlp=_test_nlp(),
        ))

        results = [e for e in events if isinstance(e, ResultReady)]
        assert len(results) >= 1
        result = results[0].result
        assert result.source_text == "липа"
        assert result.identified is True


class TestProcessAll:
    """Test the process_all() convenience wrapper."""

    def test_returns_list_of_taxon_results(self, tmp_path: Path) -> None:
        db_path = tmp_path / "gazetteer.db"
        _create_test_db(db_path)
        config = _minimal_config(tmp_path, gazetteer_path=str(db_path))

        text = "На перевале росла огромная липа."
        searcher = FakeSearcher({"липа": [_linden_match()]})

        results = process_all(
            text, config,
            searcher=searcher,
            identifier=FakeIdentifier(identify_all=True),
            nlp=_test_nlp(),
        )

        assert isinstance(results, list)
        assert all(isinstance(r, TaxonResult) for r in results)
        assert len(results) >= 1

    def test_empty_text_returns_empty_list(self, tmp_path: Path) -> None:
        config = _minimal_config(tmp_path)
        results = process_all(
            "Нет ни одного таксона.", config,
            searcher=FakeSearcher(),
            identifier=FakeIdentifier(),
            nlp=_test_nlp(),
        )
        assert results == []


# ---------------------------------------------------------------------------
# Tests: format_deduplicated() and format_full()
# ---------------------------------------------------------------------------


def _sample_result() -> TaxonResult:
    return TaxonResult(
        source_text="липа",
        identified=True,
        extraction_confidence=1.0,
        extraction_method="gazetteer",
        occurrences=[
            Occurrence(line_number=10, source_text="липа", source_context="Росла липа."),
            Occurrence(line_number=45, source_text="лип", source_context="Среди лип."),
        ],
        matches=[_linden_match()],
        llm_response=None,
        candidate_names=[],
        reason="",
    )


def _unidentified_result() -> TaxonResult:
    return TaxonResult(
        source_text="зверь",
        identified=False,
        extraction_confidence=0.6,
        extraction_method="llm",
        occurrences=[
            Occurrence(line_number=5, source_text="зверь", source_context="Встретился зверь."),
        ],
        matches=[],
        llm_response=LlmEnrichmentResponse(
            common_names_loc=["зверёк"],
            common_names_en=["beast"],
            latin_names=[],
        ),
        candidate_names=["зверь", "зверёк", "beast"],
        reason="No matches in iNaturalist",
    )


class TestFormatDeduplicated:

    def test_envelope_has_version_and_results(self) -> None:
        output = format_deduplicated([_sample_result()])
        assert output["version"] == "1.0"
        assert "results" in output
        assert isinstance(output["results"], list)

    def test_result_has_count_field(self) -> None:
        output = format_deduplicated([_sample_result()])
        item = output["results"][0]
        assert item["count"] == 2

    def test_result_has_occurrences(self) -> None:
        output = format_deduplicated([_sample_result()])
        item = output["results"][0]
        assert len(item["occurrences"]) == 2
        assert item["occurrences"][0]["line_number"] == 10

    def test_result_has_matches_with_taxonomy(self) -> None:
        output = format_deduplicated([_sample_result()])
        match = output["results"][0]["matches"][0]
        assert match["taxon_id"] == 54586
        assert match["taxonomy"]["class"] == "Magnoliopsida"
        assert "class_" not in match["taxonomy"]  # no underscore in JSON

    def test_empty_results(self) -> None:
        output = format_deduplicated([])
        assert output == {"version": "1.0", "results": []}

    def test_llm_response_null_when_not_used(self) -> None:
        output = format_deduplicated([_sample_result()])
        assert output["results"][0]["llm_response"] is None

    def test_llm_response_present_when_used(self) -> None:
        output = format_deduplicated([_unidentified_result()])
        item = output["results"][0]
        assert item["llm_response"] is not None
        assert "common_names_loc" in item["llm_response"]

    def test_validates_against_schema(self) -> None:
        schema_path = SCHEMAS_DIR / "output-deduplicated.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        output = format_deduplicated([_sample_result()])
        jsonschema.validate(output, schema)

    def test_validates_against_schema_with_unidentified(self) -> None:
        schema_path = SCHEMAS_DIR / "output-deduplicated.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        output = format_deduplicated([_sample_result(), _unidentified_result()])
        jsonschema.validate(output, schema)


class TestFormatFull:

    def test_envelope_has_version(self) -> None:
        output = format_full([_sample_result()])
        assert output["version"] == "1.0"

    def test_one_entry_per_occurrence(self) -> None:
        output = format_full([_sample_result()])
        # _sample_result has 2 occurrences
        assert len(output["results"]) == 2

    def test_each_entry_has_required_fields(self) -> None:
        output = format_full([_sample_result()])
        for item in output["results"]:
            assert "line_number" in item
            assert "source_text" in item
            assert "source_context" in item
            assert "identified" in item
            assert "extraction_confidence" in item
            assert "extraction_method" in item
            assert "matches" in item
            assert "candidate_names" in item
            assert "reason" in item

    def test_validates_against_schema(self) -> None:
        schema_path = SCHEMAS_DIR / "output-full.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        output = format_full([_sample_result()])
        jsonschema.validate(output, schema)

    def test_validates_against_schema_with_unidentified(self) -> None:
        schema_path = SCHEMAS_DIR / "output-full.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        output = format_full([_sample_result(), _unidentified_result()])
        jsonschema.validate(output, schema)

    def test_empty_results(self) -> None:
        output = format_full([])
        assert output == {"version": "1.0", "results": []}


# ---------------------------------------------------------------------------
# Tests: Pipeline integration with mock dependencies
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    """Integration tests with mock searcher/identifier."""

    def test_gazetteer_candidate_skip_resolution(self, tmp_path: Path) -> None:
        """Gazetteer candidates with full data should skip iNaturalist API."""
        db_path = tmp_path / "gazetteer.db"
        _create_test_db(db_path)
        config = _minimal_config(tmp_path, gazetteer_path=str(db_path))

        text = "На перевале росла огромная липа."
        searcher = FakeSearcher()  # no responses configured

        results = process_all(
            text, config,
            searcher=searcher,
            identifier=FakeIdentifier(identify_all=True),
            nlp=_test_nlp(),
        )

        # Searcher should NOT have been called — skip_resolution=True
        assert len(searcher.calls) == 0
        assert len(results) >= 1

    def test_degraded_mode_without_gazetteer(self, tmp_path: Path) -> None:
        """Pipeline should work without gazetteer when degraded_mode=True."""
        config = _minimal_config(tmp_path, degraded_mode=True)
        text = "Простой текст без Tilia cordata."

        # With degraded mode, pipeline should not crash
        events = list(process(
            text, config,
            searcher=FakeSearcher(),
            identifier=FakeIdentifier(),
            nlp=_test_nlp(),
        ))
        finished = [e for e in events if isinstance(e, PipelineFinished)]
        assert len(finished) == 1

    def test_no_gazetteer_strict_mode_raises(self, tmp_path: Path) -> None:
        """Without degraded_mode, missing gazetteer should raise."""
        config = _minimal_config(tmp_path, degraded_mode=False)
        text = "Текст."

        with pytest.raises(FileNotFoundError):
            list(process(
                text, config,
                searcher=FakeSearcher(),
                identifier=FakeIdentifier(),
                nlp=_test_nlp(),
            ))

    def test_confidence_filter(self, tmp_path: Path) -> None:
        """Results below confidence threshold should be filtered out."""
        config = _minimal_config(tmp_path)
        config.confidence = 0.9  # high threshold

        text = "Текст без таксонов но с ёлками."
        results = process_all(
            text, config,
            searcher=FakeSearcher(),
            identifier=FakeIdentifier(),
            nlp=_test_nlp(),
        )

        # All results should have confidence >= 0.9
        for r in results:
            assert r.extraction_confidence >= 0.9

    def test_latin_regex_detection(self, tmp_path: Path) -> None:
        """Latin binomials should be detected by regex extractor."""
        config = _minimal_config(tmp_path)
        text = "Мы нашли Quercus robur в лесу."

        searcher = FakeSearcher({
            "quercus robur": [
                TaxonMatch(
                    taxon_id=50000,
                    taxon_name="Quercus robur",
                    taxon_rank="species",
                    taxonomy=TaxonomyInfo(genus="Quercus", species="Quercus robur"),
                    taxon_common_name_en="Pedunculate Oak",
                    taxon_common_name_loc="Дуб черешчатый",
                    taxon_matched_name="Quercus robur",
                    taxon_url="https://www.inaturalist.org/taxa/50000",
                    score=10.0,
                    taxon_names=["Quercus robur"],
                )
            ],
        })

        results = process_all(
            text, config,
            searcher=searcher,
            identifier=FakeIdentifier(identify_all=True),
            nlp=_test_nlp(),
        )

        assert len(results) >= 1
        assert any("Quercus robur" in r.source_text for r in results)

    def test_summary_counts(self, tmp_path: Path) -> None:
        """PipelineSummary should have accurate counts."""
        db_path = tmp_path / "gazetteer.db"
        _create_test_db(db_path)
        config = _minimal_config(tmp_path, gazetteer_path=str(db_path))

        text = "Липа и ещё раз липа. А ещё Quercus robur."

        searcher = FakeSearcher({
            "quercus robur": [
                TaxonMatch(
                    taxon_id=50000,
                    taxon_name="Quercus robur",
                    taxon_rank="species",
                    taxonomy=TaxonomyInfo(genus="Quercus", species="Quercus robur"),
                    taxon_common_name_en="Oak",
                    taxon_common_name_loc=None,
                    taxon_matched_name="Quercus robur",
                    taxon_url="https://www.inaturalist.org/taxa/50000",
                    score=10.0,
                    taxon_names=[],
                )
            ],
        })

        events = list(process(
            text, config,
            searcher=searcher,
            identifier=FakeIdentifier(identify_all=True),
            nlp=_test_nlp(),
        ))

        finished = [e for e in events if isinstance(e, PipelineFinished)][0]
        summary = finished.summary
        assert summary.unique_candidates >= 1
        assert summary.total_time > 0

    def test_output_schema_validation_end_to_end(self, tmp_path: Path) -> None:
        """End-to-end: process text → format → validate against JSON schema."""
        db_path = tmp_path / "gazetteer.db"
        _create_test_db(db_path)
        config = _minimal_config(tmp_path, gazetteer_path=str(db_path))

        text = "На перевале росла огромная липа."
        searcher = FakeSearcher({"липа": [_linden_match()]})

        results = process_all(
            text, config,
            searcher=searcher,
            identifier=FakeIdentifier(identify_all=True),
            nlp=_test_nlp(),
        )

        schema_path = SCHEMAS_DIR / "output-deduplicated.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        output = format_deduplicated(results)
        jsonschema.validate(output, schema)


# ---------------------------------------------------------------------------
# Tests: _build_result helper
# ---------------------------------------------------------------------------


class TestBuildResult:
    """Test TaxonResult assembly from ResolvedCandidate."""

    def test_source_text_from_first_occurrence(self) -> None:
        from taxonfinder.pipeline import _build_result

        group = CandidateGroup(
            normalized="липа",
            lemmatized="липа",
            method="gazetteer",
            confidence=1.0,
            occurrences=[
                Occurrence(line_number=10, source_text="липа", source_context="Росла липа."),
                Occurrence(line_number=20, source_text="лип", source_context="Среди лип."),
            ],
            gazetteer_taxon_ids=[54586],
            skip_resolution=True,
        )

        rc = ResolvedCandidate(
            group=group,
            matches=[_linden_match()],
            identified=True,
            llm_response=None,
            candidate_names=[],
            reason="",
        )

        result = _build_result(rc)
        assert result.source_text == "липа"
        assert result.count == 2
        assert result.identified is True
        assert result.extraction_method == "gazetteer"
        assert len(result.matches) == 1

    def test_matches_limited_to_5(self) -> None:
        from taxonfinder.pipeline import _build_result

        group = CandidateGroup(
            normalized="test",
            lemmatized="test",
            method="llm",
            confidence=0.6,
            occurrences=[Occurrence(line_number=1, source_text="test", source_context="ctx")],
            gazetteer_taxon_ids=[],
            skip_resolution=False,
        )

        # Create 7 matches
        many_matches = [
            TaxonMatch(
                taxon_id=i,
                taxon_name=f"Species{i}",
                taxon_rank="species",
                taxonomy=TaxonomyInfo(genus=f"Genus{i}"),
                taxon_common_name_en=None,
                taxon_common_name_loc=None,
                taxon_matched_name="test",
                taxon_url=f"https://www.inaturalist.org/taxa/{i}",
                score=float(10 - i),
                taxon_names=[],
            )
            for i in range(1, 8)
        ]

        rc = ResolvedCandidate(
            group=group,
            matches=many_matches,
            identified=False,
            llm_response=None,
            candidate_names=["test"],
            reason="Common name not matched",
        )

        result = _build_result(rc)
        assert len(result.matches) <= 5


# ---------------------------------------------------------------------------
# Tests: _merge_matches helper
# ---------------------------------------------------------------------------


class TestMergeMatches:

    def test_deduplicates_by_taxon_id(self) -> None:
        from taxonfinder.pipeline import _merge_matches

        m1 = _linden_match()
        m2 = _linden_match()  # same taxon_id

        combined = _merge_matches([m1], [m2])
        assert len(combined) == 1

    def test_sorts_by_score_descending(self) -> None:
        from taxonfinder.pipeline import _merge_matches

        m1 = _linden_match()  # score=10.0
        m2 = _spruce_match()  # score=9.0

        combined = _merge_matches([m2], [m1])
        assert combined[0].taxon_id == 54586  # higher score first

    def test_limits_to_5(self) -> None:
        from taxonfinder.pipeline import _merge_matches

        matches = [
            TaxonMatch(
                taxon_id=i,
                taxon_name=f"Species{i}",
                taxon_rank="species",
                taxonomy=TaxonomyInfo(),
                taxon_common_name_en=None,
                taxon_common_name_loc=None,
                taxon_matched_name="x",
                taxon_url=f"https://www.inaturalist.org/taxa/{i}",
                score=float(i),
                taxon_names=[],
            )
            for i in range(1, 8)
        ]

        combined = _merge_matches(matches[:4], matches[4:])
        assert len(combined) == 5
