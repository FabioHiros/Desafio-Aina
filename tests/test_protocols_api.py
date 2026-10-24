"""Protocolo via HTTP: os testes obrigatórios do enunciado (skip PHQ-2, recusa sem termos) e os contratos."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PATIENT_PAYLOAD

OBJETIVO = "Perder 5kg em 3 meses"


def start(client: TestClient, patient_id: str, **overrides: Any) -> Any:
    response = client.post(
        f"/patients/{patient_id}/protocols", json={"template_id": "phq9", "objetivo": OBJETIVO, **overrides}
    )
    return response


def answer(client: TestClient, session_id: str, question_id: str, value: Any) -> Any:
    return client.post(f"/protocol-sessions/{session_id}/answers", json={"question_id": question_id, "value": value})


def answer_all(client: TestClient, session_id: str, *values: int) -> dict[str, Any]:
    body: dict[str, Any] = client.get(f"/protocol-sessions/{session_id}").json()
    for value in values:
        response = answer(client, session_id, body["next_question"]["question_id"], value)
        assert response.status_code == 200, response.text
        body = response.json()
    return body


@pytest.fixture
def session_id(client: TestClient, patient_id: str) -> str:
    response = start(client, patient_id)
    assert response.status_code == 201, response.text
    return str(response.json()["session_id"])


def event_names(client: TestClient, patient_id: str) -> list[str]:
    return [e["event_name"] for e in client.get("/events", params={"patient_id": patient_id}).json()]


# ─────────────── Início ───────────────


def test_start_returns_first_question(client: TestClient, patient_id: str) -> None:
    response = start(client, patient_id)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "em_andamento"
    assert (body["score"], body["ended_by_skip"], body["journey_id"]) == (None, None, None)
    question = body["next_question"]
    assert question["question_id"] == "q1"
    assert question["text"] == "Pouco interesse ou prazer em fazer as coisas"
    assert (question["position"], question["total"]) == (1, 9)
    assert question["instructions"].startswith("Nas últimas duas semanas")
    assert [o["value"] for o in question["scale"]] == [0, 1, 2, 3]
    assert OBJETIVO not in response.text


def test_start_without_consent_is_refused(client: TestClient) -> None:
    """Obrigatório: sem terms_accepted=true não se inicia protocolo."""
    patient_id = client.post("/patients", json={**PATIENT_PAYLOAD, "terms_accepted": False}).json()["patient_id"]

    response = start(client, patient_id)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "missing_consent"
    assert event_names(client, patient_id) == ["patient_created"]


def test_start_after_accepting_terms(client: TestClient) -> None:
    patient_id = client.post("/patients", json={**PATIENT_PAYLOAD, "terms_accepted": False}).json()["patient_id"]
    client.post(f"/patients/{patient_id}/terms")

    assert start(client, patient_id).status_code == 201


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"template_id": "unknown"}, 404, "template_not_found"),
        ({"objetivo": "   "}, 422, "validation_error"),
        ({"objetivo": "x" * 501}, 422, "validation_error"),
        ({"extra": 1}, 422, "validation_error"),
    ],
)
def test_start_validation(
    client: TestClient, patient_id: str, overrides: dict[str, Any], status: int, code: str
) -> None:
    response = start(client, patient_id, **overrides)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_start_for_unknown_patient(client: TestClient) -> None:
    response = start(client, "00000000-0000-4000-8000-000000000000")
    assert (response.status_code, response.json()["error"]["code"]) == (404, "patient_not_found")


def test_second_session_in_progress_is_refused(client: TestClient, patient_id: str, session_id: str) -> None:
    response = start(client, patient_id)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "protocol_in_progress")


# ─────────────── Skip logic (obrigatório) ───────────────


def test_phq2_skip_ends_with_partial_score(client: TestClient, patient_id: str, session_id: str) -> None:
    """Obrigatório: q1 + q2 < 3 encerra o bloco, conclui o protocolo e devolve a soma parcial."""
    body = answer_all(client, session_id, 1, 1)

    assert body["status"] == "concluido"
    assert (body["score"], body["ended_by_skip"]) == (2, True)
    assert body["next_question"] is None
    assert body["journey_id"] is not None
    assert event_names(client, patient_id)[-3:] == ["protocol_started", "protocol_completed", "journey_created"]


def test_no_skip_goes_through_all_nine_questions(client: TestClient, session_id: str) -> None:
    body = answer_all(client, session_id, 2, 1)
    assert body["next_question"]["question_id"] == "q3"

    body = answer_all(client, session_id, 3, 3, 2, 1, 0, 1, 2)

    assert body["status"] == "concluido"
    assert (body["score"], body["ended_by_skip"]) == (15, False)


# ─────────────── Respostas idempotentes ───────────────


def test_identical_resend_returns_the_same_body(client: TestClient, session_id: str) -> None:
    first = answer(client, session_id, "q1", 2)
    again = answer(client, session_id, "q1", 2)

    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json() == first.json()


def test_resend_of_final_answer_returns_the_result_again(client: TestClient, session_id: str) -> None:
    final = answer_all(client, session_id, 0, 0)
    again = answer(client, session_id, "q2", 0)

    assert again.status_code == 200
    assert again.json() == final


@pytest.mark.parametrize(
    ("question_id", "value", "status", "code"),
    [
        ("q1", 3, 409, "answer_already_recorded"),
        ("q5", 1, 409, "unexpected_question"),
        ("q2", 4, 422, "invalid_answer"),
        ("q2", -1, 422, "invalid_answer"),
        ("q2", "2", 422, "validation_error"),
        ("q2", 1.5, 422, "validation_error"),
        ("q2", True, 422, "validation_error"),
    ],
)
def test_answer_errors(
    client: TestClient, session_id: str, question_id: str, value: Any, status: int, code: str
) -> None:
    answer(client, session_id, "q1", 2)

    response = answer(client, session_id, question_id, value)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_unexpected_question_says_which_is_expected(client: TestClient, session_id: str) -> None:
    response = answer(client, session_id, "q3", 1)
    assert "Esperada: q1" in response.json()["error"]["message"]


def test_new_answer_after_completion_is_refused(client: TestClient, session_id: str) -> None:
    answer_all(client, session_id, 0, 0)

    response = answer(client, session_id, "q3", 1)

    assert (response.status_code, response.json()["error"]["code"]) == (409, "session_closed")


def test_unknown_or_malformed_session(client: TestClient) -> None:
    unknown = answer(client, "00000000-0000-4000-8000-000000000000", "q1", 1)
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "protocol_session_not_found")
    assert answer(client, "not-a-uuid", "q1", 1).status_code == 422


def test_get_session_resumes_where_it_stopped(client: TestClient, session_id: str) -> None:
    answer(client, session_id, "q1", 2)

    body = client.get(f"/protocol-sessions/{session_id}").json()

    assert body["next_question"]["question_id"] == "q2"
