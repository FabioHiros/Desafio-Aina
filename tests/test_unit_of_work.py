"""SqlAlchemyUnitOfWork: atomicidade, commit explícito, guardas de uso e concorrência com banco real."""

from datetime import date

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import Hasher
from app.models.events import PatientCreated
from app.models.patient import NewPatient, Sex
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


# ─────────────── Guardas de uso ───────────────


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
        uow.patients.mark_terms_accepted(patient.patient_id, clock.now())  # sem commit
    with uow:
        assert uow.patients.get(patient.patient_id) == patient
