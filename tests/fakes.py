from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Self

from app.core.errors import (
    AnswerAlreadyRecordedError,
    JourneyAlreadyActiveError,
    PatientAlreadyExistsError,
    ProtocolInProgressError,
)
from app.models.events import Event, EventName
from app.models.journey import Journey, JourneyStatus, TaskStatus
from app.models.patient import Patient
from app.models.protocol import Answer, ProtocolSession, ProtocolTemplate, SessionStatus


class FakeClock:
    def __init__(self, start: datetime = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)


class InMemoryUnitOfWork:
    def __init__(self) -> None:
        self.patients = InMemoryPatientRepository()
        self.events = InMemoryEventRepository()
        self.sessions = InMemoryProtocolSessionRepository()
        self.journeys = InMemoryJourneyRepository()
        self.commits = 0
        self.rollbacks = 0
        self._snapshot: tuple[Any, ...] | None = None

    def _state(self) -> tuple[Any, ...]:
        return (
            dict(self.patients.patients),
            list(self.events.events),
            dict(self.sessions.sessions),
            dict(self.journeys.journeys),
        )

    def __enter__(self) -> Self:
        self._snapshot = self._state()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.rollback()
        self._snapshot = None

    def commit(self) -> None:
        self.commits += 1
        self._snapshot = self._state()

    def rollback(self) -> None:
        assert self._snapshot is not None, "UnitOfWork usado fora de um bloco `with`"
        if self._state() != self._snapshot:
            self.rollbacks += 1
        patients, events, sessions, journeys = self._snapshot
        self.patients.patients = dict(patients)
        self.events.events = list(events)
        self.sessions.sessions = dict(sessions)
        self.journeys.journeys = dict(journeys)


class InMemoryPatientRepository:
    def __init__(self) -> None:
        self.patients: dict[str, Patient] = {}

    def add(self, patient: Patient) -> None:
        if self.exists_by_phone_hash(patient.phone_hash):
            raise PatientAlreadyExistsError
        self.patients[patient.patient_id] = patient

    def get(self, patient_id: str) -> Patient | None:
        return self.patients.get(patient_id)

    def exists_by_phone_hash(self, phone_hash: str) -> bool:
        return any(p.phone_hash == phone_hash for p in self.patients.values())

    def mark_terms_accepted(self, patient_id: str, accepted_at: datetime) -> None:
        patient = self.patients[patient_id]
        self.patients[patient_id] = replace(patient, terms_accepted=True, terms_accepted_at=accepted_at)


class InMemoryEventRepository:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def append(
        self,
        event_id: str,
        occurred_at: datetime,
        event_name: EventName,
        patient_id_hash: str,
        properties: dict[str, Any],
    ) -> Event:
        event = Event(event_id, len(self.events) + 1, occurred_at, event_name, patient_id_hash, properties)
        self.events.append(event)
        return event

    def list_by_patient_hash(self, patient_id_hash: str) -> list[Event]:
        return [e for e in self.events if e.patient_id_hash == patient_id_hash]

    def exists_since(self, patient_id_hash: str, event_name: EventName, since: datetime) -> bool:
        return any(
            e.patient_id_hash == patient_id_hash and e.event_name == event_name and e.occurred_at > since
            for e in self.events
        )

    def latest_occurred_at(self, patient_id_hash: str, event_name: EventName) -> datetime | None:
        matching = [e for e in self.events if e.patient_id_hash == patient_id_hash and e.event_name == event_name]
        return max((e.occurred_at for e in matching), default=None)


class InMemoryProtocolSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, ProtocolSession] = {}

    def add(self, protocol_session: ProtocolSession) -> None:
        if self.has_in_progress(protocol_session.patient_id):
            raise ProtocolInProgressError
        self.sessions[protocol_session.session_id] = protocol_session

    def get(self, session_id: str) -> ProtocolSession | None:
        return self.sessions.get(session_id)

    def has_in_progress(self, patient_id: str) -> bool:
        return any(s.patient_id == patient_id and s.status is SessionStatus.IN_PROGRESS for s in self.sessions.values())

    def has_completed(self, patient_id: str) -> bool:
        return any(s.patient_id == patient_id and s.status is SessionStatus.COMPLETED for s in self.sessions.values())

    def add_answer(self, session_id: str, answer: Answer) -> None:
        current = self.sessions[session_id]
        if current.answer_for(answer.question_id) is not None:
            raise AnswerAlreadyRecordedError
        self.sessions[session_id] = replace(current, answers=(*current.answers, answer))

    def complete(self, session_id: str, score: int, ended_by_skip: bool, completed_at: datetime) -> None:
        self.sessions[session_id] = replace(
            self.sessions[session_id],
            status=SessionStatus.COMPLETED,
            score=score,
            ended_by_skip=ended_by_skip,
            completed_at=completed_at,
        )


class InMemoryJourneyRepository:
    def __init__(self) -> None:
        self.journeys: dict[str, Journey] = {}

    def add(self, journey: Journey) -> None:
        if self.has_active(journey.patient_id):
            raise JourneyAlreadyActiveError
        self.journeys[journey.journey_id] = journey

    def get(self, journey_id: str) -> Journey | None:
        return self.journeys.get(journey_id)

    def get_by_session(self, session_id: str) -> Journey | None:
        return next((j for j in self.journeys.values() if j.session_id == session_id), None)

    def get_current_for_patient(self, patient_id: str) -> Journey | None:
        mine = [j for j in self.journeys.values() if j.patient_id == patient_id]
        active = [j for j in mine if j.status is JourneyStatus.IN_PROGRESS]
        return max(active or mine, key=lambda j: j.created_at, default=None)

    def has_active(self, patient_id: str) -> bool:
        return any(j.patient_id == patient_id and j.status is JourneyStatus.IN_PROGRESS for j in self.journeys.values())

    def complete_task(self, task_id: str, completed_at: datetime) -> None:
        for journey in self.journeys.values():
            if journey.task(task_id) is not None:
                tasks = tuple(
                    replace(t, status=TaskStatus.COMPLETED, completed_at=completed_at) if t.task_id == task_id else t
                    for t in journey.tasks
                )
                self.journeys[journey.journey_id] = replace(journey, tasks=tasks)
                return
        raise KeyError(task_id)

    def complete(self, journey_id: str, completed_at: datetime) -> None:
        self.journeys[journey_id] = replace(
            self.journeys[journey_id], status=JourneyStatus.COMPLETED, completed_at=completed_at
        )


class InMemoryTemplateCatalog:
    def __init__(self, *templates: ProtocolTemplate, journey_tasks: tuple[str, ...] = ("Tarefa A", "Tarefa B")) -> None:
        self._templates = {t.template_id: t for t in templates}
        self._journey_tasks = journey_tasks

    def get(self, template_id: str) -> ProtocolTemplate | None:
        return self._templates.get(template_id)

    @property
    def journey_tasks(self) -> tuple[str, ...]:
        return self._journey_tasks
