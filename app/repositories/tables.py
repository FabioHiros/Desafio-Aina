from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Connection,
    Date,
    Engine,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, UTCDateTime, sql_in
from app.models.events import EventName
from app.models.journey import JourneyStatus, TaskStatus
from app.models.patient import Sex
from app.models.protocol import SessionStatus


def init_db(engine: Engine) -> None:
    """Cria tabelas, índices e triggers que ainda não existem. Seguro rodar a cada inicialização."""
    Base.metadata.create_all(engine)


class PatientRow(Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20))
    phone_hash: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    birth_date: Mapped[date] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(String(1))
    terms_accepted: Mapped[bool] = mapped_column(Boolean)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    __table_args__ = (
        CheckConstraint(sql_in("sex", Sex), name="sex"),
        CheckConstraint("(terms_accepted = 1) = (terms_accepted_at IS NOT NULL)", name="terms_date"),
    )


class ProtocolSessionRow(Base):
    __tablename__ = "protocol_sessions"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"))
    template_id: Mapped[str] = mapped_column(String(50))
    objetivo: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20))
    score: Mapped[int | None] = mapped_column(Integer)
    ended_by_skip: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    answers: Mapped[list["ProtocolAnswerRow"]] = relationship(order_by="ProtocolAnswerRow.position")

    __table_args__ = (
        CheckConstraint("length(objetivo) BETWEEN 1 AND 500", name="objetivo_length"),
        CheckConstraint(sql_in("status", SessionStatus), name="status"),
        CheckConstraint(
            "(status = 'concluido') = (completed_at IS NOT NULL AND score IS NOT NULL)", name="completed_state"
        ),
        Index(None, "patient_id", "status"),
        Index(
            "ux_protocol_sessions_one_active", "patient_id", unique=True, sqlite_where=text("status = 'em_andamento'")
        ),
    )


class ProtocolAnswerRow(Base):
    __tablename__ = "protocol_answers"

    session_id: Mapped[str] = mapped_column(ForeignKey("protocol_sessions.session_id"), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    value: Mapped[int] = mapped_column(Integer)
    answered_at: Mapped[datetime] = mapped_column(UTCDateTime)


class JourneyRow(Base):
    __tablename__ = "journeys"

    journey_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"))
    session_id: Mapped[str] = mapped_column(ForeignKey("protocol_sessions.session_id"), unique=True)
    objetivo: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    tasks: Mapped[list["JourneyTaskRow"]] = relationship(order_by="JourneyTaskRow.position")

    __table_args__ = (
        CheckConstraint("length(objetivo) BETWEEN 1 AND 500", name="objetivo_length"),
        CheckConstraint(sql_in("status", JourneyStatus), name="status"),
        CheckConstraint("(status = 'concluida') = (completed_at IS NOT NULL)", name="completed_state"),
        Index("ux_journeys_one_active", "patient_id", unique=True, sqlite_where=text("status = 'em_andamento'")),
    )


class JourneyTaskRow(Base):
    __tablename__ = "journey_tasks"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    journey_id: Mapped[str] = mapped_column(ForeignKey("journeys.journey_id"))
    position: Mapped[int] = mapped_column(Integer)
    titulo: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        UniqueConstraint("journey_id", "position"),
        CheckConstraint("length(titulo) BETWEEN 1 AND 200", name="titulo_length"),
        CheckConstraint(sql_in("status", TaskStatus), name="status"),
        CheckConstraint("(status = 'concluida') = (completed_at IS NOT NULL)", name="completed_state"),
    )


class EventRow(Base):
    __tablename__ = "events"

    position: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    event_name: Mapped[str] = mapped_column(String(50))
    patient_id_hash: Mapped[str] = mapped_column(String(64))
    properties: Mapped[dict[str, Any]] = mapped_column(JSON)

    __table_args__ = (
        CheckConstraint(sql_in("event_name", EventName), name="event_name"),
        CheckConstraint("json_valid(properties)", name="properties_json"),
        Index(None, "patient_id_hash", "event_name", "occurred_at"),
    )


EVENT_TRIGGERS = (
    "CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END",
    "CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END",
)


def _create_event_triggers(_table: Any, connection: Connection, **_: Any) -> None:
    for trigger in EVENT_TRIGGERS:
        connection.exec_driver_sql(trigger)


event.listen(EventRow.__table__, "after_create", _create_event_triggers)
