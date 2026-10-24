"""Eventos: a taxonomia, o contrato das properties de cada evento e o evento persistido.

Allow-list: cada evento declara exatamente os campos que pode carregar (extra="forbid"), então incluir
um campo novo, e com ele um possível vazamento de PII, é sempre uma decisão explícita e visível.
O nome do evento vem do tipo, então não há como gravar `protocol_completed` com o payload errado.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from app.models.followup import SkipReason


class EventName(StrEnum):
    PATIENT_CREATED = "patient_created"
    TERMS_ACCEPTED = "terms_accepted"
    PROTOCOL_STARTED = "protocol_started"
    PROTOCOL_COMPLETED = "protocol_completed"
    JOURNEY_CREATED = "journey_created"
    TASK_COMPLETED = "task_completed"
    JOURNEY_COMPLETED = "journey_completed"
    FOLLOWUP_ELIGIBLE = "followup_eligible"
    FOLLOWUP_SKIPPED = "followup_skipped"


@dataclass(frozen=True, slots=True)
class Event:
    """Evento persistido na trilha (envelope + properties). Imutável."""

    event_id: str
    position: int  # ordem global de gravação: desempata eventos com o mesmo occurred_at
    occurred_at: datetime
    event_name: EventName
    patient_id_hash: str
    properties: dict[str, Any]


class DomainEvent(BaseModel):
    """Base das properties de cada evento."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_name: ClassVar[EventName]


# ─────────────── Paciente ───────────────


class PatientCreated(DomainEvent):
    event_name = EventName.PATIENT_CREATED


class TermsAccepted(DomainEvent):
    event_name = EventName.TERMS_ACCEPTED


# ─────────────── Protocolo ───────────────


class ProtocolStarted(DomainEvent):
    event_name = EventName.PROTOCOL_STARTED

    session_id: str
    template_id: str


class ProtocolCompleted(DomainEvent):
    event_name = EventName.PROTOCOL_COMPLETED

    session_id: str
    template_id: str
    score: int
    ended_by_skip: bool


# ─────────────── Jornada ───────────────


class JourneyCreated(DomainEvent):
    event_name = EventName.JOURNEY_CREATED

    journey_id: str
    session_id: str
    task_count: int


class TaskCompleted(DomainEvent):
    event_name = EventName.TASK_COMPLETED

    journey_id: str
    task_id: str


class JourneyCompleted(DomainEvent):
    event_name = EventName.JOURNEY_COMPLETED

    journey_id: str


# ─────────────── Follow-up ───────────────


class FollowupEligible(DomainEvent):
    event_name = EventName.FOLLOWUP_ELIGIBLE

    template_key: str


class FollowupSkipped(DomainEvent):
    event_name = EventName.FOLLOWUP_SKIPPED

    reason: SkipReason
