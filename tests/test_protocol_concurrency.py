"""Requisições simultâneas (protocolo e follow-up), com banco real e threads.

Cenário real: o agente reenvia a mesma resposta (retry, webhook duplicado) enquanto a primeira ainda está
sendo processada.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import Hasher
from app.models.patient import NewPatient, Sex
from app.repositories.rules import load_followup_rules
from app.repositories.tables import EventRow, JourneyRow, ProtocolAnswerRow, ProtocolSessionRow
from app.repositories.templates import FileTemplateCatalog
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.services.event_store import EventStore
from app.services.followup import FollowupService
from app.services.patient import PatientService
from app.services.protocol import ProtocolService
from tests.concurrency import ATTEMPTS, run_concurrently
from tests.fakes import FakeClock

HASHER = Hasher(phone_salt=SecretStr("phone-salt-0000000"), patient_id_salt=SecretStr("event-salt-0000000"))
CATALOG = FileTemplateCatalog.load(Path(__file__).resolve().parent.parent / "templates")


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

    results = run_concurrently(make_service, answer_q1)

    # Nenhum erro (todos recebem 200) e todos veem a mesma próxima pergunta.
    assert results == ["q2"] * ATTEMPTS
    assert count(session_factory, ProtocolAnswerRow) == 1


def test_simultaneous_final_answers_create_one_journey(
    make_service: Callable[[], ProtocolService], patient_id: str, session_factory: sessionmaker[Session]
) -> None:
    service = make_service()
    session_id = service.start(patient_id, "phq9", "Perder 5kg").session.session_id
    service.answer(session_id, "q1", 1)

    results = run_concurrently(make_service, lambda s: s.answer(session_id, "q2", 1).journey)

    journeys = {r.journey_id for r in results if not isinstance(r, str) and r is not None}
    assert len(journeys) == 1, results
    assert count(session_factory, JourneyRow) == 1
    with session_factory() as session:
        completed = select(func.count()).where(EventRow.event_name == "protocol_completed")
        assert session.scalar(completed) == 1


def test_simultaneous_starts_create_one_session(
    make_service: Callable[[], ProtocolService], patient_id: str, session_factory: sessionmaker[Session]
) -> None:
    results = run_concurrently(make_service, lambda s: s.start(patient_id, "phq9", "Perder 5kg").session.session_id)

    errors = sorted(r for r in results if r == "protocol_in_progress")
    assert len(errors) == ATTEMPTS - 1, results
    assert count(session_factory, ProtocolSessionRow) == 1


# ─────────────── Follow-up ───────────────


def test_simultaneous_followup_evaluations_allow_one_followup(
    patient_id: str,
    session_factory: sessionmaker[Session],
    clock: FakeClock,
    make_service: Callable[[], ProtocolService],
) -> None:
    """O cooldown é "verifica, depois grava" sem constraint possível no banco: 10 avaliações simultâneas devem
    resultar em exatamente 1 follow-up elegível e 9 recusas por cooldown."""
    service = make_service()
    session_id = service.start(patient_id, "phq9", "Perder 5kg").session.session_id
    service.answer(session_id, "q1", 0)
    service.answer(session_id, "q2", 0)
    rules = load_followup_rules(Path(__file__).resolve().parent.parent / "rules" / "followup.json")

    def make_followup() -> FollowupService:
        return FollowupService(SqlAlchemyUnitOfWork(session_factory), EventStore(HASHER, clock), rules, clock)

    results = run_concurrently(make_followup, lambda s: s.evaluate(patient_id))

    assert sorted(type(r).__name__ for r in results) == ["Eligible"] + ["Skipped"] * (ATTEMPTS - 1), results
    with session_factory() as session:
        eligible = select(func.count()).where(EventRow.event_name == "followup_eligible")
        assert session.scalar(eligible) == 1
