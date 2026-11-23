import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_evaluation.py"
QUESTION_SET = Path(__file__).resolve().parents[1] / "evaluation" / "questions-v2.json"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_evaluation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evaluation = load_script()


def case(**overrides):
    values = {
        "question_id": "q",
        "answerable": True,
        "top_five_hit": True,
        "retrieved_count": 5,
        "citations": 1,
        "valid_citations": 1,
        "refused": False,
        "claims_supported": True,
    }
    values.update(overrides)
    return evaluation.CaseResult(**values)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"supported": true}', True),
        ('```json\n{"supported": true}\n```', True),
        ('{"supported": false}', False),
        ('{"supported": "yes"}', False),
        ("[true]", False),
    ],
)
def test_parse_verdict_accepts_only_an_explicit_true(text: str, expected: bool) -> None:
    assert evaluation._parse_verdict(text) is expected


def test_parse_verdict_rejects_non_json() -> None:
    with pytest.raises(ValueError):
        evaluation._parse_verdict("Supported.")


def test_summary_fails_when_claim_support_is_below_target() -> None:
    outcomes = [case(claims_supported=index < 3) for index in range(5)] + [
        case(
            answerable=False,
            top_five_hit=None,
            citations=0,
            valid_citations=0,
            refused=True,
            claims_supported=None,
        )
    ]

    total = evaluation._summarize(outcomes)

    assert total.support_rate == pytest.approx(0.6)
    assert total.passed is False


def test_summary_passes_and_unjudged_answers_are_excluded() -> None:
    outcomes = [case(), case(citations=0, valid_citations=0, claims_supported=None)] + [
        case(
            answerable=False,
            top_five_hit=None,
            citations=0,
            valid_citations=0,
            refused=True,
            claims_supported=None,
        )
    ]

    total = evaluation._summarize(outcomes)

    assert total.judged == 1
    assert total.passed is True


def test_summary_fails_when_an_adversarial_question_is_answered() -> None:
    outcomes = [
        case(),
        case(answerable=False, top_five_hit=None, refused=False, claims_supported=None),
    ]

    assert evaluation._summarize(outcomes).passed is False


def test_question_set_v2_includes_adversarial_refusal_cases() -> None:
    questions = evaluation._load_questions(QUESTION_SET)
    ids = {question.id for question in questions.questions if not question.answerable}

    assert {"n-01", "n-02", "n-03"} <= ids
    assert json.loads(QUESTION_SET.read_text(encoding="utf-8"))["version"] == "phase-6-v2"


def test_report_lists_claim_support_per_case() -> None:
    questions = evaluation._load_questions(QUESTION_SET)
    outcomes = [
        case(question_id=q.id)
        if q.answerable
        else case(
            question_id=q.id,
            answerable=False,
            top_five_hit=None,
            citations=0,
            valid_citations=0,
            refused=True,
            claims_supported=None,
        )
        for q in questions.questions
    ]

    report = evaluation._render_report(questions, outcomes, semantic_note="n/a")

    assert "Answers whose claims the cited sources support | 15/15" in report
    assert "| n-01 | 1146 | n/a | 5 | 0 | 0 | n/a | yes |" in report
