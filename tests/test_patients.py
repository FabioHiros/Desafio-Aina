from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PATIENT_PAYLOAD, PII_VALUES
from tests.fakes import FakeClock


def event_names(client: TestClient, patient_id: str) -> list[str]:
    return [event["event_name"] for event in client.get("/events", params={"patient_id": patient_id}).json()]


# ─────────────── Cadastro ───────────────


def test_create_patient_returns_201_without_pii(client: TestClient) -> None:
    response = client.post("/patients", json=PATIENT_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"patient_id", "sex", "terms_accepted", "terms_accepted_at", "created_at"}
    assert body["terms_accepted"] is True
    for value in PII_VALUES:
        assert value not in response.text


def test_create_patient_with_terms_emits_created_and_accepted(client: TestClient, patient_id: str) -> None:
    assert event_names(client, patient_id) == ["patient_created", "terms_accepted"]


def test_create_patient_without_terms_emits_only_created(client: TestClient) -> None:
    response = client.post("/patients", json={**PATIENT_PAYLOAD, "terms_accepted": False})

    assert response.json()["terms_accepted"] is False
    assert response.json()["terms_accepted_at"] is None
    assert event_names(client, response.json()["patient_id"]) == ["patient_created"]


def test_same_phone_with_different_formatting_is_a_duplicate(client: TestClient, patient_id: str) -> None:
    response = client.post("/patients", json={**PATIENT_PAYLOAD, "phone": "5511987654321"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "patient_already_exists"
    for value in PII_VALUES:
        assert value not in response.text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phone", "123"),
        ("phone", "+55 11 98765-4321 ramal 1234567"),
        ("name", "   "),
        ("birth_date", "2999-01-01"),
        ("birth_date", "not-a-date"),
        ("sex", "X"),
        ("terms_accepted", "maybe"),
    ],
)
def test_invalid_payload_returns_422(client: TestClient, field: str, value: Any) -> None:
    response = client.post("/patients", json={**PATIENT_PAYLOAD, field: value})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_fields_are_rejected(client: TestClient) -> None:
    response = client.post("/patients", json={**PATIENT_PAYLOAD, "cpf": "000.000.000-00"})
    assert response.status_code == 422


def test_get_patient(client: TestClient, patient_id: str) -> None:
    response = client.get(f"/patients/{patient_id}")

    assert response.status_code == 200
    assert response.json()["patient_id"] == patient_id


def test_get_unknown_patient_returns_404(client: TestClient) -> None:
    response = client.get("/patients/00000000-0000-4000-8000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "patient_not_found"


def test_malformed_patient_id_returns_422(client: TestClient) -> None:
    assert client.get("/patients/not-a-uuid").status_code == 422


# ─────────────── Aceite posterior dos termos ───────────────


def test_accept_terms_after_registration(client: TestClient, clock: FakeClock) -> None:
    patient_id = client.post("/patients", json={**PATIENT_PAYLOAD, "terms_accepted": False}).json()["patient_id"]
    clock.advance(hours=1)

    response = client.post(f"/patients/{patient_id}/terms")

    assert response.status_code == 200
    assert response.json()["terms_accepted"] is True
    assert response.json()["terms_accepted_at"] == clock.now().isoformat().replace("+00:00", "Z")
    assert event_names(client, patient_id) == ["patient_created", "terms_accepted"]


def test_accept_terms_is_idempotent(client: TestClient, patient_id: str, clock: FakeClock) -> None:
    first = client.post(f"/patients/{patient_id}/terms").json()
    clock.advance(hours=1)
    second = client.post(f"/patients/{patient_id}/terms").json()

    assert first["terms_accepted_at"] == second["terms_accepted_at"]
    assert event_names(client, patient_id).count("terms_accepted") == 1


def test_accept_terms_for_unknown_patient_returns_404(client: TestClient) -> None:
    assert client.post("/patients/00000000-0000-4000-8000-000000000000/terms").status_code == 404
