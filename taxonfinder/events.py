from __future__ import annotations

from dataclasses import dataclass

from .models import TaxonResult


@dataclass(slots=True)
class PhaseStarted:
    phase: str
    total: int


@dataclass(slots=True)
class PhaseProgress:
    phase: str
    current: int
    total: int
    detail: str


@dataclass(slots=True)
class ResultReady:
    result: TaxonResult


@dataclass(slots=True)
class PipelineSummary:
    total_candidates: int
    unique_candidates: int
    identified_count: int
    unidentified_count: int
    skipped_resolution: int
    api_calls: int
    cache_hits: int
    phase_times: dict[str, float]
    total_time: float


@dataclass(slots=True)
class PipelineEstimate:
    sentences: int
    chunks: int
    llm_calls_phase1: int
    gazetteer_candidates: int
    regex_candidates: int
    unique_candidates: int
    api_calls_estimated: int
    estimated_time_seconds: float


@dataclass(slots=True)
class PipelineFinished:
    summary: PipelineSummary


PipelineEvent = PhaseStarted | PhaseProgress | ResultReady | PipelineFinished
