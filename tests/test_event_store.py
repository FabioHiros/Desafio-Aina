from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import Hasher
from app.models.events import DomainEvent, EventName, FollowupEligible, ProtocolCompleted
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.services.event_store import EventStore
from tests.fakes import FakeClock

HASHER = Hasher(phone_salt=SecretStr("phone-salt-0000000"), patient_id_salt=SecretStr("event-salt-0000000"))


class LeakyEvent(DomainEvent):
    """Simula alguém adicionando um campo proibido a um evento no futuro."""

    event_name = EventName.PATIENT_CREATED
    phone: str


@pytest.fixture
def store(clock: FakeClock) -> EventStore:
    return EventStore(HASHER, clock)


@pytest.fixture
def uow(session_factory: sessionmaker[Session]) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory)


# ─────────────── EventStore (unidade, banco real) ───────────────


def test_append_hashes_patient_id(store: EventStore, uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        event = store.append(uow, "p-1", FollowupEligible(template_key="checkin_adesao"))
        uow.commit()

    assert event.patient_id_hash == HASHER.hash_patient_id("p-1")
    assert "p-1" not in event.patient_id_hash
    assert event.event_name == EventName.FOLLOWUP_ELIGIBLE
    assert event.properties == {"template_key": "checkin_adesao"}


def test_event_properties_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        FollowupEligible(template_key="x", phone="5511987654321")  # type: ignore[call-arg]


def test_append_rejects_pii_keys_even_if_schema_allows_them(store: EventStore, uow: SqlAlchemyUnitOfWork) -> None:
    with pytest.raises(ValueError, match="PII"), uow:
        store.append(uow, "p-1", LeakyEvent(phone="5511987654321"))


def test_events_are_listed_in_write_order_even_with_same_timestamp(
    store: EventStore, uow: SqlAlchemyUnitOfWork
) -> None:
    with uow:
        store.append(uow, "p-1", FollowupEligible(template_key="a"))
        store.append(uow, "p-1", ProtocolCompleted(session_id="s", template_id="phq9", score=1, ended_by_skip=True))
        store.append(uow, "p-1", FollowupEligible(template_key="b"))
        uow.commit()

    with uow:
        events = store.list_by_patient(uow, "p-1")
    assert [e.position for e in events] == sorted(e.position for e in events)
    assert [e.properties.get("template_key") for e in events] == ["a", None, "b"]


def test_events_are_isolated_per_patient(store: EventStore, uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        store.append(uow, "p-1", FollowupEligible(template_key="a"))
        store.append(uow, "p-2", FollowupEligible(template_key="b"))
        uow.commit()

    with uow:
        assert [e.properties["template_key"] for e in store.list_by_patient(uow, "p-1")] == ["a"]


def test_exists_since_respects_the_window(store: EventStore, uow: SqlAlchemyUnitOfWork, clock: FakeClock) -> None:
    with uow:
        store.append(uow, "p-1", FollowupEligible(template_key="a"))
        uow.commit()
    written_at = clock.now()

    with uow:
        assert store.exists_since(uow, "p-1", EventName.FOLLOWUP_ELIGIBLE, written_at - timedelta(hours=72))
        assert not store.exists_since(uow, "p-1", EventName.FOLLOWUP_ELIGIBLE, written_at)
        assert not store.exists_since(uow, "p-1", EventName.FOLLOWUP_SKIPPED, written_at - timedelta(hours=72))


def test_events_without_commit_are_discarded(store: EventStore, uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        store.append(uow, "p-1", FollowupEligible(template_key="a"))  # sem commit

    with uow:
        assert store.list_by_patient(uow, "p-1") == []


def test_event_is_rolled_back_with_the_failed_operation(store: EventStore, uow: SqlAlchemyUnitOfWork) -> None:
    def failing_operation() -> None:
        with uow:
            store.append(uow, "p-1", FollowupEligible(template_key="a"))
            raise RuntimeError("falha antes do commit")

    with pytest.raises(RuntimeError):
        failing_operation()

    with uow:
        assert store.list_by_patient(uow, "p-1") == []


# ─────────────── GET /events ───────────────


def test_list_events_returns_envelope(client: TestClient, patient_id: str) -> None:
    response = client.get("/events", params={"patient_id": patient_id})

    assert response.status_code == 200
    first = response.json()[0]
    assert set(first) == {"event_id", "occurred_at", "event_name", "patient_id_hash", "properties"}
    assert patient_id not in response.text  # só o hash sai na trilha


def test_list_events_for_unknown_patient_is_empty(client: TestClient) -> None:
    response = client.get("/events", params={"patient_id": "00000000-0000-4000-8000-000000000000"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("params", [{}, {"patient_id": "not-a-uuid"}])
def test_list_events_requires_valid_patient_id(client: TestClient, params: dict[str, str]) -> None:
    assert client.get("/events", params=params).status_code == 422


def test_last_occurrence_is_the_latest_event_of_that_type(
    store: EventStore, uow: SqlAlchemyUnitOfWork, clock: FakeClock
) -> None:
    with uow:
        assert store.last_occurrence(uow, "p-1", EventName.FOLLOWUP_ELIGIBLE) is None
        store.append(uow, "p-1", FollowupEligible(template_key="a"))
        clock.advance(hours=5)
        store.append(uow, "p-1", FollowupEligible(template_key="b"))
        latest = clock.now()
        clock.advance(hours=1)
        store.append(uow, "p-1", ProtocolCompleted(session_id="s", template_id="phq9", score=1, ended_by_skip=True))
        store.append(uow, "p-2", FollowupEligible(template_key="c"))
        uow.commit()

    with uow:
        assert store.last_occurrence(uow, "p-1", EventName.FOLLOWUP_ELIGIBLE) == latest
        assert store.last_occurrence(uow, "p-1", EventName.FOLLOWUP_SKIPPED) is None
