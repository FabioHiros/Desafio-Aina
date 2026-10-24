"""Modelos de persistência (SQLAlchemy). Fonte única do schema, criado por `init_db()`.

O que o ORM não expressa (triggers append-only de `events`) é anexado como DDL ao criar a tabela.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DDL,
    CheckConstraint,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EVENT_NAMES = (
    "patient_created",
    "terms_accepted",
    "protocol_started",
    "protocol_completed",
    "journey_created",
    "task_completed",
    "followup_eligible",
    "followup_skipped",
)


class UTCDateTime(TypeDecorator[datetime]):
    """Grava sempre em UTC e devolve datetime com timezone.

    O SQLite não guarda fuso; sem isso, datas voltariam "naive" e a comparação do cooldown ficaria ambígua.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime sem timezone; use o relógio da aplicação (UTC)")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    # Nomes de constraints determinísticos: aparecem nas mensagens de erro e facilitam migrations futuras.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


# ─────────────── Pacientes ───────────────
# Cadastro operacional: único lugar onde telefone, nome e data de nascimento existem.
class PatientRow(Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20))
    phone_hash: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    birth_date: Mapped[str] = mapped_column(String(10))  # ISO date
    sex: Mapped[str] = mapped_column(String(1))
    terms_accepted: Mapped[bool] = mapped_column(Boolean)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    __table_args__ = (
        CheckConstraint(_in("sex", ("F", "M", "O")), name="sex"),
        CheckConstraint("(terms_accepted = 1) = (terms_accepted_at IS NOT NULL)", name="terms_date"),
    )


# ─────────────── Protocolo ───────────────
# As perguntas vivem em templates/*.json; aqui só o estado da sessão e as respostas.
# objetivo é anotado ao iniciar a sessão e copiado para a jornada quando o protocolo conclui.
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
        CheckConstraint(_in("status", ("em_andamento", "concluido")), name="status"),
        CheckConstraint(
            "(status = 'concluido') = (completed_at IS NOT NULL AND score IS NOT NULL)", name="completed_state"
        ),
        Index(None, "patient_id", "status"),
    )


class ProtocolAnswerRow(Base):
    __tablename__ = "protocol_answers"

    # PK composta: a mesma pergunta não pode ser respondida duas vezes na sessão.
    session_id: Mapped[str] = mapped_column(ForeignKey("protocol_sessions.session_id"), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    value: Mapped[int] = mapped_column(Integer)  # escala validada pelo service a partir do template
    answered_at: Mapped[datetime] = mapped_column(UTCDateTime)


# ─────────────── Jornada ───────────────
# Criada automaticamente quando o protocolo conclui: objetivo vem da sessão, tarefas de templates/journey_tasks.json.
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
        CheckConstraint(_in("status", ("em_andamento", "concluida")), name="status"),
        CheckConstraint("(status = 'concluida') = (completed_at IS NOT NULL)", name="completed_state"),
        # No máximo uma jornada em andamento por paciente.
        Index(
            "ux_journeys_one_active",
            "patient_id",
            unique=True,
            sqlite_where=text("status = 'em_andamento'"),
        ),
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
        CheckConstraint(_in("status", ("em_andamento", "concluida")), name="status"),
        CheckConstraint("(status = 'concluida') = (completed_at IS NOT NULL)", name="completed_state"),
    )


# ─────────────── Event store (append-only) ───────────────
# Sem FK para patients: a trilha é exportável e só se liga ao paciente pelo hash.
# UPDATE/DELETE são bloqueados pelos triggers definidos logo abaixo da classe.
class EventRow(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    event_name: Mapped[str] = mapped_column(String(50))
    patient_id_hash: Mapped[str] = mapped_column(String(64))
    properties: Mapped[dict[str, Any]] = mapped_column(JSON)

    __table_args__ = (
        CheckConstraint(_in("event_name", EVENT_NAMES), name="event_name"),
        CheckConstraint("json_valid(properties)", name="properties_json"),
        Index(None, "patient_id_hash", "event_name", "occurred_at"),
    )


for _trigger in (
    "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
    "BEGIN SELECT RAISE(ABORT, 'events are append-only'); END",
    "CREATE TRIGGER events_no_delete BEFORE DELETE ON events "
    "BEGIN SELECT RAISE(ABORT, 'events are append-only'); END",
):
    event.listen(EventRow.__table__, "after_create", DDL(_trigger))
