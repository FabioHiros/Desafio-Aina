from dataclasses import dataclass
from datetime import date

import pytest
from pydantic import SecretStr

from app.core.errors import JourneyNotFoundError, PatientNotFoundError, TaskNotFoundError
from app.core.security import Hasher
from app.models.events import EventName
from app.models.journey import Journey, JourneyStatus, Task, TaskStatus
from app.models.patient import Patient, Sex
from app.services.event_store import EventStore
from app.services.journey import JourneyService
from tests.fakes import FakeClock, InMemoryUnitOfWork


@dataclass
class World:
    service: JourneyService
    uow: InMemoryUnitOfWork
    clock: FakeClock

    def events(self) -> list[EventName]:
        return [e.event_name for e in self.uow.events.events]


@pytest.fixture
def world() -> World:
    uow, clock = InMemoryUnitOfWork(), FakeClock()
    uow.patients.patients["p-1"] = Patient(
        patient_id="p-1",
        phone="5511987654321",
        phone_hash="hash",
        name="Maria Teste",
        birth_date=date(1990, 5, 10),
        sex=Sex.F,
        terms_accepted=True,
        terms_accepted_at=clock.now(),
        created_at=clock.now(),
    )
    uow.journeys.journeys["j-1"] = Journey(
        journey_id="j-1",
        patient_id="p-1",
        session_id="s-1",
        objetivo="Perder 5kg",
        status=JourneyStatus.IN_PROGRESS,
        created_at=clock.now(),
        completed_at=None,
        tasks=tuple(Task(f"t-{i}", i, f"Tarefa {i}", TaskStatus.IN_PROGRESS, None) for i in (1, 2)),
    )
    hasher = Hasher(phone_salt=SecretStr("phone-salt-0000000"), patient_id_salt=SecretStr("event-salt-0000000"))
    return World(JourneyService(uow, EventStore(hasher, clock), clock), uow, clock)


def test_complete_task_emits_event_and_keeps_journey_open(world: World) -> None:
    world.clock.advance(hours=1)

    journey = world.service.complete_task("j-1", "t-1")

    task = journey.task("t-1")
    assert task is not None
    assert (task.status, task.completed_at) == (TaskStatus.COMPLETED, world.clock.now())
    assert journey.status is JourneyStatus.IN_PROGRESS
    assert world.events() == [EventName.TASK_COMPLETED]
    assert world.uow.events.events[0].properties == {"journey_id": "j-1", "task_id": "t-1"}


def test_last_task_completes_the_journey(world: World) -> None:
    world.service.complete_task("j-1", "t-1")
    world.clock.advance(hours=1)

    journey = world.service.complete_task("j-1", "t-2")

    assert journey.status is JourneyStatus.COMPLETED
    assert journey.completed_at == world.clock.now()
    assert not journey.has_active_task
    assert world.events() == [EventName.TASK_COMPLETED, EventName.TASK_COMPLETED, EventName.JOURNEY_COMPLETED]
    assert world.uow.events.events[-1].properties == {"journey_id": "j-1"}


def test_completing_twice_is_idempotent(world: World) -> None:
    first = world.service.complete_task("j-1", "t-1")
    world.clock.advance(hours=1)

    again = world.service.complete_task("j-1", "t-1")

    assert again == first
    assert world.events() == [EventName.TASK_COMPLETED]


def test_unknown_journey_or_task(world: World) -> None:
    with pytest.raises(JourneyNotFoundError):
        world.service.complete_task("nope", "t-1")
    with pytest.raises(TaskNotFoundError):
        world.service.complete_task("j-1", "nope")


def test_current_journey_for_patient(world: World) -> None:
    assert world.service.current_for_patient("p-1").journey_id == "j-1"

    with pytest.raises(PatientNotFoundError):
        world.service.current_for_patient("nope")

    world.uow.journeys.journeys.clear()
    with pytest.raises(JourneyNotFoundError):
        world.service.current_for_patient("p-1")
