import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Comparison = Literal["lt", "lte", "gt", "gte", "eq"]

_COMPARATORS: dict[Comparison, Callable[[int, int], bool]] = {
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
    "eq": operator.eq,
}


class _TemplateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScaleOption(_TemplateModel):
    value: int
    label: str = Field(min_length=1)


class Question(_TemplateModel):
    id: str = Field(min_length=1, max_length=50)
    text: str = Field(min_length=1)


class SumCondition(_TemplateModel):
    sum: tuple[str, ...] = Field(min_length=1)
    op: Comparison
    value: int

    def matches(self, answers: Mapping[str, int]) -> bool:
        total = sum(answers[question_id] for question_id in self.sum)
        return _COMPARATORS[self.op](total, self.value)


class SkipRule(_TemplateModel):
    after: str
    when: SumCondition
    action: Literal["end_block"]


@dataclass(frozen=True, slots=True)
class NextQuestion:
    question: Question
    position: int


@dataclass(frozen=True, slots=True)
class Completed:
    score: int
    ended_by_skip: bool


Progress = NextQuestion | Completed


class ProtocolTemplate(_TemplateModel):
    template_id: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1)
    instructions: str = ""
    scale: tuple[ScaleOption, ...] = Field(min_length=1)
    questions: tuple[Question, ...] = Field(min_length=1)
    rules: tuple[SkipRule, ...] = ()

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        """Um template inconsistente falha ao carregar, não no meio da sessão de um paciente."""
        values = [option.value for option in self.scale]
        if len(set(values)) != len(values):
            raise ValueError("valores da escala repetidos")

        order = {question.id: index for index, question in enumerate(self.questions)}
        if len(order) != len(self.questions):
            raise ValueError("ids de pergunta repetidos")

        for rule in self.rules:
            if rule.after not in order:
                raise ValueError(f"regra após pergunta inexistente: {rule.after}")
            for question_id in rule.when.sum:
                if question_id not in order:
                    raise ValueError(f"regra soma pergunta inexistente: {question_id}")
                if order[question_id] > order[rule.after]:
                    raise ValueError(f"regra após {rule.after} soma {question_id}, que ainda não foi respondida")
        return self

    @property
    def scale_values(self) -> frozenset[int]:
        return frozenset(option.value for option in self.scale)

    def evaluate(self, answers: Mapping[str, int]) -> Progress:
        """Dado o que já foi respondido, decide: próxima pergunta, fim por skip ou fim normal.

        Percorre as perguntas em ordem; após cada pergunta respondida, aplica as regras ligadas a ela.
        """
        for position, question in enumerate(self.questions, start=1):
            if question.id not in answers:
                return NextQuestion(question=question, position=position)
            for rule in self.rules:
                if rule.after == question.id and rule.when.matches(answers):
                    return Completed(score=self._score(answers), ended_by_skip=True)
        return Completed(score=self._score(answers), ended_by_skip=False)

    def _score(self, answers: Mapping[str, int]) -> int:
        return sum(answers[q.id] for q in self.questions if q.id in answers)


class SessionStatus(StrEnum):
    IN_PROGRESS = "em_andamento"
    COMPLETED = "concluido"


@dataclass(frozen=True, slots=True)
class Answer:
    question_id: str
    position: int
    value: int
    answered_at: datetime


@dataclass(frozen=True, slots=True)
class ProtocolSession:
    session_id: str
    patient_id: str
    template_id: str
    objetivo: str = field(repr=False)
    status: SessionStatus
    score: int | None
    ended_by_skip: bool
    started_at: datetime
    completed_at: datetime | None
    answers: tuple[Answer, ...] = ()

    @property
    def answer_values(self) -> dict[str, int]:
        return {answer.question_id: answer.value for answer in self.answers}

    def answer_for(self, question_id: str) -> Answer | None:
        return next((answer for answer in self.answers if answer.question_id == question_id), None)
