from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.database import create_db_engine, create_session_factory
from app.main import create_app
from app.repositories.tables import init_db
from tests.fakes import FakeClock

PATIENT_PAYLOAD: dict[str, Any] = {
    "phone": "+55 (11) 98765-4321",
    "name": "Maria Teste da Silva",
    "birth_date": "1990-05-10",
    "sex": "F",
    "terms_accepted": True,
}
PHONE_DIGITS = "5511987654321"
PII_VALUES = (PHONE_DIGITS, "98765-4321", "987654321", "Maria Teste da Silva", "1990-05-10")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """Banco SQLite novo por teste."""
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        phone_hash_salt=SecretStr("test-phone-salt-0000"),
        event_hash_salt=SecretStr("test-event-salt-0000"),
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        log_level="INFO",
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(settings: Settings, clock: FakeClock) -> Iterator[TestClient]:
    with TestClient(create_app(settings, clock)) as client:
        yield client


@pytest.fixture
def patient_id(client: TestClient) -> str:
    response = client.post("/patients", json=PATIENT_PAYLOAD)
    assert response.status_code == 201
    return str(response.json()["patient_id"])
