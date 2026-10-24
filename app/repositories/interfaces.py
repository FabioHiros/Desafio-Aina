"""Interfaces de persistência. Os services dependem só delas; as implementações SQLAlchemy ficam ao lado
(patient.py, event.py, unit_of_work.py) e são escolhidas em api/dependencies.py.

Isso permite testar regras de negócio com implementações em memória (tests/fakes.py), sem banco.
"""

from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self

from app.models.events import Event, EventName
from app.models.journey import Journey
from app.models.patient import Patient
from app.models.protocol import Answer, ProtocolSession, ProtocolTemplate


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

    def latest_occurred_at(self, patient_id_hash: str, event_name: EventName) -> datetime | None:
        """Quando ocorreu o evento mais recente desse tipo para o paciente (None se nunca ocorreu)."""
        ...


class ProtocolSessionRepository(Protocol):
    def add(self, protocol_session: ProtocolSession) -> None:
        """Raises ProtocolInProgressError se o paciente já tiver uma sessão em andamento."""
        ...

    def get(self, session_id: str) -> ProtocolSession | None:
        """Sessão com as respostas, em ordem."""
        ...

    def has_in_progress(self, patient_id: str) -> bool: ...

    def has_completed(self, patient_id: str) -> bool: ...

    def add_answer(self, session_id: str, answer: Answer) -> None:
        """Raises AnswerAlreadyRecordedError se a pergunta já tiver resposta (respostas não mudam)."""
        ...

    def complete(self, session_id: str, score: int, ended_by_skip: bool, completed_at: datetime) -> None: ...


class JourneyRepository(Protocol):
    def add(self, journey: Journey) -> None:
        """Grava a jornada e as tarefas. Raises JourneyAlreadyActiveError se já houver uma em andamento."""
        ...

    def get(self, journey_id: str) -> Journey | None: ...

    def get_by_session(self, session_id: str) -> Journey | None: ...

    def get_current_for_patient(self, patient_id: str) -> Journey | None:
        """A jornada em andamento, ou a mais recente se nenhuma estiver em andamento."""
        ...

    def has_active(self, patient_id: str) -> bool: ...

    def complete_task(self, task_id: str, completed_at: datetime) -> None: ...

    def complete(self, journey_id: str, completed_at: datetime) -> None: ...


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

    @property
    def sessions(self) -> ProtocolSessionRepository: ...

    @property
    def journeys(self) -> JourneyRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class TemplateCatalog(Protocol):
    """Templates de protocolo e tarefas placeholder da jornada, carregados e validados na inicialização."""

    def get(self, template_id: str) -> ProtocolTemplate | None: ...

    @property
    def journey_tasks(self) -> tuple[str, ...]: ...
