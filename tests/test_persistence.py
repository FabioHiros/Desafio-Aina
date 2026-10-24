"""Regras que o próprio banco garante, independentemente dos services."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import Engine, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session, sessionmaker

from app.repositories.tables import (
    EventRow,
    JourneyRow,
    PatientRow,
    ProtocolAnswerRow,
    ProtocolSessionRow,
    init_db,
)

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
NOW_DB = "2026-10-24 12:00:00.000000"  # formato em que o SQLAlchemy grava datas no SQLite, para INSERTs em SQL puro


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


def patient(patient_id: str = "p-1", phone_hash: str = "h-1", sex: str = "F") -> PatientRow:
    return PatientRow(
        patient_id=patient_id,
        phone="5500000000000",
        phone_hash=phone_hash,
        name="Fulano",
        birth_date=date(1990, 1, 1),
        sex=sex,
        terms_accepted=True,
        terms_accepted_at=NOW,
        created_at=NOW,
    )


def completed_session(session_id: str, patient_id: str = "p-1") -> ProtocolSessionRow:
    return ProtocolSessionRow(
        session_id=session_id,
        patient_id=patient_id,
        template_id="phq9",
        objetivo="Perder 5kg",
        status="concluido",
        score=1,
        ended_by_skip=True,
        started_at=NOW,
        completed_at=NOW,
    )


def journey(journey_id: str, session_id: str, patient_id: str = "p-1") -> JourneyRow:
    return JourneyRow(
        journey_id=journey_id,
        patient_id=patient_id,
        session_id=session_id,
        objetivo="Perder 5kg",
        status="em_andamento",
        created_at=NOW,
    )


def event(event_id: str = "e-1", event_name: str = "patient_created", occurred_at: datetime = NOW) -> EventRow:
    return EventRow(
        event_id=event_id, occurred_at=occurred_at, event_name=event_name, patient_id_hash="hash", properties={}
    )


# ─────────────── Schema ───────────────


def test_init_db_is_idempotent(engine: Engine) -> None:
    init_db(engine)


# ─────────────── Event store ───────────────


def test_events_cannot_be_updated(session: Session) -> None:
    session.add(event())
    session.commit()
    with pytest.raises(IntegrityError, match="append-only"):
        session.execute(update(EventRow).values(event_name="terms_accepted"))


def test_events_cannot_be_deleted(session: Session) -> None:
    session.add(event())
    session.commit()
    with pytest.raises(IntegrityError, match="append-only"):
        session.execute(delete(EventRow))


def test_unknown_event_name_is_rejected(session: Session) -> None:
    session.add(event(event_name="made_up_event"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_event_properties_must_be_json(session: Session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO events (event_id, occurred_at, event_name, patient_id_hash, properties) "
                "VALUES ('e-1', :now, 'patient_created', 'hash', 'not json')"
            ),
            {"now": NOW_DB},
        )


# ─────────────── Datas ───────────────


def test_datetimes_round_trip_as_utc(session: Session) -> None:
    sao_paulo = timezone(timedelta(hours=-3))
    session.add(event(occurred_at=datetime(2026, 10, 24, 9, 0, tzinfo=sao_paulo)))
    session.commit()
    session.expunge_all()

    stored = session.scalars(select(EventRow)).one()
    assert stored.occurred_at == NOW
    assert stored.occurred_at.tzinfo == UTC


def test_naive_datetime_is_rejected(session: Session) -> None:
    session.add(event(occurred_at=datetime(2026, 10, 24, 12, 0)))
    with pytest.raises(StatementError, match="timezone"):
        session.commit()


# ─────────────── Pacientes, protocolo e jornada ───────────────


def test_duplicate_phone_hash_is_rejected(session: Session) -> None:
    session.add_all([patient("p-1", phone_hash="same"), patient("p-2", phone_hash="same")])
    with pytest.raises(IntegrityError):
        session.commit()


def test_invalid_sex_is_rejected(session: Session) -> None:
    session.add(patient(sex="X"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_question_cannot_be_answered_twice(session: Session) -> None:
    session.add_all([patient(), completed_session("s-1")])
    session.commit()
    session.add(ProtocolAnswerRow(session_id="s-1", question_id="q1", position=1, value=0, answered_at=NOW))
    session.commit()

    with pytest.raises(IntegrityError):
        session.execute(
            text("INSERT INTO protocol_answers VALUES ('s-1', 'q1', 1, 2, :now)"),
            {"now": NOW_DB},
        )


def test_journey_requires_existing_session(session: Session) -> None:
    session.add(patient())
    session.commit()
    session.add(journey("j-1", session_id="does-not-exist"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_only_one_active_journey_per_patient(session: Session) -> None:
    session.add_all([patient(), completed_session("s-1"), completed_session("s-2")])
    session.commit()
    session.add(journey("j-1", "s-1"))
    session.commit()

    session.add(journey("j-2", "s-2"))
    with pytest.raises(IntegrityError):
        session.commit()


def in_progress_session(session_id: str, patient_id: str = "p-1") -> ProtocolSessionRow:
    return ProtocolSessionRow(
        session_id=session_id,
        patient_id=patient_id,
        template_id="phq9",
        objetivo="Perder 5kg",
        status="em_andamento",
        started_at=NOW,
    )


def test_only_one_protocol_session_in_progress_per_patient(session: Session) -> None:
    session.add_all([patient(), in_progress_session("s-1")])
    session.commit()

    session.add(in_progress_session("s-2"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_completed_sessions_do_not_block_a_new_one(session: Session) -> None:
    session.add_all([patient(), completed_session("s-1"), completed_session("s-2"), in_progress_session("s-3")])
    session.commit()


# ─────────────── Conexão SQLite ───────────────


def test_sqlite_connection_is_configured(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


# ─────────────── Transações ───────────────


def test_transaction_rolls_back_everything_on_error(session_factory: sessionmaker[Session]) -> None:
    def failing_operation() -> None:
        with session_factory.begin() as session:
            session.add_all([patient(), event()])
            session.flush()
            raise RuntimeError("falha no meio da operação")

    with pytest.raises(RuntimeError):
        failing_operation()

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PatientRow)) == 0
        assert session.scalar(select(func.count()).select_from(EventRow)) == 0


def test_transaction_commits_on_success(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        session.add_all([patient(), event()])

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PatientRow)) == 1
        assert session.scalar(select(func.count()).select_from(EventRow)) == 1
