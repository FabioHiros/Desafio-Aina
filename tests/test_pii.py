import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import Settings
from app.core.security import keyed_hash
from app.main import create_app
from app.models.events import EventName
from tests.conftest import PATIENT_PAYLOAD, PHONE_DIGITS, PII_VALUES
from tests.fakes import FakeClock


def stored_events(settings: Settings) -> str:
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT * FROM events")).fetchall()
    engine.dispose()
    return repr(rows)


def test_events_never_contain_pii(client: TestClient) -> None:
    patient_id = client.post("/patients", json={**PATIENT_PAYLOAD, "terms_accepted": False}).json()["patient_id"]
    client.post(f"/patients/{patient_id}/terms")

    trail = client.get("/events", params={"patient_id": patient_id}).text
    assert json.loads(trail)
    for value in PII_VALUES:
        assert value not in trail


def test_persisted_events_never_contain_pii(client: TestClient, patient_id: str, settings: Settings) -> None:
    dumped = stored_events(settings)
    assert dumped != "[]"
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
        client.post("/patients", json=PATIENT_PAYLOAD)
        client.post("/patients", json={**PATIENT_PAYLOAD, "sex": "X"})
        client.get("/events", params={"patient_id": patient_id})

    logged = caplog.text
    assert "POST /patients -> 409" in logged
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


def test_objective_never_reaches_the_event_trail(client: TestClient, patient_id: str, settings: Settings) -> None:
    objetivo = "Controlar a ansiedade depois do diagnóstico"
    session_id = client.post(
        f"/patients/{patient_id}/protocols", json={"template_id": "phq9", "objetivo": objetivo}
    ).json()["session_id"]
    for question_id in ("q1", "q2"):
        client.post(f"/protocol-sessions/{session_id}/answers", json={"question_id": question_id, "value": 0})

    trail = client.get("/events", params={"patient_id": patient_id}).text
    assert "journey_created" in trail
    assert objetivo not in trail

    assert objetivo not in stored_events(settings)


def test_full_journey_trail_never_contains_pii(
    client: TestClient, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        created = client.post("/patients", json=PATIENT_PAYLOAD)
        assert created.status_code == 201
        patient_id = created.json()["patient_id"]

        started = client.post(
            f"/patients/{patient_id}/protocols", json={"template_id": "phq9", "objetivo": "Dormir melhor"}
        )
        assert started.status_code == 201
        session_id = started.json()["session_id"]
        for question_id in ("q1", "q2"):
            answered = client.post(
                f"/protocol-sessions/{session_id}/answers", json={"question_id": question_id, "value": 0}
            )
            assert answered.status_code == 200
        assert answered.json()["ended_by_skip"] is True

        journey = client.get(f"/patients/{patient_id}/journey")
        assert journey.status_code == 200

        first = client.post("/followups/evaluate", json={"patient_id": patient_id})
        second = client.post("/followups/evaluate", json={"patient_id": patient_id})
        assert first.json()["eligible"] is True
        assert second.json()["reason"] == "cooldown"

        for task in journey.json()["tarefas"]:
            completed = client.patch(
                f"/journeys/{journey.json()['journey_id']}/tasks/{task['id']}", json={"status": "concluida"}
            )
            assert completed.status_code == 200
        assert completed.json()["status"] == "concluida"

        events = client.get("/events", params={"patient_id": patient_id})
        assert events.status_code == 200

    trail = events.text
    assert {event["event_name"] for event in events.json()} == set(EventName)

    stored = stored_events(settings)

    logged = caplog.text
    assert "POST /followups/evaluate -> 200" in logged

    phone_hash = keyed_hash(PHONE_DIGITS, settings.phone_hash_salt)
    for value in (*PII_VALUES, phone_hash):
        assert value not in trail
        assert value not in stored
        assert value not in logged
    assert patient_id not in trail
    assert patient_id not in stored
