from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import spacy

from taxonfinder.config import Config, InaturalistConfig
from taxonfinder.pipeline import process_all
from taxonfinder.resolvers.identifier import DefaultIdentificationResolver
from taxonfinder.resolvers.inaturalist import INaturalistSearcher

pytestmark = pytest.mark.inaturalist_live

TEXT_PATH = Path(__file__).resolve().parents[1] / "data" / "txt_samples" / "козуля.txt"


@pytest.fixture(autouse=True)
def _skip_unless_requested(request: pytest.FixtureRequest) -> None:
    """Skip live iNaturalist tests unless explicitly selected with -m inaturalist_live."""
    markexpr = request.config.option.markexpr
    if not markexpr or "inaturalist_live" not in markexpr:
        pytest.skip(
            "Live iNaturalist tests are skipped by default; run with -m inaturalist_live",
            allow_module_level=True,
        )


def _test_nlp():
    nlp = spacy.blank("ru")
    nlp.add_pipe("sentencizer")
    return nlp


def _live_config(tmp_path: Path) -> Config:
    return Config(
        confidence=0.3,
        locale="ru",
        gazetteer_path=str(tmp_path / "missing-gazetteer.db"),
        spacy_model="ru_core_news_sm",
        max_file_size_mb=5.0,
        degraded_mode=True,
        user_agent="TaxonFinder/0.1.0-live-test",
        inaturalist=InaturalistConfig(
            cache_enabled=False,
            timeout=20,
            max_retries=1,
        ),
        llm_extractor=None,
        llm_enricher=None,
    )


def test_inaturalist_search_live_returns_capreolus(tmp_path: Path) -> None:
    """Real autocomplete call should return Capreolus pygargus (taxon 42183)."""
    config = _live_config(tmp_path)

    with httpx.Client(timeout=config.inaturalist.timeout) as client:
        searcher = INaturalistSearcher(http=client, config=config.inaturalist)
        try:
            matches = searcher.search("Capreolus pygargus", config.locale)
        except httpx.HTTPError as exc:
            pytest.skip(f"iNaturalist unavailable: {exc!r}")

    assert matches, "iNaturalist returned no matches"
    assert any(m.taxon_id == 42183 for m in matches)


def test_pipeline_live_full_sentence(tmp_path: Path) -> None:
    """End-to-end pipeline on real text should resolve Capreolus pygargus via iNaturalist."""
    text = TEXT_PATH.read_text(encoding="utf-8")
    config = _live_config(tmp_path)

    with httpx.Client(timeout=config.inaturalist.timeout) as client:
        searcher = INaturalistSearcher(http=client, config=config.inaturalist)
        identifier = DefaultIdentificationResolver()
        try:
            results = process_all(
                text,
                config,
                searcher=searcher,
                identifier=identifier,
                nlp=_test_nlp(),
            )
        except httpx.HTTPError as exc:
            pytest.skip(f"iNaturalist unavailable: {exc!r}")

    assert results, "Pipeline returned no results"
    assert any(match.taxon_id == 42183 for result in results for match in result.matches)
