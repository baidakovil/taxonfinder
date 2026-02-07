from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ExtractionMethod = Literal["gazetteer", "latin_regex", "llm"]


@dataclass(slots=True)
class Candidate:
    source_text: str
    source_context: str
    line_number: int
    start_char: int
    end_char: int
    normalized: str
    lemmatized: str
    method: ExtractionMethod
    confidence: float
    gazetteer_taxon_ids: list[int] = field(default_factory=list)

    def to_occurrence(self) -> Occurrence:
        return Occurrence(
            line_number=self.line_number,
            source_text=self.source_text,
            source_context=self.source_context,
        )


@dataclass(slots=True)
class Occurrence:
    line_number: int
    source_text: str
    source_context: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_number": self.line_number,
            "source_text": self.source_text,
            "source_context": self.source_context,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Occurrence:
        return Occurrence(
            line_number=int(data["line_number"]),
            source_text=str(data["source_text"]),
            source_context=str(data["source_context"]),
        )


@dataclass(slots=True)
class CandidateGroup:
    normalized: str
    lemmatized: str
    method: ExtractionMethod
    confidence: float
    occurrences: list[Occurrence]
    gazetteer_taxon_ids: list[int]
    skip_resolution: bool


@dataclass(slots=True)
class TaxonomyInfo:
    kingdom: str | None = None
    phylum: str | None = None
    class_: str | None = None
    order: str | None = None
    family: str | None = None
    genus: str | None = None
    species: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kingdom": self.kingdom,
            "phylum": self.phylum,
            "class": self.class_,
            "order": self.order,
            "family": self.family,
            "genus": self.genus,
            "species": self.species,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> TaxonomyInfo:
        return TaxonomyInfo(
            kingdom=data.get("kingdom"),
            phylum=data.get("phylum"),
            class_=data.get("class"),
            order=data.get("order"),
            family=data.get("family"),
            genus=data.get("genus"),
            species=data.get("species"),
        )


@dataclass(slots=True)
class TaxonMatch:
    taxon_id: int
    taxon_name: str
    taxon_rank: str
    taxonomy: TaxonomyInfo
    taxon_common_name_en: str | None
    taxon_common_name_loc: str | None
    taxon_matched_name: str
    score: float
    taxon_url: str
    taxon_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "taxon_id": self.taxon_id,
            "taxon_name": self.taxon_name,
            "taxon_rank": self.taxon_rank,
            "taxonomy": self.taxonomy.to_dict(),
            "taxon_common_name_en": self.taxon_common_name_en,
            "taxon_common_name_loc": self.taxon_common_name_loc,
            "taxon_matched_name": self.taxon_matched_name,
            "taxon_url": self.taxon_url,
            "score": self.score,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> TaxonMatch:
        return TaxonMatch(
            taxon_id=int(data["taxon_id"]),
            taxon_name=str(data["taxon_name"]),
            taxon_rank=str(data["taxon_rank"]),
            taxonomy=TaxonomyInfo.from_dict(data["taxonomy"]),
            taxon_common_name_en=data.get("taxon_common_name_en"),
            taxon_common_name_loc=data.get("taxon_common_name_loc"),
            taxon_matched_name=str(data["taxon_matched_name"]),
            taxon_url=str(data["taxon_url"]),
            score=float(data["score"]),
            taxon_names=list(data.get("taxon_names", [])),
        )


@dataclass(slots=True)
class LlmEnrichmentResponse:
    common_names_loc: list[str] = field(default_factory=list)
    common_names_en: list[str] = field(default_factory=list)
    latin_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "common_names_loc": list(self.common_names_loc),
            "common_names_en": list(self.common_names_en),
            "latin_names": list(self.latin_names),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> LlmEnrichmentResponse:
        return LlmEnrichmentResponse(
            common_names_loc=list(data.get("common_names_loc", [])),
            common_names_en=list(data.get("common_names_en", [])),
            latin_names=list(data.get("latin_names", [])),
        )


@dataclass(slots=True)
class ResolvedCandidate:
    group: CandidateGroup
    matches: list[TaxonMatch]
    identified: bool
    llm_response: LlmEnrichmentResponse | None
    candidate_names: list[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "matches": [match.to_dict() for match in self.matches],
            "identified": self.identified,
            "llm_response": None if self.llm_response is None else self.llm_response.to_dict(),
            "candidate_names": list(self.candidate_names),
            "reason": self.reason,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ResolvedCandidate:
        llm_data = data.get("llm_response")
        return ResolvedCandidate(
            group=data["group"],
            matches=[TaxonMatch.from_dict(item) for item in data.get("matches", [])],
            identified=bool(data["identified"]),
            llm_response=None if llm_data is None else LlmEnrichmentResponse.from_dict(llm_data),
            candidate_names=list(data.get("candidate_names", [])),
            reason=str(data.get("reason", "")),
        )


@dataclass(slots=True)
class TaxonResult:
    source_text: str
    identified: bool
    extraction_confidence: float
    extraction_method: ExtractionMethod
    occurrences: list[Occurrence]
    matches: list[TaxonMatch]
    llm_response: LlmEnrichmentResponse | None
    candidate_names: list[str]
    reason: str

    @property
    def count(self) -> int:
        return len(self.occurrences)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_text": self.source_text,
            "identified": self.identified,
            "extraction_confidence": self.extraction_confidence,
            "extraction_method": self.extraction_method,
            "occurrences": [occ.to_dict() for occ in self.occurrences],
            "matches": [match.to_dict() for match in self.matches],
            "llm_response": None if self.llm_response is None else self.llm_response.to_dict(),
            "candidate_names": list(self.candidate_names),
            "reason": self.reason,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> TaxonResult:
        llm_data = data.get("llm_response")
        return TaxonResult(
            source_text=str(data["source_text"]),
            identified=bool(data["identified"]),
            extraction_confidence=float(data["extraction_confidence"]),
            extraction_method=data["extraction_method"],
            occurrences=[Occurrence.from_dict(item) for item in data.get("occurrences", [])],
            matches=[TaxonMatch.from_dict(item) for item in data.get("matches", [])],
            llm_response=None if llm_data is None else LlmEnrichmentResponse.from_dict(llm_data),
            candidate_names=list(data.get("candidate_names", [])),
            reason=str(data.get("reason", "")),
        )
