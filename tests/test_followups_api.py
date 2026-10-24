"""Follow-up via HTTP: o teste obrigatório de cooldown de 72h e cada motivo de recusa, a partir do fluxo real."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PATIENT_PAYLOAD
from tests.fakes import FakeClock

UNKNOWN = "00000000-0000-4000-8000-000000000000"
ELIGIBLE = {"eligible": True, "template_key": "checkin_adesao", "reason": None}


def evaluate(client: TestClient, patient_id: str) -> Any:
    return client.post("/followups/evaluate", json={"patient_id": patient_id})


def skipped(reason: str) -> dict[str, Any]:
    return {"eligible": False, "template_key": None, "reason": reason}


def complete_protocol(client: TestClient, patient_id: str) -> dict[str, Any]:
    session_id = client.post(
        f"/patients/{patient_id}/protocols", json={"template_id": "phq9", "objetivo": "Perder 5kg"}
    ).json()["session_id"]
    for question_id in ("q1", "q2"):
        client.post(f"/protocol-sessions/{session_id}/answers", json={"question_id": question_id, "value": 0})
    journey: dict[str, Any] = client.get(f"/patients/{patient_id}/journey").json()
    return journey


@pytest.fixture
def journey(client: TestClient, patient_id: str) -> dict[str, Any]:
    return complete_protocol(client, patient_id)


def followup_events(client: TestClient, patient_id: str) -> list[tuple[str, dict[str, Any]]]:
    events = client.get("/events", params={"patient_id": patient_id}).json()
    return [(e["event_name"], e["properties"]) for e in events if e["event_name"].startswith("followup_")]


def test_cooldown_72h(client: TestClient, patient_id: str, journey: dict[str, Any], clock: FakeClock) -> None:
    """Obrigatório: avaliar duas vezes e observar o cooldown; após 72h, elegível de novo."""
    first = evaluate(client, patient_id)
    second = evaluate(client, patient_id)

    assert (first.status_code, first.json()) == (200, ELIGIBLE)
    assert (second.status_code, second.json()) == (200, skipped("cooldown"))

    clock.advance(hours=71, minutes=59)
    assert evaluate(client, patient_id).json() == skipped("cooldown")

    clock.advance(minutes=1)
    assert evaluate(client, patient_id).json() == ELIGIBLE

    assert followup_events(client, patient_id) == [
        ("followup_eligible", {"template_key": "checkin_adesao"}),
        ("followup_skipped", {"reason": "cooldown"}),
        ("followup_skipped", {"reason": "cooldown"}),
        ("followup_eligible", {"template_key": "checkin_adesao"}),
    ]


def test_missing_consent(client: TestClient) -> None:
    patient_id = client.post("/patients", json={**PATIENT_PAYLOAD, "terms_accepted": False}).json()["patient_id"]

    assert evaluate(client, patient_id).json() == skipped("missing_consent")
    assert followup_events(client, patient_id) == [("followup_skipped", {"reason": "missing_consent"})]


def test_no_completed_protocol(client: TestClient, patient_id: str) -> None:
    assert evaluate(client, patient_id).json() == skipped("no_completed_protocol")


def test_protocol_in_progress_is_not_completed(client: TestClient, patient_id: str) -> None:
    client.post(f"/patients/{patient_id}/protocols", json={"template_id": "phq9", "objetivo": "x"})
    assert evaluate(client, patient_id).json() == skipped("no_completed_protocol")


def test_completed_journey_is_not_active(client: TestClient, patient_id: str, journey: dict[str, Any]) -> None:
    for task in journey["tarefas"]:
        client.patch(f"/journeys/{journey['journey_id']}/tasks/{task['id']}", json={"status": "concluida"})

    assert evaluate(client, patient_id).json() == skipped("no_active_journey")


def test_unknown_or_invalid_patient(client: TestClient) -> None:
    unknown = evaluate(client, UNKNOWN)
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "patient_not_found")
    assert evaluate(client, "not-a-uuid").status_code == 422
    assert client.post("/followups/evaluate", json={}).status_code == 422
