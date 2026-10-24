"""SqlAlchemyUnitOfWork: atomicidade, commit explícito, guardas de uso e concorrência com banco real."""

from datetime import date

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import Hasher
from app.models.patient import NewPatient, Sex
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork

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
