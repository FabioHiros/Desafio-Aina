import threading
from datetime import date, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import PatientAlreadyExistsError
from app.core.security import Hasher
from app.models.events import EventName, FollowupEligible, PatientCreated
from app.models.patient import NewPatient, Sex
from app.repositories.tables import EventRow, PatientRow
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.services.event_store import EventStore
from app.services.patient import PatientService
from tests.fakes import FakeClock

HASHER = Hasher(phone_salt=SecretStr("phone-salt-0000000"), patient_id_salt=SecretStr("event-salt-0000000"))
NEW_PATIENT = NewPatient(
    phone="5511987654321", name="Maria Teste", birth_date=date(1990, 5, 10), sex=Sex.F, terms_accepted=True
)


@pytest.fixture
def uow(session_factory: sessionmaker[Session]) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory)


def test_repositories_are_unavailable_outside_the_block(uow: SqlAlchemyUnitOfWork) -> None:
    with pytest.raises(RuntimeError, match="fora de um bloco"):
        _ = uow.patients


def test_unit_of_work_is_not_reentrant(uow: SqlAlchemyUnitOfWork) -> None:
    with uow, pytest.raises(RuntimeError, match="reentrante"), uow:
        pass


def test_unit_of_work_can_be_reused_sequentially(uow: SqlAlchemyUnitOfWork, clock: FakeClock) -> None:
    store = EventStore(HASHER, clock)
    with uow:
        store.append(uow, "p-1", PatientCreated())
        uow.commit()
    with uow:
        assert len(store.list_by_patient(uow, "p-1")) == 1


def test_nothing_is_saved_without_commit(uow: SqlAlchemyUnitOfWork, clock: FakeClock) -> None:
    service = PatientService(uow, EventStore(HASHER, clock), HASHER, clock)
    patient = service.register(NEW_PATIENT)

    with uow:
        assert uow.patients.get(patient.patient_id) == patient

    with uow:
        uow.patients.mark_terms_accepted(patient.patient_id, clock.now())
    with uow:
        assert uow.patients.get(patient.patient_id) == patient


def test_concurrent_registrations_of_the_same_phone(session_factory: sessionmaker[Session], clock: FakeClock) -> None:
    """10 threads cadastram o mesmo telefone ao mesmo tempo: exatamente 1 cadastro, 9 conflitos, nenhum erro 500
    ("database is locked") e exatamente um patient_created na trilha."""
    attempts = 10
    barrier = threading.Barrier(attempts)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def register() -> None:
        service = PatientService(SqlAlchemyUnitOfWork(session_factory), EventStore(HASHER, clock), HASHER, clock)
        barrier.wait()
        try:
            service.register(NEW_PATIENT)
            outcome = "created"
        except PatientAlreadyExistsError:
            outcome = "duplicate"
        except Exception as exc:
            outcome = f"error: {type(exc).__name__}: {exc}"
        with outcomes_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=register) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["created"] + ["duplicate"] * (attempts - 1)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PatientRow)) == 1
        created_events = select(func.count()).where(EventRow.event_name == EventName.PATIENT_CREATED.value)
        assert session.scalar(created_events) == 1


def test_concurrent_check_then_write_is_serialized(session_factory: sessionmaker[Session], clock: FakeClock) -> None:
    """O padrão do cooldown de 72h: "se não existe evento recente, grava um". Não há constraint de banco que
    proteja isso; só a serialização das transações (BEGIN IMMEDIATE) impede que duas requisições simultâneas
    leiam "não existe" e gravem as duas. Esperado: exatamente um evento e nenhum erro."""
    attempts = 10
    barrier = threading.Barrier(attempts)
    errors: list[str] = []
    store = EventStore(HASHER, clock)
    window_start = clock.now() - timedelta(hours=72)

    def check_then_write() -> None:
        uow = SqlAlchemyUnitOfWork(session_factory)
        barrier.wait()
        try:
            with uow:
                if not store.exists_since(uow, "p-1", EventName.FOLLOWUP_ELIGIBLE, window_start):
                    store.append(uow, "p-1", FollowupEligible(template_key="checkin_adesao"))
                    uow.commit()
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=check_then_write) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with session_factory() as session:
        eligible = select(func.count()).where(EventRow.event_name == EventName.FOLLOWUP_ELIGIBLE.value)
        assert session.scalar(eligible) == 1
