from dataclasses import dataclass
from datetime import datetime

from app.core.clock import Clock
from app.core.errors import (
    AnswerAlreadyRecordedError,
    ConsentRequiredError,
    InvalidAnswerError,
    JourneyAlreadyActiveError,
    PatientNotFoundError,
    ProtocolInProgressError,
    ProtocolSessionNotFoundError,
    SessionClosedError,
    TemplateNotFoundError,
    UnexpectedQuestionError,
)
from app.core.ids import new_id
from app.models.events import JourneyCreated, ProtocolCompleted, ProtocolStarted
from app.models.journey import Journey, JourneyStatus, Task, TaskStatus
from app.models.protocol import (
    Answer,
    Completed,
    NextQuestion,
    ProtocolSession,
    ProtocolTemplate,
    SessionStatus,
)
from app.repositories.interfaces import TemplateCatalog, UnitOfWork
from app.services.event_store import EventStore


@dataclass(frozen=True, slots=True)
class SessionState:
    session: ProtocolSession
    template: ProtocolTemplate
    next_question: NextQuestion | None
    journey: Journey | None = None


class ProtocolService:
    def __init__(self, uow: UnitOfWork, event_store: EventStore, catalog: TemplateCatalog, clock: Clock) -> None:
        self._uow = uow
        self._event_store = event_store
        self._catalog = catalog
        self._clock = clock

    def start(self, patient_id: str, template_id: str, objetivo: str) -> SessionState:
        template = self._template(template_id)
        with self._uow as uow:
            patient = uow.patients.get(patient_id)
            if patient is None:
                raise PatientNotFoundError
            if not patient.terms_accepted:
                raise ConsentRequiredError
            if uow.sessions.has_in_progress(patient_id):
                raise ProtocolInProgressError
            if uow.journeys.has_active(patient_id):
                raise JourneyAlreadyActiveError

            session = ProtocolSession(
                session_id=new_id(),
                patient_id=patient_id,
                template_id=template_id,
                objetivo=objetivo,
                status=SessionStatus.IN_PROGRESS,
                score=None,
                ended_by_skip=False,
                started_at=self._clock.now(),
                completed_at=None,
            )
            uow.sessions.add(session)
            self._event_store.append(
                uow, patient_id, ProtocolStarted(session_id=session.session_id, template_id=template_id)
            )
            uow.commit()
            return self._state(uow, session, template)

    def get(self, session_id: str) -> SessionState:
        with self._uow as uow:
            session = self._session(uow, session_id)
            return self._state(uow, session, self._template(session.template_id))

    def answer(self, session_id: str, question_id: str, value: int) -> SessionState:
        with self._uow as uow:
            session = self._session(uow, session_id)
            template = self._template(session.template_id)

            recorded = session.answer_for(question_id)
            if recorded is not None:
                if recorded.value != value:
                    raise AnswerAlreadyRecordedError
                return self._state(uow, session, template)

            progress = template.evaluate(session.answer_values)
            if session.status is SessionStatus.COMPLETED or isinstance(progress, Completed):
                raise SessionClosedError
            if progress.question.id != question_id:
                raise UnexpectedQuestionError(progress.question.id)
            if value not in template.scale_values:
                raise InvalidAnswerError

            now = self._clock.now()
            uow.sessions.add_answer(session_id, Answer(question_id, progress.position, value, now))
            result = template.evaluate({**session.answer_values, question_id: value})
            if isinstance(result, Completed):
                self._complete(uow, session, result, now)
            uow.commit()
            return self._state(uow, self._session(uow, session_id), template)

    def _complete(self, uow: UnitOfWork, session: ProtocolSession, result: Completed, now: datetime) -> None:
        uow.sessions.complete(session.session_id, result.score, result.ended_by_skip, now)
        self._event_store.append(
            uow,
            session.patient_id,
            ProtocolCompleted(
                session_id=session.session_id,
                template_id=session.template_id,
                score=result.score,
                ended_by_skip=result.ended_by_skip,
            ),
        )
        self._create_journey(uow, session, now)

    def _create_journey(self, uow: UnitOfWork, session: ProtocolSession, now: datetime) -> None:
        journey = Journey(
            journey_id=new_id(),
            patient_id=session.patient_id,
            session_id=session.session_id,
            objetivo=session.objetivo,
            status=JourneyStatus.IN_PROGRESS,
            created_at=now,
            completed_at=None,
            tasks=tuple(
                Task(
                    task_id=new_id(), position=position, titulo=titulo, status=TaskStatus.IN_PROGRESS, completed_at=None
                )
                for position, titulo in enumerate(self._catalog.journey_tasks, start=1)
            ),
        )
        uow.journeys.add(journey)
        self._event_store.append(
            uow,
            session.patient_id,
            JourneyCreated(journey_id=journey.journey_id, session_id=session.session_id, task_count=len(journey.tasks)),
        )

    def _state(self, uow: UnitOfWork, session: ProtocolSession, template: ProtocolTemplate) -> SessionState:
        progress = template.evaluate(session.answer_values)
        in_progress = session.status is SessionStatus.IN_PROGRESS
        next_question = progress if in_progress and isinstance(progress, NextQuestion) else None
        journey = None if in_progress else uow.journeys.get_by_session(session.session_id)
        return SessionState(session=session, template=template, next_question=next_question, journey=journey)

    def _template(self, template_id: str) -> ProtocolTemplate:
        template = self._catalog.get(template_id)
        if template is None:
            raise TemplateNotFoundError
        return template

    @staticmethod
    def _session(uow: UnitOfWork, session_id: str) -> ProtocolSession:
        session = uow.sessions.get(session_id)
        if session is None:
            raise ProtocolSessionNotFoundError
        return session
