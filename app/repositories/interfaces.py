"""Interfaces de persistência. Os services dependem só delas; as implementações SQLAlchemy ficam ao lado
(patient.py, event.py, unit_of_work.py) e são escolhidas em api/dependencies.py.

Isso permite testar regras de negócio com implementações em memória (tests/fakes.py), sem banco.
"""

from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self

from app.models.events import Event, EventName
from app.models.patient import Patient


class PatientRepository(Protocol):
    """Persistência de pacientes. Recebe e devolve modelos de domínio, nunca linhas do ORM."""

    def add(self, patient: Patient) -> None:
        """Raises PatientAlreadyExistsError se o telefone (phone_hash) já estiver cadastrado."""
        ...

    def get(self, patient_id: str) -> Patient | None: ...

    def exists_by_phone_hash(self, phone_hash: str) -> bool: ...

    def mark_terms_accepted(self, patient_id: str, accepted_at: datetime) -> None: ...


class EventRepository(Protocol):
    """Trilha append-only: não existe operação de update nem de delete."""

    def append(
        self,
        event_id: str,
        occurred_at: datetime,
        event_name: EventName,
        patient_id_hash: str,
        properties: dict[str, Any],
    ) -> Event: ...

    def list_by_patient_hash(self, patient_id_hash: str) -> list[Event]:
        """Eventos do paciente em ordem de gravação."""
        ...

    def exists_since(self, patient_id_hash: str, event_name: EventName, since: datetime) -> bool:
        """Existe evento desse tipo para o paciente com occurred_at depois de `since`?"""
        ...


class UnitOfWork(Protocol):
    """Única porta de entrada da persistência: os repositórios só existem dentro de uma unidade de trabalho.

        with uow:
            uow.patients.add(patient)
            event_store.append(uow, patient_id, PatientCreated())
            uow.commit()

    Tudo dentro do bloco usa a mesma transação. Nada é gravado sem `commit()`: sair do bloco sem commit
    (por exceção ou esquecimento) desfaz tudo.
    """

    @property
    def patients(self) -> PatientRepository: ...

    @property
    def events(self) -> EventRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
