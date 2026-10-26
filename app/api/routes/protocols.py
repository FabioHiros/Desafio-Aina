from uuid import UUID

from fastapi import APIRouter, status

from app.api.dependencies import ProtocolServiceDep
from app.models.protocol import SessionStatus
from app.schemas.common import ErrorResponse
from app.schemas.protocol import AnswerIn, ProtocolSessionOut, ProtocolStart, QuestionOut, ScaleOptionOut
from app.services.protocol import SessionState

router = APIRouter(tags=["protocols"])


@router.post(
    "/patients/{patient_id}/protocols",
    status_code=status.HTTP_201_CREATED,
    response_model=ProtocolSessionOut,
    responses={
        403: {"model": ErrorResponse, "description": "Paciente não aceitou os termos (missing_consent)."},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "Sessão ou jornada já em andamento."},
        422: {"model": ErrorResponse},
    },
)
def start_protocol(patient_id: UUID, body: ProtocolStart, service: ProtocolServiceDep) -> ProtocolSessionOut:
    return to_out(service.start(str(patient_id), body.template_id, body.objetivo))


@router.post(
    "/protocol-sessions/{session_id}/answers",
    response_model=ProtocolSessionOut,
    responses={
        404: {"model": ErrorResponse},
        409: {
            "model": ErrorResponse,
            "description": "Fora de ordem, resposta já gravada com outro valor ou sessão concluída.",
        },
        422: {"model": ErrorResponse, "description": "Valor fora da escala ou payload inválido."},
    },
)
def answer(session_id: UUID, body: AnswerIn, service: ProtocolServiceDep) -> ProtocolSessionOut:
    return to_out(service.answer(str(session_id), body.question_id, body.value))


@router.get(
    "/protocol-sessions/{session_id}", response_model=ProtocolSessionOut, responses={404: {"model": ErrorResponse}}
)
def get_session(session_id: UUID, service: ProtocolServiceDep) -> ProtocolSessionOut:
    return to_out(service.get(str(session_id)))


def to_out(state: SessionState) -> ProtocolSessionOut:
    session, template, pending = state.session, state.template, state.next_question
    completed = session.status is SessionStatus.COMPLETED
    question = None
    if pending is not None:
        question = QuestionOut(
            question_id=pending.question.id,
            text=pending.question.text,
            position=pending.position,
            total=len(template.questions),
            instructions=template.instructions,
            scale=[ScaleOptionOut(value=o.value, label=o.label) for o in template.scale],
        )
    return ProtocolSessionOut(
        session_id=session.session_id,
        template_id=session.template_id,
        status=session.status,
        next_question=question,
        score=session.score if completed else None,
        ended_by_skip=session.ended_by_skip if completed else None,
        journey_id=state.journey.journey_id if state.journey is not None else None,
    )
