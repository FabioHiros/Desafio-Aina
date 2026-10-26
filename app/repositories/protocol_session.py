from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AnswerAlreadyRecordedError, ProtocolInProgressError
from app.models.protocol import Answer, ProtocolSession, SessionStatus
from app.repositories.tables import ProtocolAnswerRow, ProtocolSessionRow


class SqlAlchemyProtocolSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, protocol_session: ProtocolSession) -> None:
        self._session.add(
            ProtocolSessionRow(
                session_id=protocol_session.session_id,
                patient_id=protocol_session.patient_id,
                template_id=protocol_session.template_id,
                objetivo=protocol_session.objetivo,
                status=protocol_session.status.value,
                score=protocol_session.score,
                ended_by_skip=protocol_session.ended_by_skip,
                started_at=protocol_session.started_at,
                completed_at=protocol_session.completed_at,
            )
        )
        try:
            self._session.flush()
        except IntegrityError as exc:
            if "protocol_sessions.patient_id" in str(exc.orig):
                raise ProtocolInProgressError from None
            raise

    def get(self, session_id: str) -> ProtocolSession | None:
        row = self._session.get(ProtocolSessionRow, session_id)
        return _to_domain(row) if row is not None else None

    def has_in_progress(self, patient_id: str) -> bool:
        query = select(
            exists().where(
                ProtocolSessionRow.patient_id == patient_id,
                ProtocolSessionRow.status == SessionStatus.IN_PROGRESS.value,
            )
        )
        return bool(self._session.scalar(query))

    def has_completed(self, patient_id: str) -> bool:
        query = select(
            exists().where(
                ProtocolSessionRow.patient_id == patient_id,
                ProtocolSessionRow.status == SessionStatus.COMPLETED.value,
            )
        )
        return bool(self._session.scalar(query))

    def add_answer(self, session_id: str, answer: Answer) -> None:
        self._session.add(
            ProtocolAnswerRow(
                session_id=session_id,
                question_id=answer.question_id,
                position=answer.position,
                value=answer.value,
                answered_at=answer.answered_at,
            )
        )
        try:
            self._session.flush()
        except IntegrityError as exc:
            if "protocol_answers" in str(exc.orig):
                raise AnswerAlreadyRecordedError from None
            raise
        self._session.expire(self._session.get_one(ProtocolSessionRow, session_id), ["answers"])

    def complete(self, session_id: str, score: int, ended_by_skip: bool, completed_at: datetime) -> None:
        row = self._session.get_one(ProtocolSessionRow, session_id)
        row.status = SessionStatus.COMPLETED.value
        row.score = score
        row.ended_by_skip = ended_by_skip
        row.completed_at = completed_at
        self._session.flush()


def _to_domain(row: ProtocolSessionRow) -> ProtocolSession:
    return ProtocolSession(
        session_id=row.session_id,
        patient_id=row.patient_id,
        template_id=row.template_id,
        objetivo=row.objetivo,
        status=SessionStatus(row.status),
        score=row.score,
        ended_by_skip=row.ended_by_skip,
        started_at=row.started_at,
        completed_at=row.completed_at,
        answers=tuple(
            Answer(question_id=a.question_id, position=a.position, value=a.value, answered_at=a.answered_at)
            for a in row.answers
        ),
    )
