"""Evaluate the live chat API and hybrid retrieval against a small versioned question set.

Measures expected-source hits, citation validity (every citation is a retrieved URL), refusals of
unanswerable and adversarial questions, and claim support: a judge model checks that the answer's
claims are supported by the full indexed text of the pages it cites. In the API, "grounded" only
means at least one valid citation exists; claim support is the stronger check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError
from azure.search.documents.aio import SearchClient
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from product_support_agent.catalog import validate_source_url
from product_support_agent.chat import (
    NO_EVIDENCE_ANSWER,
    ChatResponse,
    EmbeddedSearchRetriever,
)
from product_support_agent.config import ModelAndSearchSettings
from product_support_agent.documents import HTML_PARSER_VERSION, stable_document_id
from product_support_agent.embeddings import OpenAICompatibleEmbedder
from product_support_agent.indexing import DocumentIndexingError
from product_support_agent.search import (
    DEFAULT_SEARCH_TOP,
    AzureAISearchProvider,
    build_versioned_index_name,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTION_SET = ROOT / "tests" / "evaluation" / "questions-v2.json"
DEFAULT_REPORT = ROOT / "docs" / "operations" / "phase-6-evaluation-v2.md"
MIN_TOP_FIVE_HIT_RATE = 0.8
MIN_CLAIM_SUPPORT_RATE = 0.8
MAX_JUDGE_SOURCE_CHARS = 60_000
JUDGE_INSTRUCTIONS = (
    "You check whether an answer is supported by its sources. Use only the sources below. "
    "The answer cites sources with markers such as [E1]. Reply with only a JSON object "
    'such as {"supported": true}. Say true only if every factual claim in the answer is '
    "stated or directly implied by the sources. Say false if any claim is missing from the "
    "sources, contradicts them, or the sources are empty."
)


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
        if answerable_count == 0 or answerable_count == len(self.questions):
            raise ValueError(
                "the evaluation needs both answerable and unanswerable (refusal) questions"
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
    claims_supported: bool | None = None


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


async def _cited_source_text(provider: AzureAISearchProvider, product_id: str, url: str) -> str:
    """The full indexed text of a cited page, in chunk order."""
    document_id = stable_document_id(product_id, url)
    results = await provider.client.search(
        search_text="*",
        filter=f"document_id eq '{document_id}'",
        select=["content", "chunk_index"],
        top=100,
    )
    chunks = sorted([item async for item in results], key=lambda item: int(item["chunk_index"]))
    return "\n".join(str(chunk["content"]) for chunk in chunks)[:MAX_JUDGE_SOURCE_CHARS]


def _parse_verdict(text: str) -> bool:
    body = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    verdict = json.loads(body)
    return isinstance(verdict, dict) and verdict.get("supported") is True


async def _claims_supported(
    judge: AsyncOpenAI,
    deployment: str,
    provider: AzureAISearchProvider,
    question: EvaluationQuestion,
    chat: ChatResponse,
) -> bool:
    sources = [
        f"[{citation.evidence_id}]\n"
        + await _cited_source_text(provider, question.product_id, citation.source_url)
        for citation in chat.citations
    ]
    prompt = "\n\n".join([JUDGE_INSTRUCTIONS, "SOURCES", *sources, "ANSWER", chat.answer])
    try:
        response = await judge.responses.create(model=deployment, input=prompt)
        return _parse_verdict(response.output_text)
    except (OpenAIError, ValueError) as error:
        raise EvaluationError(f"{question.id}: claim-support judge failed") from error


async def _evaluate(
    questions: EvaluationQuestionSet,
    *,
    api_url: str,
    settings: ModelAndSearchSettings,
) -> list[CaseResult]:
    retriever, provider = _build_retriever(settings)
    judge = AsyncOpenAI(
        base_url=settings.chat_base_url, api_key=settings.chat_api_key.get_secret_value()
    )
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
                supported = (
                    await _claims_supported(
                        judge, settings.chat_deployment, provider, question, chat
                    )
                    if question.answerable and chat.citations
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
                        claims_supported=supported,
                    )
                )
    finally:
        await judge.close()
        await provider.close()
    return outcomes


@dataclass(frozen=True)
class Summary:
    answerable: int
    top_five_hits: int
    citations: int
    valid_citations: int
    judged: int
    claims_supported: int
    unanswerable: int
    refusals: int

    @property
    def hit_rate(self) -> float:
        return self.top_five_hits / self.answerable

    @property
    def citation_rate(self) -> float:
        return self.valid_citations / self.citations if self.citations else 0.0

    @property
    def support_rate(self) -> float:
        return self.claims_supported / self.judged if self.judged else 0.0

    @property
    def passed(self) -> bool:
        return (
            self.hit_rate >= MIN_TOP_FIVE_HIT_RATE
            and self.citations > 0
            and self.citation_rate == 1.0
            and self.support_rate >= MIN_CLAIM_SUPPORT_RATE
            and self.refusals == self.unanswerable
        )


def _summarize(outcomes: list[CaseResult]) -> Summary:
    answerable = [result for result in outcomes if result.answerable]
    unanswerable = [result for result in outcomes if not result.answerable]
    judged = [result for result in answerable if result.claims_supported is not None]
    return Summary(
        answerable=len(answerable),
        top_five_hits=sum(result.top_five_hit is True for result in answerable),
        citations=sum(result.citations for result in outcomes),
        valid_citations=sum(result.valid_citations for result in outcomes),
        judged=len(judged),
        claims_supported=sum(result.claims_supported is True for result in judged),
        unanswerable=len(unanswerable),
        refusals=sum(result.refused for result in unanswerable),
    )


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


def _render_report(
    questions: EvaluationQuestionSet,
    outcomes: list[CaseResult],
    *,
    semantic_note: str,
) -> str:
    total = _summarize(outcomes)
    lines = [
        "# Phase 6 evaluation v2",
        "",
        f"Run date: {date.today().isoformat()}",
        f"Question set: `{questions.version}` ({total.answerable} answerable, "
        f"{total.unanswerable} unanswerable or adversarial)",
        "Retrieval mode: existing hybrid text/vector Search, top five",
        f"Semantic reranking: {semantic_note}",
        "",
        "| Measure | Result | Target |",
        "|---|---:|---:|",
        f"| Expected-source hit in top five | {total.top_five_hits}/{total.answerable} "
        f"({total.hit_rate:.1%}) | >= 80% |",
        f"| Citations matching direct top-five retrieved URLs | "
        f"{total.valid_citations}/{total.citations} ({total.citation_rate:.1%}) | 100% |",
        f"| Answers whose claims the cited sources support | "
        f"{total.claims_supported}/{total.judged} ({total.support_rate:.1%}) | >= 80% |",
        f"| Unanswerable and adversarial questions refused with no citations | "
        f"{total.refusals}/{total.unanswerable} | all |",
        "",
        "Claim support is judged by a model against the full indexed text of each cited page. "
        "It is a screening check, not a guarantee, and needs periodic human review.",
        "",
        "No evaluation question or model response text is included in this report.",
        "",
        "| Case | Product | Top-five expected-source hit | Retrieved | Citations | "
        "Valid citations | Claims supported | Refused |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for question, result in zip(questions.questions, outcomes, strict=True):
        refused = _yes_no(result.refused) if not result.answerable else "n/a"
        lines.append(
            f"| {result.question_id} | {question.product_id} | {_yes_no(result.top_five_hit)} | "
            f"{result.retrieved_count} | {result.citations} | {result.valid_citations} | "
            f"{_yes_no(result.claims_supported)} | {refused} |"
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

    total = _summarize(outcomes)
    print(f"Report: {args.report}")
    print(
        f"Top-five expected-source hit: {total.top_five_hits}/{total.answerable} "
        f"({total.hit_rate:.1%})"
    )
    print(
        f"Citation validity: {total.valid_citations}/{total.citations} ({total.citation_rate:.1%})"
    )
    print(f"Claim support: {total.claims_supported}/{total.judged} ({total.support_rate:.1%})")
    print(f"Refusals: {total.refusals}/{total.unanswerable}")
    return 0 if total.passed else 1


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
