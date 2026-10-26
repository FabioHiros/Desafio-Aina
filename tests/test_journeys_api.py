from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeClock

OBJETIVO = "Perder 5kg em 3 meses"
UNKNOWN = "00000000-0000-4000-8000-000000000000"


def start(client: TestClient, patient_id: str) -> str:
    response = client.post(f"/patients/{patient_id}/protocols", json={"template_id": "phq9", "objetivo": OBJETIVO})
    return str(response.json()["session_id"])


def finish_by_skip(client: TestClient, session_id: str) -> dict[str, Any]:
    client.post(f"/protocol-sessions/{session_id}/answers", json={"question_id": "q1", "value": 0})
    response = client.post(f"/protocol-sessions/{session_id}/answers", json={"question_id": "q2", "value": 1})
    body: dict[str, Any] = response.json()
    return body


def complete(client: TestClient, journey_id: str, task_id: str, status: str = "concluida") -> Any:
    return client.patch(f"/journeys/{journey_id}/tasks/{task_id}", json={"status": status})


@pytest.fixture
def journey(client: TestClient, patient_id: str) -> dict[str, Any]:
    finish_by_skip(client, start(client, patient_id))
    body: dict[str, Any] = client.get(f"/patients/{patient_id}/journey").json()
    return body


def test_journey_only_exists_after_the_protocol_completes(client: TestClient, patient_id: str) -> None:
    before = client.get(f"/patients/{patient_id}/journey")
    assert (before.status_code, before.json()["error"]["code"]) == (404, "journey_not_found")

    session_id = start(client, patient_id)
    client.post(f"/protocol-sessions/{session_id}/answers", json={"question_id": "q1", "value": 0})
    assert client.get(f"/patients/{patient_id}/journey").status_code == 404

    result = finish_by_skip(client, session_id)
    after = client.get(f"/patients/{patient_id}/journey")

    assert after.status_code == 200
    assert after.json()["journey_id"] == result["journey_id"]
    assert after.json()["session_id"] == session_id


def test_journey_content(journey: dict[str, Any]) -> None:
    assert journey["objetivo"] == OBJETIVO
    assert journey["status"] == "em_andamento"
    assert journey["completed_at"] is None
    assert [t["titulo"] for t in journey["tarefas"]] == [
        "Registrar humor diariamente por 7 dias",
        "Definir um primeiro passo concreto para o objetivo",
        "Responder ao check-in semanal",
    ]
    assert {t["status"] for t in journey["tarefas"]} == {"em_andamento"}


def test_complete_task(client: TestClient, patient_id: str, journey: dict[str, Any], clock: FakeClock) -> None:
    clock.advance(hours=1)
    task_id = journey["tarefas"][0]["id"]

    response = complete(client, journey["journey_id"], task_id)

    assert response.status_code == 200
    task = response.json()["tarefas"][0]
    assert task["status"] == "concluida"
    assert task["completed_at"] == clock.now().isoformat().replace("+00:00", "Z")
    assert response.json()["status"] == "em_andamento"
    events = client.get("/events", params={"patient_id": patient_id}).json()
    assert events[-1]["event_name"] == "task_completed"
    assert events[-1]["properties"] == {"journey_id": journey["journey_id"], "task_id": task_id}


def test_completing_every_task_completes_the_journey(
    client: TestClient, patient_id: str, journey: dict[str, Any]
) -> None:
    for task in journey["tarefas"]:
        response = complete(client, journey["journey_id"], task["id"])
    complete(client, journey["journey_id"], journey["tarefas"][-1]["id"])

    assert response.json()["status"] == "concluida"
    assert response.json()["completed_at"] is not None
    events = client.get("/events", params={"patient_id": patient_id}).json()
    assert [e["event_name"] for e in events].count("journey_completed") == 1
    assert events[-1]["event_name"] == "journey_completed"
    assert events[-1]["properties"] == {"journey_id": journey["journey_id"]}


def test_completing_twice_is_idempotent(client: TestClient, patient_id: str, journey: dict[str, Any]) -> None:
    task_id = journey["tarefas"][0]["id"]
    first = complete(client, journey["journey_id"], task_id)
    again = complete(client, journey["journey_id"], task_id)

    assert again.json() == first.json()
    names = [e["event_name"] for e in client.get("/events", params={"patient_id": patient_id}).json()]
    assert names.count("task_completed") == 1


def test_new_protocol_is_refused_while_the_journey_is_active(
    client: TestClient, patient_id: str, journey: dict[str, Any]
) -> None:
    response = client.post(f"/patients/{patient_id}/protocols", json={"template_id": "phq9", "objetivo": "x"})
    assert (response.status_code, response.json()["error"]["code"]) == (409, "journey_already_active")


@pytest.mark.parametrize(
    ("journey_id", "task_id", "status", "expected"),
    [
        (UNKNOWN, None, "concluida", (404, "journey_not_found")),
        (None, UNKNOWN, "concluida", (404, "task_not_found")),
        (None, None, "em_andamento", (422, "validation_error")),
        ("not-a-uuid", None, "concluida", (422, "validation_error")),
    ],
)
def test_complete_task_errors(
    client: TestClient,
    journey: dict[str, Any],
    journey_id: str | None,
    task_id: str | None,
    status: str,
    expected: tuple[int, str],
) -> None:
    response = complete(client, journey_id or journey["journey_id"], task_id or journey["tarefas"][0]["id"], status)
    assert (response.status_code, response.json()["error"]["code"]) == expected


def test_journey_for_unknown_patient(client: TestClient) -> None:
    response = client.get(f"/patients/{UNKNOWN}/journey")
    assert (response.status_code, response.json()["error"]["code"]) == (404, "patient_not_found")
