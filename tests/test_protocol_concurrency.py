"""Requisições simultâneas na sessão de protocolo, com banco real e threads.

Cenário real: o agente reenvia a mesma resposta (retry, webhook duplicado) enquanto a primeira ainda está
sendo processada.
"""

import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.core.security import Hasher
from app.models.patient import NewPatient, Sex
from app.repositories.tables import EventRow, JourneyRow, ProtocolAnswerRow, ProtocolSessionRow
from app.repositories.templates import FileTemplateCatalog
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.services.event_store import EventStore
from app.services.patient import PatientService
from app.services.protocol import ProtocolService
from tests.fakes import FakeClock

HASHER = Hasher(phone_salt=SecretStr("phone-salt-0000000"), patient_id_salt=SecretStr("event-salt-0000000"))
CATALOG = FileTemplateCatalog.load(Path(__file__).resolve().parent.parent / "templates")
ATTEMPTS = 10


@pytest.fixture
def make_service(session_factory: sessionmaker[Session], clock: FakeClock) -> Callable[[], ProtocolService]:
    def make() -> ProtocolService:
        return ProtocolService(SqlAlchemyUnitOfWork(session_factory), EventStore(HASHER, clock), CATALOG, clock)

    return make


@pytest.fixture
def patient_id(session_factory: sessionmaker[Session], clock: FakeClock) -> str:
    service = PatientService(SqlAlchemyUnitOfWork(session_factory), EventStore(HASHER, clock), HASHER, clock)
    patient = service.register(
        NewPatient(phone="5511987654321", name="Maria", birth_date=date(1990, 5, 10), sex=Sex.F, terms_accepted=True)
    )
    return patient.patient_id


def run_concurrently[T](action: Callable[[ProtocolService], T], make: Callable[[], ProtocolService]) -> list[T | str]:
    """Roda `action` em ATTEMPTS threads liberadas ao mesmo tempo; erros viram o código do erro."""
    barrier = threading.Barrier(ATTEMPTS)
    results: list[T | str] = []
    lock = threading.Lock()

    def worker() -> None:
        service = make()
        barrier.wait()
        try:
            outcome: T | str = action(service)
        except AppError as exc:
            outcome = exc.code
        except Exception as exc:  # erro inesperado: registrado para a mensagem de falha
            outcome = f"unexpected {type(exc).__name__}: {exc}"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(ATTEMPTS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def count(session_factory: sessionmaker[Session], table: type) -> int:
    with session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(table)) or 0)


def test_simultaneous_identical_answers_are_recorded_once(
    make_service: Callable[[], ProtocolService], patient_id: str, session_factory: sessionmaker[Session]
) -> None:
    session_id = make_service().start(patient_id, "phq9", "Perder 5kg").session.session_id

    def answer_q1(service: ProtocolService) -> str | None:
        pending = service.answer(session_id, "q1", 2).next_question
        return pending.question.id if pending is not None else None

    results = run_concurrently(answer_q1, make_service)

    # Nenhum erro (todos recebem 200) e todos veem a mesma próxima pergunta.
    assert results == ["q2"] * ATTEMPTS
    assert count(session_factory, ProtocolAnswerRow) == 1


def test_simultaneous_final_answers_create_one_journey(
    make_service: Callable[[], ProtocolService], patient_id: str, session_factory: sessionmaker[Session]
) -> None:
    service = make_service()
    session_id = service.start(patient_id, "phq9", "Perder 5kg").session.session_id
    service.answer(session_id, "q1", 1)

    results = run_concurrently(lambda s: s.answer(session_id, "q2", 1).journey, make_service)

    journeys = {r.journey_id for r in results if not isinstance(r, str) and r is not None}
    assert len(journeys) == 1, results
    assert count(session_factory, JourneyRow) == 1
    with session_factory() as session:
        completed = select(func.count()).where(EventRow.event_name == "protocol_completed")
        assert session.scalar(completed) == 1


def test_simultaneous_starts_create_one_session(
    make_service: Callable[[], ProtocolService], patient_id: str, session_factory: sessionmaker[Session]
) -> None:
    results = run_concurrently(lambda s: s.start(patient_id, "phq9", "Perder 5kg").session.session_id, make_service)

    errors = sorted(r for r in results if r == "protocol_in_progress")
    assert len(errors) == ATTEMPTS - 1, results
    assert count(session_factory, ProtocolSessionRow) == 1
