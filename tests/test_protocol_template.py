from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.models.protocol import Completed, NextQuestion, ProtocolTemplate

ROOT = Path(__file__).resolve().parent.parent
SCALE = [{"value": v, "label": str(v)} for v in range(4)]


def template(questions: int = 9, rules: list[dict[str, Any]] | None = None, **extra: Any) -> ProtocolTemplate:
    return ProtocolTemplate.model_validate(
        {
            "template_id": "test",
            "name": "Teste",
            "scale": SCALE,
            "questions": [{"id": f"q{i}", "text": f"Pergunta {i}"} for i in range(1, questions + 1)],
            "rules": rules if rules is not None else [PHQ2_RULE],
            **extra,
        }
    )


PHQ2_RULE = {"after": "q2", "when": {"sum": ["q1", "q2"], "op": "lt", "value": 3}, "action": "end_block"}


def answers(*values: int) -> dict[str, int]:
    return {f"q{i}": value for i, value in enumerate(values, start=1)}


def test_first_question_when_nothing_answered() -> None:
    progress = template().evaluate({})
    assert progress == NextQuestion(question=template().questions[0], position=1)


def test_rule_is_not_evaluated_before_its_question() -> None:
    progress = template().evaluate(answers(0))
    assert isinstance(progress, NextQuestion)
    assert progress.question.id == "q2"


@pytest.mark.parametrize(("q1", "q2"), [(0, 0), (1, 1), (0, 2), (2, 0)])
def test_phq2_skip_when_sum_below_3(q1: int, q2: int) -> None:
    assert template().evaluate(answers(q1, q2)) == Completed(score=q1 + q2, ended_by_skip=True)


@pytest.mark.parametrize(("q1", "q2"), [(0, 3), (1, 2), (3, 3)])
def test_phq2_continues_when_sum_is_3_or_more(q1: int, q2: int) -> None:
    progress = template().evaluate(answers(q1, q2))
    assert isinstance(progress, NextQuestion)
    assert (progress.question.id, progress.position) == ("q3", 3)


def test_full_protocol_completes_with_total_score() -> None:
    values = (2, 1, 3, 0, 1, 2, 3, 1, 0)
    assert template().evaluate(answers(*values)) == Completed(score=sum(values), ended_by_skip=False)


def test_template_without_rules_never_skips() -> None:
    assert template(rules=[]).evaluate(answers(0, 0)) == NextQuestion(template().questions[2], 3)


@pytest.mark.parametrize(
    ("op", "threshold", "q1", "skips"),
    [("lte", 3, 3, True), ("gt", 3, 3, False), ("gte", 2, 1, False), ("eq", 2, 2, True)],
)
def test_other_comparisons(op: str, threshold: int, q1: int, skips: bool) -> None:
    rule = {"after": "q1", "when": {"sum": ["q1"], "op": op, "value": threshold}, "action": "end_block"}
    progress = template(rules=[rule]).evaluate({"q1": q1})
    assert isinstance(progress, Completed) is skips


def test_rules_are_generic_for_any_template() -> None:
    """Outro template, outra regra: o mesmo motor, sem nenhuma mudança de código."""
    rule = {"after": "q1", "when": {"sum": ["q1"], "op": "gte", "value": 3}, "action": "end_block"}
    other = template(questions=3, rules=[rule], template_id="outro")

    assert other.evaluate({"q1": 3}) == Completed(score=3, ended_by_skip=True)
    assert other.evaluate(answers(1, 1, 1)) == Completed(score=3, ended_by_skip=False)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"rules": [{**PHQ2_RULE, "after": "q99"}]}, "pergunta inexistente: q99"),
        ({"rules": [{**PHQ2_RULE, "when": {"sum": ["q1", "q9"], "op": "lt", "value": 3}}]}, "ainda não foi respondida"),
        ({"rules": [{**PHQ2_RULE, "when": {"sum": ["q1"], "op": "between", "value": 3}}]}, "op"),
        ({"rules": [{**PHQ2_RULE, "action": "jump"}]}, "action"),
        ({"questions": [{"id": "q1", "text": "a"}, {"id": "q1", "text": "b"}], "rules": []}, "repetidos"),
        ({"scale": [{"value": 0, "label": "a"}, {"value": 0, "label": "b"}]}, "repetidos"),
        ({"questions": []}, "questions"),
        ({"unexpected": True}, "unexpected"),
    ],
)
def test_invalid_templates_are_rejected(overrides: dict[str, Any], message: str) -> None:
    data: dict[str, Any] = {
        "template_id": "test",
        "name": "Teste",
        "scale": SCALE,
        "questions": [{"id": f"q{i}", "text": "x"} for i in range(1, 10)],
        "rules": [PHQ2_RULE],
    }
    with pytest.raises(ValidationError, match=message):
        ProtocolTemplate.model_validate({**data, **overrides})


def test_phq9_template_matches_the_specification() -> None:
    phq9 = ProtocolTemplate.model_validate_json(
        (ROOT / "templates" / "protocols" / "phq9.json").read_text(encoding="utf-8")
    )

    assert phq9.template_id == "phq9"
    assert [q.id for q in phq9.questions] == [f"q{i}" for i in range(1, 10)]
    assert [(o.value, o.label) for o in phq9.scale] == [
        (0, "Nenhuma vez"),
        (1, "Vários dias"),
        (2, "Mais da metade dos dias"),
        (3, "Quase todos os dias"),
    ]
    assert phq9.questions[0].text == "Pouco interesse ou prazer em fazer as coisas"
    assert phq9.questions[8].text.startswith("Pensamentos de que estaria melhor morto(a)")
    assert phq9.evaluate({"q1": 1, "q2": 1}) == Completed(score=2, ended_by_skip=True)
    assert isinstance(phq9.evaluate({"q1": 1, "q2": 2}), NextQuestion)
