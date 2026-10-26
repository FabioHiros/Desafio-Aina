from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AnswerAlreadyRecordedError, JourneyAlreadyActiveError, ProtocolInProgressError
from app.models.journey import Journey, JourneyStatus, Task, TaskStatus
from app.models.patient import Patient, Sex
from app.models.protocol import Answer, ProtocolSession, SessionStatus
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def uow(session_factory: sessionmaker[Session]) -> SqlAlchemyUnitOfWork:
    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        uow.patients.add(
            Patient(
                patient_id="p-1",
                phone="5511987654321",
                phone_hash="hash",
                name="Maria Teste",
                birth_date=date(1990, 5, 10),
                sex=Sex.F,
                terms_accepted=True,
                terms_accepted_at=NOW,
                created_at=NOW,
            )
        )
        uow.commit()
    return uow


def new_session(session_id: str = "s-1", status: SessionStatus = SessionStatus.IN_PROGRESS) -> ProtocolSession:
    completed = status is SessionStatus.COMPLETED
    return ProtocolSession(
        session_id=session_id,
        patient_id="p-1",
        template_id="phq9",
        objetivo="Perder 5kg",
        status=status,
        score=1 if completed else None,
        ended_by_skip=False,
        started_at=NOW,
        completed_at=NOW if completed else None,
    )


def new_journey(journey_id: str = "j-1", session_id: str = "s-1", created_at: datetime = NOW) -> Journey:
    return Journey(
        journey_id=journey_id,
        patient_id="p-1",
        session_id=session_id,
        objetivo="Perder 5kg",
        status=JourneyStatus.IN_PROGRESS,
        created_at=created_at,
        completed_at=None,
        tasks=tuple(
            Task(
                task_id=f"{journey_id}-t{i}",
                position=i,
                titulo=f"Tarefa {i}",
                status=TaskStatus.IN_PROGRESS,
                completed_at=None,
            )
            for i in (1, 2)
        ),
    )


def test_session_round_trip_with_answers_in_order(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        uow.sessions.add(new_session())
        uow.sessions.add_answer("s-1", Answer("q1", 1, 2, NOW))
        uow.sessions.add_answer("s-1", Answer("q2", 2, 0, NOW + timedelta(seconds=5)))
        uow.commit()

    with uow:
        stored = uow.sessions.get("s-1")
    assert stored is not None
    assert stored.objetivo == "Perder 5kg"
    assert stored.answer_values == {"q1": 2, "q2": 0}
    assert [a.position for a in stored.answers] == [1, 2]
    assert stored.answers[1].answered_at == NOW + timedelta(seconds=5)


def test_answer_is_visible_in_the_same_transaction(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        uow.sessions.add(new_session())
        assert uow.sessions.get("s-1") is not None
        uow.sessions.add_answer("s-1", Answer("q1", 1, 2, NOW))
        stored = uow.sessions.get("s-1")
        assert stored is not None
        assert stored.answer_values == {"q1": 2}


def test_same_question_cannot_be_recorded_twice(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        uow.sessions.add(new_session())
        uow.sessions.add_answer("s-1", Answer("q1", 1, 2, NOW))
        with pytest.raises(AnswerAlreadyRecordedError):
            uow.sessions.add_answer("s-1", Answer("q1", 1, 3, NOW))


def test_complete_session(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        uow.sessions.add(new_session())
        uow.sessions.complete("s-1", score=2, ended_by_skip=True, completed_at=NOW)
        uow.commit()

    with uow:
        stored = uow.sessions.get("s-1")
        assert not uow.sessions.has_in_progress("p-1")
    assert stored is not None
    assert (stored.status, stored.score, stored.ended_by_skip, stored.completed_at) == (
        SessionStatus.COMPLETED,
        2,
        True,
        NOW,
    )


def test_second_session_in_progress_is_rejected(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        uow.sessions.add(new_session("s-1"))
        assert uow.sessions.has_in_progress("p-1")
        with pytest.raises(ProtocolInProgressError):
            uow.sessions.add(new_session("s-2"))


def test_unknown_session_is_none(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        assert uow.sessions.get("nope") is None


def test_journey_round_trip_with_tasks_in_order(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        uow.sessions.add(new_session(status=SessionStatus.COMPLETED))
        uow.journeys.add(new_journey())
        uow.commit()

    with uow:
        stored = uow.journeys.get("j-1")
        assert uow.journeys.get_by_session("s-1") == stored
        assert uow.journeys.has_active("p-1")
    assert stored == new_journey()


def test_second_active_journey_is_rejected(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        uow.sessions.add(new_session("s-1", SessionStatus.COMPLETED))
        uow.sessions.add(new_session("s-2", SessionStatus.COMPLETED))
        uow.journeys.add(new_journey("j-1", "s-1"))
        with pytest.raises(JourneyAlreadyActiveError):
            uow.journeys.add(new_journey("j-2", "s-2"))


def test_complete_task_and_journey(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        uow.sessions.add(new_session(status=SessionStatus.COMPLETED))
        uow.journeys.add(new_journey())
        uow.journeys.complete_task("j-1-t1", NOW)
        partially = uow.journeys.get("j-1")
        uow.journeys.complete_task("j-1-t2", NOW)
        uow.journeys.complete("j-1", NOW)
        uow.commit()

    assert partially is not None
    assert partially.has_active_task
    with uow:
        done = uow.journeys.get("j-1")
        assert not uow.journeys.has_active("p-1")
    assert done is not None
    assert done.status is JourneyStatus.COMPLETED
    assert not done.has_active_task


def test_current_journey_prefers_active_then_latest(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        assert uow.journeys.get_current_for_patient("p-1") is None
        for i in (1, 2, 3):
            uow.sessions.add(new_session(f"s-{i}", SessionStatus.COMPLETED))
        uow.journeys.add(new_journey("j-1", "s-1", NOW))
        uow.journeys.complete("j-1", NOW)
        uow.journeys.add(new_journey("j-2", "s-2", NOW + timedelta(days=1)))
        uow.journeys.complete("j-2", NOW + timedelta(days=1))
        latest = uow.journeys.get_current_for_patient("p-1")
        uow.journeys.add(new_journey("j-3", "s-3", NOW - timedelta(days=1)))
        active = uow.journeys.get_current_for_patient("p-1")

    assert latest is not None
    assert latest.journey_id == "j-2"
    assert active is not None
    assert active.journey_id == "j-3"


def test_has_completed_only_counts_completed_sessions(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        uow.sessions.add(new_session("s-1"))
        assert not uow.sessions.has_completed("p-1")
        uow.sessions.complete("s-1", score=2, ended_by_skip=True, completed_at=NOW)
        assert uow.sessions.has_completed("p-1")
        assert not uow.sessions.has_completed("other")
