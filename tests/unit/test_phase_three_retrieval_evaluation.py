import hashlib

import pytest

from product_support_agent.documents import stable_chunk_id, stable_document_id
from product_support_agent.retrieval_evaluation import (
    CitationReference,
    RetrievalEvaluationCase,
    evaluate_retrieval,
)
from product_support_agent.search import SearchResult

SOURCE_URL = "https://my.opentext.com/support/products/product-a"


def hit(chunk_id: str, source_url: str = SOURCE_URL) -> SearchResult:
    document_id = stable_document_id("product-a", source_url)
    chunk_index = int.from_bytes(hashlib.sha256(chunk_id.encode()).digest()[:4], "big")
    return SearchResult(
        chunk_id=stable_chunk_id(document_id, chunk_index),
        document_id=document_id,
        source_id="product-a",
        product_id="product-a",
        source_url=source_url,
        title="Reviewed support evidence",
        excerpt=f"Evidence excerpt for {chunk_id}",
        content_hash=f"hash-{chunk_id}",
        chunk_index=chunk_index,
        score=1.0,
    )


def case(
    question_id: str,
    relevant_ids: set[str],
    retrieved_ids: list[str],
    citations: list[CitationReference] | None = None,
) -> RetrievalEvaluationCase:
    retrieved = [hit(chunk_id) for chunk_id in retrieved_ids]
    return RetrievalEvaluationCase(
        question_id=question_id,
        relevant_chunk_ids={hit(chunk_id).chunk_id for chunk_id in relevant_ids},
        retrieved_results=retrieved,
        citations=citations if citations is not None else [],
    )


def test_retrieval_evaluation_passes_at_nine_of_ten_relevant_in_top_five() -> None:
    cases = [
        case(
            f"question-{index}",
            {f"relevant-{index}"},
            [
                f"distractor-{index}-1",
                f"distractor-{index}-2",
                f"distractor-{index}-3",
                f"distractor-{index}-4",
                f"relevant-{index}",
            ],
        )
        for index in range(9)
    ]
    cases.append(
        case(
            "question-9",
            {"relevant-9"},
            [
                "distractor-9-1",
                "distractor-9-2",
                "distractor-9-3",
                "distractor-9-4",
                "distractor-9-5",
                "relevant-9",
            ],
        )
    )

    report = evaluate_retrieval(cases, top_k=5)

    assert report.top_five_relevance_rate == 0.9
    assert report.passed_top_five_threshold is True


def test_retrieval_evaluation_fails_below_ninety_percent_top_five() -> None:
    cases = [
        case(
            f"question-{index}",
            {f"relevant-{index}"},
            [f"relevant-{index}" if index < 8 else f"other-{index}"],
        )
        for index in range(10)
    ]

    report = evaluate_retrieval(cases, top_k=5)

    assert report.top_five_relevance_rate == 0.8
    assert report.passed_top_five_threshold is False


def test_retrieval_evaluation_requires_all_citation_ids_and_urls_to_resolve() -> None:
    case_with_citations = RetrievalEvaluationCase(
        question_id="citation-integrity",
        relevant_chunk_ids={"retrieved-chunk"},
        retrieved_results=[hit("retrieved-chunk")],
        citations=[
            CitationReference(
                chunk_id=hit("retrieved-chunk").chunk_id,
                source_url=SOURCE_URL,
            ),
            CitationReference(
                chunk_id=hit("retrieved-chunk").chunk_id,
                source_url=f"{SOURCE_URL}/different",
            ),
            CitationReference(
                chunk_id=hit("missing-chunk").chunk_id,
                source_url=SOURCE_URL,
            ),
        ],
    )

    report = evaluate_retrieval([case_with_citations], top_k=5)

    assert report.citation_integrity_rate == pytest.approx(1 / 3)
    assert report.passed_citation_threshold is False


def test_retrieval_evaluation_accepts_citations_bound_to_retrieved_url() -> None:
    case_with_citation = RetrievalEvaluationCase(
        question_id="valid-citation",
        relevant_chunk_ids={"retrieved-chunk"},
        retrieved_results=[hit("retrieved-chunk")],
        citations=[
            CitationReference(
                chunk_id=hit("retrieved-chunk").chunk_id,
                source_url=SOURCE_URL,
            )
        ],
    )

    report = evaluate_retrieval([case_with_citation], top_k=5)

    assert report.citation_integrity_rate == 1.0
    assert report.passed_citation_threshold is True


def test_retrieval_evaluation_rejects_empty_review_set() -> None:
    with pytest.raises(ValueError):
        evaluate_retrieval([], top_k=5)


def test_retrieval_evaluation_rejects_a_non_top_five_threshold() -> None:
    with pytest.raises(ValueError, match="top_k must be 5"):
        evaluate_retrieval([case("question", {"relevant"}, ["relevant"])], top_k=4)


def test_retrieval_evaluation_does_not_pass_when_no_citations_were_reviewed() -> None:
    report = evaluate_retrieval([case("question", {"relevant"}, ["relevant"])])

    assert report.citation_integrity_rate == 0.0
    assert report.passed_citation_threshold is False


def test_retrieval_evaluation_accepts_an_empty_result_for_unanswerable_case() -> None:
    unanswerable = RetrievalEvaluationCase(
        question_id="no-relevant-source",
        relevant_chunk_ids=set(),
        retrieved_results=[],
        citations=[],
    )

    report = evaluate_retrieval([unanswerable])

    assert report.top_five_relevance_rate == 1.0
