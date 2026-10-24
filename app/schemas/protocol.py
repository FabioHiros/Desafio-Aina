"""Contratos HTTP das sessões de protocolo."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints

from app.models.protocol import SessionStatus


class ProtocolStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=50, examples=["phq9"])
    objetivo: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] = Field(
        description="Objetivo do paciente, em texto livre, anotado na jornada criada ao fim do protocolo.",
        examples=["Perder 5kg em 3 meses"],
    )


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(
        min_length=1,
        max_length=50,
        description="Pergunta que está sendo respondida. Reenviar a mesma resposta é seguro (idempotente).",
        examples=["q1"],
    )
    value: StrictInt = Field(description="Valor da escala do template.", examples=[2])


class ScaleOptionOut(BaseModel):
    value: int
    label: str


class QuestionOut(BaseModel):
    question_id: str
    text: str
    position: int
    total: int
    instructions: str
    scale: list[ScaleOptionOut]


class ProtocolSessionOut(BaseModel):
    """Próxima pergunta enquanto a sessão está em andamento; resultado e jornada quando concluída."""

    session_id: str
    template_id: str
    status: SessionStatus
    next_question: QuestionOut | None
    score: int | None
    ended_by_skip: bool | None
    journey_id: str | None
