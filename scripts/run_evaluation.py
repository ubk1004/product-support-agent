"""Evaluate the live chat API and hybrid retrieval against a small versioned question set."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError
from azure.search.documents.aio import SearchClient
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from product_support_agent.catalog import validate_source_url
from product_support_agent.chat import (
    NO_EVIDENCE_ANSWER,
    ChatResponse,
    EmbeddedSearchRetriever,
)
from product_support_agent.config import ModelAndSearchSettings
from product_support_agent.documents import HTML_PARSER_VERSION
from product_support_agent.embeddings import OpenAICompatibleEmbedder
from product_support_agent.indexing import DocumentIndexingError
from product_support_agent.search import (
    DEFAULT_SEARCH_TOP,
    AzureAISearchProvider,
    build_versioned_index_name,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTION_SET = ROOT / "tests" / "evaluation" / "questions-v1.json"
DEFAULT_REPORT = ROOT / "docs" / "operations" / "phase-6-evaluation-v1.md"
MIN_TOP_FIVE_HIT_RATE = 0.8


class EvaluationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2_000)
    expected_source_urls: list[str]
    answerable: bool

    @model_validator(mode="after")
    def validate_expected_sources(self) -> EvaluationQuestion:
        if self.answerable != bool(self.expected_source_urls):
            raise ValueError(
                "answerable questions need expected sources; unanswerable ones must not"
            )
        if any(not validate_source_url(url) for url in self.expected_source_urls):
            raise ValueError("evaluation source URL is not allowlisted")
        return self


class EvaluationQuestionSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    questions: list[EvaluationQuestion] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_phase_six_shape(self) -> EvaluationQuestionSet:
        question_ids = [question.id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("evaluation question IDs must be unique")
        answerable_count = sum(question.answerable for question in self.questions)
        unanswerable_count = len(self.questions) - answerable_count
        if answerable_count != 15 or unanswerable_count != 3:
            raise ValueError(
                "Phase 6 evaluation requires 15 answerable and 3 unanswerable questions"
            )
        return self


@dataclass(frozen=True)
class CaseResult:
    question_id: str
    answerable: bool
    top_five_hit: bool | None
    retrieved_count: int
    citations: int
    valid_citations: int
    refused: bool


class EvaluationError(RuntimeError):
    pass


def _load_questions(path: Path) -> EvaluationQuestionSet:
    try:
        return EvaluationQuestionSet.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise EvaluationError(f"unable to load evaluation set: {path}") from error


def _build_retriever(
    settings: ModelAndSearchSettings,
) -> tuple[EmbeddedSearchRetriever, AzureAISearchProvider]:
    index_name = build_versioned_index_name(
        settings.demo_index_base,
        embedding_model_version=settings.embedding_model_version,
        embedding_dimensions=settings.embedding_dimensions,
        parser_version=HTML_PARSER_VERSION,
    )
    credential = AzureKeyCredential(settings.search_key.get_secret_value())
    provider = AzureAISearchProvider(
        SearchClient(settings.search_endpoint, index_name, credential),
        embedding_dimensions=settings.embedding_dimensions,
        embedding_model_version=settings.embedding_model_version,
    )
    embedder = OpenAICompatibleEmbedder(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key.get_secret_value(),
        deployment=settings.embedding_deployment,
        model_version=settings.embedding_model_version,
        dimensions=settings.embedding_dimensions,
    )
    return EmbeddedSearchRetriever(embedder=embedder, search=provider), provider


async def _evaluate(
    questions: EvaluationQuestionSet,
    *,
    api_url: str,
    settings: ModelAndSearchSettings,
) -> list[CaseResult]:
    retriever, provider = _build_retriever(settings)
    outcomes: list[CaseResult] = []
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            for question in questions.questions:
                retrieved = await retriever.search(
                    question.question,
                    product_ids=[question.product_id],
                    top=DEFAULT_SEARCH_TOP,
                )
                response = await client.post(
                    f"{api_url.rstrip('/')}/chat",
                    json={
                        "message": question.question,
                        "product_ids": [question.product_id],
                    },
                )
                if response.status_code != 200:
                    raise EvaluationError(
                        f"{question.id}: chat API returned HTTP {response.status_code}"
                    )
                try:
                    chat = ChatResponse.model_validate(response.json())
                except (ValueError, ValidationError) as error:
                    raise EvaluationError(f"{question.id}: invalid chat response") from error

                retrieved_urls = {str(result.source_url) for result in retrieved}
                valid_citations = sum(
                    citation.source_url in retrieved_urls for citation in chat.citations
                )
                expected_urls = set(question.expected_source_urls)
                hit = (
                    any(str(result.source_url) in expected_urls for result in retrieved[:5])
                    if question.answerable
                    else None
                )
                outcomes.append(
                    CaseResult(
                        question_id=question.id,
                        answerable=question.answerable,
                        top_five_hit=hit,
                        retrieved_count=len(retrieved),
                        citations=len(chat.citations),
                        valid_citations=valid_citations,
                        refused=(
                            not question.answerable
                            and chat.answer == NO_EVIDENCE_ANSWER
                            and not chat.citations
                        ),
                    )
                )
    finally:
        await provider.close()
    return outcomes


def _render_report(
    questions: EvaluationQuestionSet,
    outcomes: list[CaseResult],
    *,
    semantic_note: str,
) -> str:
    answerable = [result for result in outcomes if result.answerable]
    unanswerable = [result for result in outcomes if not result.answerable]
    top_five_hits = sum(result.top_five_hit is True for result in answerable)
    citation_count = sum(result.citations for result in outcomes)
    valid_citations = sum(result.valid_citations for result in outcomes)
    refusals = sum(result.refused for result in unanswerable)
    hit_rate = top_five_hits / len(answerable)
    citation_rate = valid_citations / citation_count if citation_count else 0.0

    lines = [
        "# Phase 6 evaluation v1",
        "",
        f"Run date: {date.today().isoformat()}",
        f"Question set: `{questions.version}` ({len(answerable)} answerable, "
        f"{len(unanswerable)} unanswerable)",
        "Retrieval mode: existing hybrid text/vector Search, top five",
        f"Semantic reranking: {semantic_note}",
        "",
        "| Measure | Result | Target |",
        "|---|---:|---:|",
        f"| Expected-source hit in top five | {top_five_hits}/{len(answerable)} "
        f"({hit_rate:.1%}) | >= 80% |",
        f"| Citations matching direct top-five retrieved URLs | {valid_citations}/{citation_count} "
        f"({citation_rate:.1%}) | 100% |",
        f"| Unanswerable questions refused with no citations | {refusals}/{len(unanswerable)} "
        "| 3/3 |",
        "",
        "No evaluation question or model response text is included in this report.",
        "",
        "| Case | Product | Top-five expected-source hit | Retrieved | Citations | "
        "Valid citations | Refused |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for question, result in zip(questions.questions, outcomes, strict=True):
        hit = "n/a" if result.top_five_hit is None else ("yes" if result.top_five_hit else "no")
        refused = "yes" if result.refused else "no" if not result.answerable else "n/a"
        lines.append(
            f"| {result.question_id} | {question.product_id} | {hit} | "
            f"{result.retrieved_count} | {result.citations} | {result.valid_citations} | "
            f"{refused} |"
        )
    return "\n".join(lines) + "\n"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--question-set", type=Path, default=DEFAULT_QUESTION_SET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    questions = _load_questions(args.question_set)
    settings = ModelAndSearchSettings()  # type: ignore[call-arg]
    outcomes = await _evaluate(questions, api_url=args.api_url, settings=settings)
    semantic_note = (
        "not evaluated; service tier and billing plan could not be verified, "
        "so no semantic-ranker setting was changed"
    )
    report = _render_report(questions, outcomes, semantic_note=semantic_note)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")

    answerable = [result for result in outcomes if result.answerable]
    unanswerable = [result for result in outcomes if not result.answerable]
    top_five_hits = sum(result.top_five_hit is True for result in answerable)
    citation_count = sum(result.citations for result in outcomes)
    valid_citations = sum(result.valid_citations for result in outcomes)
    refusals = sum(result.refused for result in unanswerable)
    hit_rate = top_five_hits / len(answerable)
    citation_rate = valid_citations / citation_count if citation_count else 0.0
    print(f"Report: {args.report}")
    print(f"Top-five expected-source hit: {top_five_hits}/{len(answerable)} ({hit_rate:.1%})")
    print(f"Citation validity: {valid_citations}/{citation_count} ({citation_rate:.1%})")
    print(f"Unanswerable refusals: {refusals}/{len(unanswerable)}")
    return int(
        hit_rate < MIN_TOP_FIVE_HIT_RATE
        or citation_count == 0
        or citation_rate < 1.0
        or refusals != len(unanswerable)
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("Evaluation interrupted.", file=sys.stderr)
        return 130
    except (
        AzureError,
        DocumentIndexingError,
        EvaluationError,
        httpx.HTTPError,
        OSError,
        ValueError,
    ) as error:
        print(f"Evaluation failed ({type(error).__name__}): {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
