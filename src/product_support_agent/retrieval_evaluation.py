from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from product_support_agent.catalog import validate_source_url
from product_support_agent.search import SearchResult

MIN_TOP_FIVE_RELEVANCE_RATE = 0.9
MIN_CITATION_INTEGRITY_RATE = 1.0
TOP_FIVE = 5


class CitationReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=1)
    source_url: HttpUrl

    @model_validator(mode="after")
    def validate_source_url(self) -> CitationReference:
        if not self.chunk_id.strip():
            raise ValueError("citation chunk ID cannot be empty")
        if not validate_source_url(str(self.source_url)):
            raise ValueError("citation source URL is not allowlisted")
        return self


class RetrievalEvaluationCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str = Field(min_length=1)
    relevant_chunk_ids: set[str]
    retrieved_results: list[SearchResult]
    citations: list[CitationReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> RetrievalEvaluationCase:
        if not self.question_id.strip():
            raise ValueError("question ID cannot be empty")
        if any(not chunk_id.strip() for chunk_id in self.relevant_chunk_ids):
            raise ValueError("relevant chunk IDs cannot be empty")
        retrieved_ids = [result.chunk_id for result in self.retrieved_results]
        if len(retrieved_ids) != len(set(retrieved_ids)):
            raise ValueError("retrieved chunk IDs must be unique within an evaluation case")
        return self


class RetrievalEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    top_five_relevance_rate: float = Field(ge=0.0, le=1.0)
    citation_integrity_rate: float = Field(ge=0.0, le=1.0)
    passed_top_five_threshold: bool
    passed_citation_threshold: bool


def evaluate_retrieval(
    cases: Sequence[RetrievalEvaluationCase],
    *,
    top_k: int = TOP_FIVE,
) -> RetrievalEvaluationReport:
    if not cases:
        raise ValueError("at least one reviewed retrieval case is required")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k != TOP_FIVE:
        raise ValueError(f"top_k must be {TOP_FIVE} for the Phase 3 relevance threshold")
    question_ids = [case.question_id for case in cases]
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("question IDs must be unique within a retrieval evaluation")

    relevant_cases = sum(
        (not case.relevant_chunk_ids and not case.retrieved_results[:top_k])
        or any(
            result.chunk_id in case.relevant_chunk_ids for result in case.retrieved_results[:top_k]
        )
        for case in cases
    )
    top_five_relevance_rate = relevant_cases / len(cases)

    citation_count = 0
    resolved_citation_count = 0
    for case in cases:
        retrieved_by_id = {
            result.chunk_id: str(result.source_url) for result in case.retrieved_results
        }
        for citation in case.citations:
            citation_count += 1
            if retrieved_by_id.get(citation.chunk_id) == str(citation.source_url):
                resolved_citation_count += 1

    citation_integrity_rate = resolved_citation_count / citation_count if citation_count else 0.0
    return RetrievalEvaluationReport(
        top_five_relevance_rate=top_five_relevance_rate,
        citation_integrity_rate=citation_integrity_rate,
        passed_top_five_threshold=top_five_relevance_rate >= MIN_TOP_FIVE_RELEVANCE_RATE,
        passed_citation_threshold=citation_count > 0
        and citation_integrity_rate >= MIN_CITATION_INTEGRITY_RATE,
    )
