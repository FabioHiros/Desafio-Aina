"""Testes obrigatórios de PII: telefone, nome e data de nascimento nunca saem do cadastro."""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import Settings
from app.main import create_app
from tests.conftest import PATIENT_PAYLOAD, PII_VALUES
from tests.fakes import FakeClock


def test_events_never_contain_pii(client: TestClient) -> None:
    patient_id = client.post("/patients", json={**PATIENT_PAYLOAD, "terms_accepted": False}).json()["patient_id"]
    client.post(f"/patients/{patient_id}/terms")

    trail = client.get("/events", params={"patient_id": patient_id}).text
    assert json.loads(trail)  # a trilha não está vazia
    for value in PII_VALUES:
        assert value not in trail


def test_persisted_events_never_contain_pii(client: TestClient, patient_id: str, settings: Settings) -> None:
    """Além da resposta da API: lê a tabela events direto do banco."""
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT * FROM events")).fetchall()
    engine.dispose()

    dumped = repr(rows)
    assert rows
    for value in PII_VALUES:
        assert value not in dumped


def test_validation_error_does_not_echo_input(client: TestClient) -> None:
    payload = {**PATIENT_PAYLOAD, "sex": "invalid", "terms_accepted": "invalid"}
    response = client.post("/patients", json=payload)

    assert response.status_code == 422
    for value in PII_VALUES:
        assert value not in response.text


def test_invalid_phone_is_not_echoed(client: TestClient) -> None:
    response = client.post("/patients", json={**PATIENT_PAYLOAD, "phone": "98765"})

    assert response.status_code == 422
    assert "98765" not in response.text


def test_logs_never_contain_pii(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        patient_id = client.post("/patients", json=PATIENT_PAYLOAD).json()["patient_id"]
        client.post("/patients", json=PATIENT_PAYLOAD)  # 409
        client.post("/patients", json={**PATIENT_PAYLOAD, "sex": "X"})  # 422
        client.get("/events", params={"patient_id": patient_id})

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert logged  # houve log de requisições
    for value in PII_VALUES:
        assert value not in logged


def test_unexpected_error_returns_generic_500_without_pii(settings: Settings, clock: FakeClock) -> None:
    app = create_app(settings, clock)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(f"falha com {PATIENT_PAYLOAD['phone']}")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error", "message": "Erro interno."}}
