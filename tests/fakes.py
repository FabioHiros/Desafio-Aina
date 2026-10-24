"""Implementações de teste das interfaces da aplicação (Clock e repositories/interfaces.py)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Self

from app.core.errors import PatientAlreadyExistsError
from app.models.events import Event, EventName
from app.models.patient import Patient


class FakeClock:
    """Relógio controlado pelo teste: o tempo só anda quando o teste manda."""

    def __init__(self, start: datetime = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)


class InMemoryUnitOfWork:
    """Unidade de trabalho em memória com rollback de verdade: sem commit, o estado volta ao snapshot."""

    def __init__(self) -> None:
        self.patients = InMemoryPatientRepository()
        self.events = InMemoryEventRepository()
        self.commits = 0
        self.rollbacks = 0
        self._snapshot: tuple[dict[str, Patient], list[Event]] | None = None

    def __enter__(self) -> Self:
        self._snapshot = (dict(self.patients.patients), list(self.events.events))
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.rollback()
        self._snapshot = None

    def commit(self) -> None:
        self.commits += 1
        self._snapshot = (dict(self.patients.patients), list(self.events.events))

    def rollback(self) -> None:
        assert self._snapshot is not None, "UnitOfWork usado fora de um bloco `with`"
        if (self.patients.patients, self.events.events) != self._snapshot:
            self.rollbacks += 1
        self.patients.patients, self.events.events = dict(self._snapshot[0]), list(self._snapshot[1])


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
