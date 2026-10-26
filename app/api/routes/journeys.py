from uuid import UUID

from fastapi import APIRouter

from app.api.dependencies import JourneyServiceDep
from app.models.journey import Journey
from app.schemas.common import ErrorResponse
from app.schemas.journey import JourneyOut, TaskOut, TaskUpdate

router = APIRouter(tags=["journeys"])


@router.get("/patients/{patient_id}/journey", response_model=JourneyOut, responses={404: {"model": ErrorResponse}})
def get_journey(patient_id: UUID, service: JourneyServiceDep) -> JourneyOut:
    return to_out(service.current_for_patient(str(patient_id)))


@router.patch(
    "/journeys/{journey_id}/tasks/{task_id}",
    response_model=JourneyOut,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def complete_task(journey_id: UUID, task_id: UUID, _: TaskUpdate, service: JourneyServiceDep) -> JourneyOut:
    return to_out(service.complete_task(str(journey_id), str(task_id)))


def to_out(journey: Journey) -> JourneyOut:
    return JourneyOut(
        journey_id=journey.journey_id,
        session_id=journey.session_id,
        objetivo=journey.objetivo,
        status=journey.status,
        created_at=journey.created_at,
        completed_at=journey.completed_at,
        tarefas=[
            TaskOut(id=task.task_id, titulo=task.titulo, status=task.status, completed_at=task.completed_at)
            for task in journey.tasks
        ],
    )
