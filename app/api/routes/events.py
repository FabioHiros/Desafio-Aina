from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import EventServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.event import EventOut

router = APIRouter(tags=["events"])


@router.get("/events", response_model=list[EventOut], responses={422: {"model": ErrorResponse}})
def list_events(
    service: EventServiceDep, patient_id: Annotated[UUID, Query(description="Id interno do paciente.")]
) -> list[EventOut]:
    """Trilha do paciente em ordem de gravação.

    Recebe o id interno (conforme o enunciado) e filtra pelo hash. Id sem eventos devolve lista vazia:
    a resposta não revela se um paciente existe.
    """
    return [EventOut.from_domain(event) for event in service.trail(str(patient_id))]
