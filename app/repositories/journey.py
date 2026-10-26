from datetime import datetime

from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import JourneyAlreadyActiveError
from app.models.journey import Journey, JourneyStatus, Task, TaskStatus
from app.repositories.tables import JourneyRow, JourneyTaskRow


class SqlAlchemyJourneyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, journey: Journey) -> None:
        self._session.add(
            JourneyRow(
                journey_id=journey.journey_id,
                patient_id=journey.patient_id,
                session_id=journey.session_id,
                objetivo=journey.objetivo,
                status=journey.status.value,
                created_at=journey.created_at,
                completed_at=journey.completed_at,
                tasks=[
                    JourneyTaskRow(
                        task_id=task.task_id,
                        position=task.position,
                        titulo=task.titulo,
                        status=task.status.value,
                        completed_at=task.completed_at,
                    )
                    for task in journey.tasks
                ],
            )
        )
        try:
            self._session.flush()
        except IntegrityError as exc:
            if "journeys.patient_id" in str(exc.orig):
                raise JourneyAlreadyActiveError from None
            raise

    def get(self, journey_id: str) -> Journey | None:
        row = self._session.get(JourneyRow, journey_id)
        return _to_domain(row) if row is not None else None

    def get_by_session(self, session_id: str) -> Journey | None:
        row = self._session.scalar(select(JourneyRow).where(JourneyRow.session_id == session_id))
        return _to_domain(row) if row is not None else None

    def get_current_for_patient(self, patient_id: str) -> Journey | None:
        """A jornada em andamento, ou a mais recente se nenhuma estiver em andamento."""
        active_first = case((JourneyRow.status == JourneyStatus.IN_PROGRESS.value, 0), else_=1)
        query = (
            select(JourneyRow)
            .where(JourneyRow.patient_id == patient_id)
            .order_by(active_first, JourneyRow.created_at.desc())
            .limit(1)
        )
        row = self._session.scalar(query)
        return _to_domain(row) if row is not None else None

    def has_active(self, patient_id: str) -> bool:
        journey = self.get_current_for_patient(patient_id)
        return journey is not None and journey.status is JourneyStatus.IN_PROGRESS

    def complete_task(self, task_id: str, completed_at: datetime) -> None:
        row = self._session.get_one(JourneyTaskRow, task_id)
        row.status = TaskStatus.COMPLETED.value
        row.completed_at = completed_at
        self._session.flush()

    def complete(self, journey_id: str, completed_at: datetime) -> None:
        row = self._session.get_one(JourneyRow, journey_id)
        row.status = JourneyStatus.COMPLETED.value
        row.completed_at = completed_at
        self._session.flush()


def _to_domain(row: JourneyRow) -> Journey:
    return Journey(
        journey_id=row.journey_id,
        patient_id=row.patient_id,
        session_id=row.session_id,
        objetivo=row.objetivo,
        status=JourneyStatus(row.status),
        created_at=row.created_at,
        completed_at=row.completed_at,
        tasks=tuple(
            Task(
                task_id=t.task_id,
                position=t.position,
                titulo=t.titulo,
                status=TaskStatus(t.status),
                completed_at=t.completed_at,
            )
            for t in row.tasks
        ),
    )
