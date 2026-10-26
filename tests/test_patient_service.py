from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.errors import PatientAlreadyExistsError, PatientNotFoundError
from app.core.security import Hasher
from app.models.events import Event, EventName
from app.models.patient import NewPatient, Sex
from app.services.event_store import EventStore
from app.services.patient import PatientService
from tests.fakes import FakeClock, InMemoryUnitOfWork

NEW_PATIENT = NewPatient(
    phone="5511987654321", name="Maria Teste", birth_date=date(1990, 5, 10), sex=Sex.F, terms_accepted=True
)
WITHOUT_TERMS = replace(NEW_PATIENT, terms_accepted=False)


@dataclass
class World:
    service: PatientService
    uow: InMemoryUnitOfWork
    clock: FakeClock


@pytest.fixture
def world() -> World:
    uow, clock = InMemoryUnitOfWork(), FakeClock()
    hasher = Hasher(phone_salt=SecretStr("phone-salt-0000000"), patient_id_salt=SecretStr("event-salt-0000000"))
    return World(PatientService(uow, EventStore(hasher, clock), hasher, clock), uow, clock)


def event_names(world: World) -> list[EventName]:
    return [e.event_name for e in world.uow.events.events]


def test_register_stores_hash_and_emits_events_in_one_commit(world: World) -> None:
    patient = world.service.register(NEW_PATIENT)

    assert world.uow.patients.get(patient.patient_id) == patient
    assert patient.phone_hash != NEW_PATIENT.phone
    assert patient.terms_accepted_at == world.clock.now()
    assert event_names(world) == [EventName.PATIENT_CREATED, EventName.TERMS_ACCEPTED]
    assert world.uow.commits == 1


def test_register_without_terms_emits_only_created(world: World) -> None:
    patient = world.service.register(WITHOUT_TERMS)

    assert patient.terms_accepted_at is None
    assert event_names(world) == [EventName.PATIENT_CREATED]


def test_register_duplicate_phone_leaves_no_trace(world: World) -> None:
    world.service.register(NEW_PATIENT)

    with pytest.raises(PatientAlreadyExistsError):
        world.service.register(NEW_PATIENT)

    assert len(world.uow.patients.patients) == 1
    assert event_names(world) == [EventName.PATIENT_CREATED, EventName.TERMS_ACCEPTED]
    assert world.uow.commits == 1


def test_failure_after_writing_rolls_back_state_and_events(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_on_terms(*args: object, **kwargs: object) -> None:
        raise RuntimeError("falha entre o cadastro e o evento de termos")

    original_append = world.uow.events.append

    def append(*args: Any, **kwargs: Any) -> Event:
        if kwargs.get("event_name") == EventName.TERMS_ACCEPTED:
            fail_on_terms()
        return original_append(*args, **kwargs)

    monkeypatch.setattr(world.uow.events, "append", append)

    with pytest.raises(RuntimeError):
        world.service.register(NEW_PATIENT)

    assert world.uow.patients.patients == {}
    assert world.uow.events.events == []
    assert world.uow.rollbacks == 1


def test_accept_terms_later(world: World) -> None:
    patient = world.service.register(WITHOUT_TERMS)
    world.clock.advance(hours=2)

    accepted = world.service.accept_terms(patient.patient_id)

    assert accepted.terms_accepted is True
    assert accepted.terms_accepted_at == world.clock.now()
    assert event_names(world) == [EventName.PATIENT_CREATED, EventName.TERMS_ACCEPTED]


def test_accept_terms_twice_keeps_first_date_and_single_event(world: World) -> None:
    patient = world.service.register(NEW_PATIENT)
    world.clock.advance(hours=2)

    again = world.service.accept_terms(patient.patient_id)

    assert again.terms_accepted_at == patient.terms_accepted_at
    assert event_names(world).count(EventName.TERMS_ACCEPTED) == 1


@pytest.mark.parametrize("operation", ["get", "accept_terms"])
def test_unknown_patient_raises_not_found(world: World, operation: str) -> None:
    with pytest.raises(PatientNotFoundError):
        getattr(world.service, operation)("does-not-exist")
