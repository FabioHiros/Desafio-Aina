from datetime import datetime

from app.core.clock import Clock
from app.core.ids import new_id
from app.core.security import Hasher
from app.models.events import DomainEvent, Event, EventName
from app.repositories.interfaces import UnitOfWork

# Segunda barreira, além da allow-list de cada evento: chaves que nunca podem existir em properties.
FORBIDDEN_PROPERTY_KEYS = frozenset({"phone", "telefone", "name", "nome", "birth_date", "data_nascimento", "objetivo"})


class EventStore:
    """Única porta de entrada da trilha de eventos.

    Recebe o patient_id em claro e é o único lugar que o converte em patient_id_hash.
    Não tem transação própria: todo método recebe a unidade de trabalho aberta de quem chamou, então um
    evento só pode ser gravado junto com a mudança de estado que ele descreve.
    """

    def __init__(self, hasher: Hasher, clock: Clock) -> None:
        self._hasher = hasher
        self._clock = clock

    def append(self, uow: UnitOfWork, patient_id: str, event: DomainEvent) -> Event:
        properties = event.model_dump(mode="json")
        leaked = FORBIDDEN_PROPERTY_KEYS & properties.keys()
        if leaked:
            raise ValueError(f"properties de evento não podem conter PII: {sorted(leaked)}")
        return uow.events.append(
            event_id=new_id(),
            occurred_at=self._clock.now(),
            event_name=event.event_name,
            patient_id_hash=self._hasher.hash_patient_id(patient_id),
            properties=properties,
        )

    def list_by_patient(self, uow: UnitOfWork, patient_id: str) -> list[Event]:
        return uow.events.list_by_patient_hash(self._hasher.hash_patient_id(patient_id))

    def exists_since(self, uow: UnitOfWork, patient_id: str, event_name: EventName, since: datetime) -> bool:
        return uow.events.exists_since(self._hasher.hash_patient_id(patient_id), event_name, since)

    def last_occurrence(self, uow: UnitOfWork, patient_id: str, event_name: EventName) -> datetime | None:
        return uow.events.latest_occurred_at(self._hasher.hash_patient_id(patient_id), event_name)


class EventService:
    """Consulta da trilha (GET /events): abre a própria unidade de trabalho, só leitura."""

    def __init__(self, uow: UnitOfWork, event_store: EventStore) -> None:
        self._uow = uow
        self._event_store = event_store

    def trail(self, patient_id: str) -> list[Event]:
        with self._uow as uow:
            return self._event_store.list_by_patient(uow, patient_id)
