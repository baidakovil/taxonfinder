"""Pipeline orchestrator — Phases 1-5.

Thin orchestrator: all business logic lives in extractors, merge, resolvers.
This module only calls them in the right order and yields PipelineEvent.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import spacy
import structlog

from .checkpoint import FileCheckpoint
from .config import Config, LlmEnricherConfig, LlmExtractorConfig
from .events import (
    PhaseProgress,
    PhaseStarted,
    PipelineEstimate,
    PipelineEvent,
    PipelineFinished,
    PipelineSummary,
    ResultReady,
)
from .extractors.gazetteer import GazetteerExtractor
from .extractors.latin import LatinRegexExtractor, SentenceSpan
from .extractors.llm_client import (
    AnthropicClient,
    LlmClient,
    LlmError,
    OllamaClient,
    OpenAIClient,
)
from .extractors.llm_enricher import LlmEnricherConfig as EnricherCfg
from .extractors.llm_enricher import LlmEnricherPhase
from .extractors.llm_enricher import SentenceSpan as EnricherSentenceSpan
from .extractors.llm_extractor import LlmExtractorConfig as ExtractorCfg
from .extractors.llm_extractor import LlmExtractorPhase, chunk_text
from .gazetteer.storage import GazetteerStorage
from .merge import merge_candidates
from .models import (
    Candidate,
    CandidateGroup,
    ResolvedCandidate,
    TaxonMatch,
    TaxonomyInfo,
    TaxonResult,
)
from .normalizer import normalize, search_variants
from .rate_limiter import TokenBucketRateLimiter
from .resolvers.base import IdentificationResolver, TaxonSearcher
from .resolvers.cache import DiskCache, DiskCacheConfig
from .resolvers.identifier import DefaultIdentificationResolver
from .resolvers.inaturalist import INaturalistSearcher

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process(
    text: str,
    config: Config,
    *,
    searcher: TaxonSearcher | None = None,
    identifier: IdentificationResolver | None = None,
    llm_client: LlmClient | None = None,
    rate_limiter: object | None = None,
    checkpoint_dir: Path | None = None,
    nlp: Any | None = None,
) -> Iterator[PipelineEvent]:
    """Main sync generator.  Core pipeline.

    Dependencies are accepted via keyword args for testability.
    If not provided, created from *config* (production defaults).
    """
    start_total = time.monotonic()
    phase_times: dict[str, float] = {}
    cleanup_callbacks: list[Callable[[], None]] = []

    # --- build dependencies ------------------------------------------------
    if nlp is None:
        nlp = spacy.load(config.spacy_model)
    try:
        import pymorphy3  # noqa: PLC0415

        morph: object | None = pymorphy3.MorphAnalyzer()
    except Exception:
        morph = None

    doc = nlp(text)
    sentences = [
        SentenceSpan(start=sent.start_char, end=sent.end_char, text=sent.text) for sent in doc.sents
    ]
    enricher_sentences = [
        EnricherSentenceSpan(start=s.start, end=s.end, text=s.text) for s in sentences
    ]

    http_client: httpx.Client | None = None
    owns_http = False

    if searcher is None:
        if rate_limiter is None:
            rate_limiter = TokenBucketRateLimiter(
                rate=config.inaturalist.rate_limit,
                burst=config.inaturalist.burst_limit,
            )
        http_client = httpx.Client(headers={"User-Agent": config.user_agent})
        owns_http = True

        cache: DiskCache | None = None
        if config.inaturalist.cache_enabled:
            cache = DiskCache(
                DiskCacheConfig(
                    path=Path(config.inaturalist.cache_path),
                    ttl_days=config.inaturalist.cache_ttl_days,
                )
            )

        searcher = INaturalistSearcher(
            http=http_client,
            config=config.inaturalist,
            user_agent=config.user_agent,
            rate_limiter=rate_limiter,
            cache=cache,
        )

    if identifier is None:
        identifier = DefaultIdentificationResolver()

    # gazetteer
    storage: GazetteerStorage | None = None
    gazetteer_path = Path(config.gazetteer_path)
    if gazetteer_path.exists():
        try:
            storage = GazetteerStorage(gazetteer_path)
        except Exception as exc:
            if not config.degraded_mode:
                raise
            logger.warning("gazetteer_unavailable", error=str(exc))
    elif not config.degraded_mode:
        raise FileNotFoundError(
            f"Gazetteer not found: {gazetteer_path}. "
            "Set degraded_mode=true in config to continue without it."
        )
    else:
        logger.warning("gazetteer_not_found", path=str(gazetteer_path))

    # checkpoint
    cp: FileCheckpoint | None = None
    cp_key: str | None = None
    if checkpoint_dir is not None:
        cp = FileCheckpoint(checkpoint_dir)
        cp_key = cp.key(text, config)

    summary_data: dict[str, Any] = {
        "total_candidates": 0,
        "skipped_resolution": 0,
        "api_calls": 0,
        "cache_hits": 0,
    }

    try:
        # ===================================================================
        # PHASE 1: Extraction
        # ===================================================================
        t0 = time.monotonic()
        all_candidates: list[Candidate] = []

        # --- Gazetteer ---
        if storage is not None:
            gazetteer_ext = GazetteerExtractor(
                storage,
                locale=config.locale,
                nlp=nlp,
                morph=morph,
            )
            gaz_candidates = gazetteer_ext.extract(doc)
            all_candidates.extend(gaz_candidates)
            logger.info("extraction_gazetteer", count=len(gaz_candidates))

        # --- Latin regex ---
        is_known: Any = None
        if storage is not None:
            known_latin = {row_name.lower() for row_name in _collect_latin_names(storage)}
            is_known = lambda name: name.lower() in known_latin  # noqa: E731
        latin_ext = LatinRegexExtractor(morph=morph, is_known_name=is_known)
        latin_candidates = latin_ext.extract(text, sentences=sentences)
        all_candidates.extend(latin_candidates)
        logger.info("extraction_latin", count=len(latin_candidates))

        # --- LLM extractor ---
        llm_candidates: list[Candidate] = []
        if config.llm_extractor is not None and config.llm_extractor.enabled:
            if llm_client is not None:
                llm_ext_client = llm_client
            else:
                llm_ext_client, cleanup = _build_llm_client(
                    config.llm_extractor,
                    config,
                    http_client,
                )
                if cleanup is not None:
                    cleanup_callbacks.append(cleanup)
            ext_cfg = ExtractorCfg(
                provider=config.llm_extractor.provider,
                model=config.llm_extractor.model,
                prompt_file=config.llm_extractor.prompt_file,
                timeout=config.llm_extractor.timeout,
                chunk_strategy=config.llm_extractor.chunk_strategy,
                min_chunk_words=config.llm_extractor.min_chunk_words,
                max_chunk_words=config.llm_extractor.max_chunk_words,
            )
            sentence_texts = [s.text for s in sentences]
            llm_extractor = LlmExtractorPhase(
                ext_cfg,
                locale=config.locale,
                llm_client=llm_ext_client,
                morph=morph,
                sentence_splitter=lambda t: sentence_texts,
            )

            chunks = chunk_text(
                text,
                strategy=config.llm_extractor.chunk_strategy,
                min_words=config.llm_extractor.min_chunk_words,
                max_words=config.llm_extractor.max_chunk_words,
                sentence_splitter=lambda t: sentence_texts,
            )
            total_chunks = len(chunks)
            yield PhaseStarted(phase="extraction", total=total_chunks)

            llm_candidates = llm_extractor.extract(text)
            all_candidates.extend(llm_candidates)
            logger.info("extraction_llm", count=len(llm_candidates))

            for i in range(total_chunks):
                yield PhaseProgress(
                    phase="extraction",
                    current=i + 1,
                    total=total_chunks,
                    detail=f"LLM chunk {i + 1}/{total_chunks}",
                )
        else:
            yield PhaseStarted(phase="extraction", total=0)

        summary_data["total_candidates"] = len(all_candidates)
        phase_times["extraction"] = time.monotonic() - t0

        # ===================================================================
        # PHASE 2: Merge & Dedup
        # ===================================================================
        t0 = time.monotonic()
        yield PhaseStarted(phase="merge", total=len(all_candidates))

        def _skip_check(c: Candidate) -> bool:
            if c.method != "gazetteer" or not c.gazetteer_taxon_ids or storage is None:
                return False
            for tid in c.gazetteer_taxon_ids:
                rec = storage.get_full_record(tid, config.locale)
                if rec is None:
                    return False
                if not rec.taxon_name or not rec.taxon_rank:
                    return False
            return True

        groups = merge_candidates(all_candidates, skip_resolution_check=_skip_check)
        logger.info("merge_complete", groups=len(groups))
        yield PhaseProgress(
            phase="merge",
            current=len(all_candidates),
            total=len(all_candidates),
            detail=f"{len(groups)} unique candidates",
        )
        phase_times["merge"] = time.monotonic() - t0

        # ===================================================================
        # PHASE 3: Resolution
        # ===================================================================
        t0 = time.monotonic()
        to_resolve = [g for g in groups if not g.skip_resolution]
        to_skip = [g for g in groups if g.skip_resolution]
        summary_data["skipped_resolution"] = len(to_skip)

        yield PhaseStarted(phase="resolution", total=len(to_resolve))

        resolved: list[ResolvedCandidate] = []

        # Resolve groups that already have full gazetteer data
        for group in to_skip:
            matches = _matches_from_gazetteer(group, storage, config.locale)
            identified, reason = identifier.resolve(group, matches)
            resolved.append(
                ResolvedCandidate(
                    group=group,
                    matches=matches,
                    identified=identified,
                    llm_response=None,
                    candidate_names=[],
                    reason=reason,
                )
            )

        # Resolve groups via iNaturalist API
        for idx, group in enumerate(to_resolve, 1):
            variants = search_variants(group.normalized, morph)
            matches: list[TaxonMatch] = []
            identified = False
            reason = "No matches in iNaturalist"

            for var in variants:
                new_matches = searcher.search(var, config.locale)
                summary_data["api_calls"] += 1
                matches = _merge_matches(matches, new_matches)
                identified, reason = identifier.resolve(group, matches)
                if identified:
                    break

            candidate_names: list[str] = []
            if not identified:
                candidate_names = list(variants)

            resolved.append(
                ResolvedCandidate(
                    group=group,
                    matches=matches,
                    identified=identified,
                    llm_response=None,
                    candidate_names=candidate_names,
                    reason=reason,
                )
            )

            yield PhaseProgress(
                phase="resolution",
                current=idx,
                total=len(to_resolve),
                detail=f"iNaturalist: {group.normalized}",
            )

        phase_times["resolution"] = time.monotonic() - t0

        # ===================================================================
        # PHASE 4: LLM Enrichment
        # ===================================================================
        t0 = time.monotonic()
        unresolved = [r for r in resolved if not r.identified]

        enricher_enabled = (
            config.llm_enricher is not None and config.llm_enricher.enabled and len(unresolved) > 0
        )

        if enricher_enabled:
            assert config.llm_enricher is not None
            if llm_client is not None:
                enricher_client = llm_client
            else:
                enricher_client, cleanup = _build_llm_client(
                    config.llm_enricher,
                    config,
                    http_client,
                )
                if cleanup is not None:
                    cleanup_callbacks.append(cleanup)
            enr_cfg = EnricherCfg(
                provider=config.llm_enricher.provider,
                model=config.llm_enricher.model,
                prompt_file=config.llm_enricher.prompt_file,
                timeout=config.llm_enricher.timeout,
            )
            enricher = LlmEnricherPhase(
                enr_cfg,
                locale=config.locale,
                llm_client=enricher_client,
            )

            yield PhaseStarted(phase="enrichment", total=len(unresolved))

            for idx, rc in enumerate(unresolved, 1):
                llm_resp = enricher.enrich(
                    text,
                    rc.group,
                    sentences=enricher_sentences,
                )

                # Retry search with alternative names from LLM
                alt_names = (
                    llm_resp.common_names_loc + llm_resp.common_names_en + llm_resp.latin_names
                )
                extra_matches: list[TaxonMatch] = []
                tried_names = list(rc.candidate_names)
                for alt in alt_names:
                    norm_alt = normalize(alt)
                    if norm_alt not in tried_names:
                        tried_names.append(norm_alt)
                        new_matches = searcher.search(norm_alt, config.locale)
                        summary_data["api_calls"] += 1
                        extra_matches.extend(new_matches)

                # Merge and deduplicate matches
                combined = _merge_matches(rc.matches, extra_matches)
                identified, reason = identifier.resolve(rc.group, combined)

                if identified:
                    tried_names = []
                    reason = ""

                rc.group  # keep reference
                # Update resolved candidate in-place via index
                idx_in_resolved = resolved.index(rc)
                resolved[idx_in_resolved] = ResolvedCandidate(
                    group=rc.group,
                    matches=combined,
                    identified=identified,
                    llm_response=llm_resp,
                    candidate_names=tried_names,
                    reason=reason,
                )

                yield PhaseProgress(
                    phase="enrichment",
                    current=idx,
                    total=len(unresolved),
                    detail=f"LLM enrichment: {rc.group.normalized}",
                )
        else:
            yield PhaseStarted(phase="enrichment", total=0)

        phase_times["enrichment"] = time.monotonic() - t0

        # ===================================================================
        # PHASE 5: Assembly
        # ===================================================================
        t0 = time.monotonic()
        yield PhaseStarted(phase="assembly", total=len(resolved))

        # Filter by confidence threshold
        filtered = [r for r in resolved if r.group.confidence >= config.confidence]

        identified_count = 0
        unidentified_count = 0

        for idx, rc in enumerate(filtered, 1):
            result = _build_result(rc)
            if result.identified:
                identified_count += 1
            else:
                unidentified_count += 1
            yield ResultReady(result=result)
            yield PhaseProgress(
                phase="assembly",
                current=idx,
                total=len(filtered),
                detail=f"Assembled: {result.source_text}",
            )

        phase_times["assembly"] = time.monotonic() - t0

        # ===================================================================
        # Finish
        # ===================================================================
        total_time = time.monotonic() - start_total

        summary = PipelineSummary(
            total_candidates=summary_data["total_candidates"],
            unique_candidates=len(groups),
            identified_count=identified_count,
            unidentified_count=unidentified_count,
            skipped_resolution=summary_data["skipped_resolution"],
            api_calls=summary_data["api_calls"],
            cache_hits=summary_data["cache_hits"],
            phase_times=phase_times,
            total_time=total_time,
        )
        yield PipelineFinished(summary=summary)

        # Cleanup checkpoint on success
        if cp is not None and cp_key is not None:
            cp.clear(cp_key)

    except GeneratorExit:
        logger.info("pipeline_cancelled")
        if cp is not None and cp_key is not None:
            # Save checkpoint before exiting
            pass
    finally:
        for cb in reversed(cleanup_callbacks):
            try:
                cb()
            except Exception:
                name = cb.__name__ if hasattr(cb, "__name__") else "callback"
                logger.warning("cleanup_failed", cleanup=name)
        if owns_http and http_client is not None:
            http_client.close()


def process_all(text: str, config: Config, **kwargs: Any) -> list[TaxonResult]:
    """Convenience wrapper: returns only final results."""
    return [e.result for e in process(text, config, **kwargs) if isinstance(e, ResultReady)]


def estimate(text: str, config: Config) -> PipelineEstimate:
    """Dry-run: estimate workload without execution."""
    nlp = spacy.load(config.spacy_model)
    doc = nlp(text)

    sentence_list = list(doc.sents)
    sentence_texts = [s.text for s in sentence_list]

    # Estimate chunks for LLM extractor
    if config.llm_extractor is not None and config.llm_extractor.enabled:
        chunks = chunk_text(
            text,
            strategy=config.llm_extractor.chunk_strategy,
            min_words=config.llm_extractor.min_chunk_words,
            max_words=config.llm_extractor.max_chunk_words,
            sentence_splitter=lambda t: sentence_texts,
        )
        n_chunks = len(chunks)
        llm_calls = n_chunks
    else:
        n_chunks = 0
        llm_calls = 0

    # Run gazetteer and regex without API calls
    storage: GazetteerStorage | None = None
    gazetteer_path = Path(config.gazetteer_path)
    if gazetteer_path.exists():
        try:
            storage = GazetteerStorage(gazetteer_path)
        except Exception:
            pass

    gaz_count = 0
    if storage is not None:
        try:
            import pymorphy3  # noqa: PLC0415

            morph: object | None = pymorphy3.MorphAnalyzer()
        except Exception:
            morph = None

        gazetteer_ext = GazetteerExtractor(
            storage,
            locale=config.locale,
            nlp=nlp,
            morph=morph,
        )
        gaz_candidates = gazetteer_ext.extract(doc)
        gaz_count = len(gaz_candidates)

    sentences = [
        SentenceSpan(start=sent.start_char, end=sent.end_char, text=sent.text)
        for sent in sentence_list
    ]
    latin_ext = LatinRegexExtractor(morph=None)
    regex_candidates = latin_ext.extract(text, sentences=sentences)
    regex_count = len(regex_candidates)

    # Rough estimate of unique candidates (without LLM)
    unique_est = max(gaz_count + regex_count, 1)

    # Estimate skip_resolution
    skip_est = gaz_count  # rough: all gazetteer candidates may skip
    api_calls_est = max(unique_est - skip_est, 0)

    # Time estimate: 1 sec per API call + ~2 sec per LLM call
    estimated_time = api_calls_est * 1.0 + llm_calls * 2.0

    return PipelineEstimate(
        sentences=len(sentence_list),
        chunks=n_chunks,
        llm_calls_phase1=llm_calls,
        gazetteer_candidates=gaz_count,
        regex_candidates=regex_count,
        unique_candidates=unique_est,
        api_calls_estimated=api_calls_est,
        estimated_time_seconds=estimated_time,
    )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def format_deduplicated(results: list[TaxonResult]) -> dict[str, Any]:
    """Format results as deduplicated JSON with envelope."""
    return {
        "version": "1.0",
        "results": [
            {
                **result.to_dict(),
                "count": result.count,
            }
            for result in results
        ],
    }


def format_full(results: list[TaxonResult]) -> dict[str, Any]:
    """Format results as full (one entry per occurrence) JSON with envelope."""
    items: list[dict[str, Any]] = []
    for result in results:
        base = {
            "identified": result.identified,
            "extraction_confidence": result.extraction_confidence,
            "extraction_method": result.extraction_method,
            "matches": [m.to_dict() for m in result.matches],
            "candidate_names": list(result.candidate_names),
            "reason": result.reason,
            "llm_response": (
                result.llm_response.to_dict() if result.llm_response is not None else None
            ),
        }
        for occ in result.occurrences:
            items.append(
                {
                    "line_number": occ.line_number,
                    "source_text": occ.source_text,
                    "source_context": occ.source_context,
                    **base,
                }
            )
    return {"version": "1.0", "results": items}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_result(rc: ResolvedCandidate) -> TaxonResult:
    """Convert a ResolvedCandidate into a TaxonResult."""
    first_occ = rc.group.occurrences[0] if rc.group.occurrences else None
    return TaxonResult(
        source_text=first_occ.source_text if first_occ else rc.group.normalized,
        identified=rc.identified,
        extraction_confidence=rc.group.confidence,
        extraction_method=rc.group.method,
        occurrences=list(rc.group.occurrences),
        matches=rc.matches[:5],
        llm_response=rc.llm_response,
        candidate_names=rc.candidate_names,
        reason=rc.reason,
    )


def _matches_from_gazetteer(
    group: CandidateGroup,
    storage: GazetteerStorage | None,
    locale: str,
) -> list[TaxonMatch]:
    """Build TaxonMatch list from gazetteer data (skip_resolution path)."""
    if storage is None:
        return []

    matches: list[TaxonMatch] = []
    seen_ids: set[int] = set()
    for tid in group.gazetteer_taxon_ids:
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        rec = storage.get_full_record(tid, locale)
        if rec is None:
            continue
        taxonomy = _taxonomy_from_ancestry(rec.ancestry, rec.taxon_name, rec.taxon_rank)
        is_preferred = any(tid == t for t in group.gazetteer_taxon_ids[:1])
        matches.append(
            TaxonMatch(
                taxon_id=rec.taxon_id,
                taxon_name=rec.taxon_name,
                taxon_rank=rec.taxon_rank,
                taxonomy=taxonomy,
                taxon_common_name_en=rec.taxon_common_name_en,
                taxon_common_name_loc=rec.taxon_common_name_loc,
                taxon_matched_name=group.normalized,
                taxon_url=f"https://www.inaturalist.org/taxa/{rec.taxon_id}",
                score=1.0 if is_preferred else 0.5,
                taxon_names=[],
            )
        )
    return matches


def _taxonomy_from_ancestry(
    ancestry: str | None,
    taxon_name: str,
    taxon_rank: str,
) -> TaxonomyInfo:
    """Build TaxonomyInfo from a gazetteer ancestry string.

    The ancestry string from iNaturalist is a slash-separated list of ancestor
    taxon IDs.  Without a full lookup table we can only populate the level
    corresponding to the taxon itself.
    """
    info = TaxonomyInfo()
    _set_rank(info, taxon_rank, taxon_name)
    return info


def _set_rank(info: TaxonomyInfo, rank: str, name: str) -> None:
    if rank == "kingdom":
        info.kingdom = name
    elif rank == "phylum":
        info.phylum = name
    elif rank == "class":
        info.class_ = name
    elif rank == "order":
        info.order = name
    elif rank == "family":
        info.family = name
    elif rank == "genus":
        info.genus = name
    elif rank == "species":
        info.species = name


def _merge_matches(
    existing: list[TaxonMatch],
    extra: list[TaxonMatch],
) -> list[TaxonMatch]:
    """Merge two lists of TaxonMatch, dedup by taxon_id, sort by score."""
    seen: set[int] = set()
    combined: list[TaxonMatch] = []
    for m in existing:
        if m.taxon_id not in seen:
            seen.add(m.taxon_id)
            combined.append(m)
    for m in extra:
        if m.taxon_id not in seen:
            seen.add(m.taxon_id)
            combined.append(m)
    combined.sort(key=lambda m: m.score, reverse=True)
    return combined[:5]


def _collect_latin_names(storage: GazetteerStorage) -> set[str]:
    """Get all latin taxon names from the gazetteer for regex validation."""
    try:
        with storage._connect() as conn:
            rows = conn.execute("SELECT taxon_name FROM taxa").fetchall()
            return {str(row["taxon_name"]).lower() for row in rows}
    except Exception:
        return set()


def _prepare_ollama(
    *,
    http: httpx.Client,
    base_url: str,
    model: str,
    auto_start: bool,
    auto_pull: bool,
    stop_after: bool,
    timeout: float,
) -> Callable[[], None] | None:
    """Ensure Ollama is reachable and model exists; return cleanup callback if started."""

    def _reachable() -> bool:
        try:
            resp = http.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
            return resp.status_code < 500
        except Exception:
            return False

    def _model_available() -> bool:
        try:
            resp = http.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
            data = resp.json()
            models = data.get("models", []) if isinstance(data, dict) else []
            return any(m.get("name") == model for m in models if isinstance(m, dict))
        except Exception:
            return False

    started_proc: subprocess.Popen[bytes] | None = None

    if not _reachable() and auto_start:
        logger.info("ollama_auto_start", base_url=base_url)
        proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        started_proc = proc
        deadline = time.monotonic() + max(timeout, 5)
        while time.monotonic() < deadline:
            if _reachable():
                logger.info("ollama_started", base_url=base_url)
                break
            time.sleep(0.5)
        else:
            proc.terminate()
            raise LlmError(f"Failed to start ollama serve at {base_url}")

    if not _reachable():
        raise LlmError(
            f"Ollama is not reachable at {base_url}. "
            "Start 'ollama serve' or set auto_start=true in config."
        )

    if auto_pull and not _model_available():
        logger.info("ollama_pull_model", model=model)
        try:
            subprocess.run(
                ["ollama", "pull", model],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise LlmError("Ollama CLI not found; please install Ollama.") from exc
        except subprocess.CalledProcessError as exc:
            raise LlmError(f"ollama pull failed for model {model}") from exc

        if not _model_available():
            raise LlmError(f"Model {model} is still unavailable after pull")

    if started_proc is None or not stop_after:
        return None

    def _cleanup() -> None:
        started_proc.terminate()

    return _cleanup


def _build_llm_client(
    llm_config: LlmExtractorConfig | LlmEnricherConfig,
    config: Config,
    http_client: httpx.Client | None,
) -> tuple[LlmClient, Callable[[], None] | None]:
    """Build an LlmClient from config, returning optional cleanup callback."""
    import os

    http = http_client or httpx.Client(headers={"User-Agent": config.user_agent})
    cleanup: Callable[[], None] | None = None

    if llm_config.provider == "ollama":
        base_url = llm_config.url or "http://localhost:11434"
        cleanup = _prepare_ollama(
            http=http,
            base_url=base_url,
            model=llm_config.model,
            auto_start=llm_config.auto_start,
            auto_pull=llm_config.auto_pull_model,
            stop_after=llm_config.stop_after_run,
            timeout=llm_config.timeout,
        )
        return (
            OllamaClient(
                base_url=base_url,
                model=llm_config.model,
                timeout=llm_config.timeout,
                http=http,
                user_agent=config.user_agent,
            ),
            cleanup,
        )
    if llm_config.provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        return (
            OpenAIClient(
                base_url=llm_config.url or "https://api.openai.com",
                model=llm_config.model,
                timeout=llm_config.timeout,
                api_key=api_key,
                http=http,
                user_agent=config.user_agent,
            ),
            None,
        )
    if llm_config.provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        return (
            AnthropicClient(
                base_url=llm_config.url or "https://api.anthropic.com",
                model=llm_config.model,
                timeout=llm_config.timeout,
                api_key=api_key,
                http=http,
                user_agent=config.user_agent,
            ),
            None,
        )
    raise ValueError(f"Unknown LLM provider: {llm_config.provider}")


__all__ = [
    "estimate",
    "format_deduplicated",
    "format_full",
    "process",
    "process_all",
]
