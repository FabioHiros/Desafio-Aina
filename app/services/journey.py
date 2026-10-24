"""Jornada: consulta e conclusão de tarefas. A criação acontece em ProtocolService, ao concluir o protocolo."""

from app.core.clock import Clock
from app.core.errors import JourneyNotFoundError, PatientNotFoundError, TaskNotFoundError
from app.models.events import TaskCompleted
from app.models.journey import Journey, TaskStatus
from app.repositories.interfaces import UnitOfWork
from app.services.event_store import EventStore


class JourneyService:
    def __init__(self, uow: UnitOfWork, event_store: EventStore, clock: Clock) -> None:
        self._uow = uow
        self._event_store = event_store
        self._clock = clock

    def current_for_patient(self, patient_id: str) -> Journey:
        """A jornada em andamento, ou a mais recente se nenhuma estiver em andamento."""
        with self._uow as uow:
            if uow.patients.get(patient_id) is None:
                raise PatientNotFoundError
            journey = uow.journeys.get_current_for_patient(patient_id)
            if journey is None:
                raise JourneyNotFoundError
            return journey

    def complete_task(self, journey_id: str, task_id: str) -> Journey:
        """Idempotente: concluir de novo não altera a data nem gera evento. A jornada é concluída junto com a
        última tarefa."""
        with self._uow as uow:
            journey = uow.journeys.get(journey_id)
            if journey is None:
                raise JourneyNotFoundError
            task = journey.task(task_id)
            if task is None:
                raise TaskNotFoundError
            if task.status is TaskStatus.COMPLETED:
                return journey

            now = self._clock.now()
            uow.journeys.complete_task(task_id, now)
            self._event_store.append(uow, journey.patient_id, TaskCompleted(journey_id=journey_id, task_id=task_id))
            updated = self._reload(uow, journey_id)
            if not updated.has_active_task:
                uow.journeys.complete(journey_id, now)
                updated = self._reload(uow, journey_id)
            uow.commit()
            return updated

    @staticmethod
    def _reload(uow: UnitOfWork, journey_id: str) -> Journey:
        journey = uow.journeys.get(journey_id)
        if journey is None:
            raise JourneyNotFoundError
        return journey
