from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.errors import PatientNotFoundError
from app.core.security import Hasher
from app.models.events import EventName
from app.models.followup import Eligible, Skipped, SkipReason
from app.models.journey import Journey, JourneyStatus, Task, TaskStatus
from app.models.patient import Patient, Sex
from app.models.protocol import ProtocolSession, SessionStatus
from app.repositories.rules import load_followup_rules
from app.services.event_store import EventStore
from app.services.followup import FollowupService
from tests.fakes import FakeClock, InMemoryUnitOfWork

RULES = load_followup_rules(Path(__file__).resolve().parent.parent / "rules" / "followup.json")
ELIGIBLE = Eligible(template_key="checkin_adesao")


@dataclass
class World:
    service: FollowupService
    uow: InMemoryUnitOfWork
    clock: FakeClock

    def events(self) -> list[tuple[EventName, dict[str, object]]]:
        return [(e.event_name, e.properties) for e in self.uow.events.events]

    def skipped(self, reason: SkipReason) -> None:
        assert self.service.evaluate("p-1") == Skipped(reason=reason)


@pytest.fixture
def world() -> World:
    uow, clock = InMemoryUnitOfWork(), FakeClock()
    now = clock.now()
    uow.patients.patients["p-1"] = Patient(
        "p-1", "5511987654321", "hash", "Maria", date(1990, 5, 10), Sex.F, True, now, now
    )
    uow.sessions.sessions["s-1"] = ProtocolSession(
        "s-1", "p-1", "phq9", "Perder 5kg", SessionStatus.COMPLETED, 2, True, now, now
    )
    uow.journeys.journeys["j-1"] = Journey(
        "j-1",
        "p-1",
        "s-1",
        "Perder 5kg",
        JourneyStatus.IN_PROGRESS,
        now,
        None,
        (Task("t-1", 1, "Tarefa", TaskStatus.IN_PROGRESS, None),),
    )
    hasher = Hasher(phone_salt=SecretStr("phone-salt-0000000"), patient_id_salt=SecretStr("event-salt-0000000"))
    return World(FollowupService(uow, EventStore(hasher, clock), RULES, clock), uow, clock)


def test_eligible_emits_followup_eligible_with_template_key(world: World) -> None:
    assert world.service.evaluate("p-1") == ELIGIBLE
    assert world.events() == [(EventName.FOLLOWUP_ELIGIBLE, {"template_key": "checkin_adesao"})]
    assert world.uow.commits == 1


def test_cooldown_72h(world: World) -> None:
    assert world.service.evaluate("p-1") == ELIGIBLE

    world.clock.advance(hours=1)
    world.skipped(SkipReason.COOLDOWN)

    world.clock.advance(hours=70, minutes=59)
    world.skipped(SkipReason.COOLDOWN)

    world.clock.advance(minutes=1)
    assert world.service.evaluate("p-1") == ELIGIBLE

    assert [name for name, _ in world.events()] == [
        EventName.FOLLOWUP_ELIGIBLE,
        EventName.FOLLOWUP_SKIPPED,
        EventName.FOLLOWUP_SKIPPED,
        EventName.FOLLOWUP_ELIGIBLE,
    ]


def test_skipped_evaluations_do_not_restart_the_cooldown(world: World) -> None:
    world.service.evaluate("p-1")
    for _ in range(5):
        world.clock.advance(hours=10)
        world.service.evaluate("p-1")
    world.clock.advance(hours=22)

    assert world.service.evaluate("p-1") == ELIGIBLE


def test_missing_consent(world: World) -> None:
    world.uow.patients.patients["p-1"] = replace(world.uow.patients.patients["p-1"], terms_accepted=False)
    world.skipped(SkipReason.MISSING_CONSENT)
    assert world.events() == [(EventName.FOLLOWUP_SKIPPED, {"reason": "missing_consent"})]


def test_no_completed_protocol(world: World) -> None:
    world.uow.sessions.sessions.clear()
    world.uow.journeys.journeys.clear()
    world.skipped(SkipReason.NO_COMPLETED_PROTOCOL)


def test_no_active_journey(world: World) -> None:
    journey = world.uow.journeys.journeys["j-1"]
    world.uow.journeys.journeys["j-1"] = replace(
        journey, status=JourneyStatus.COMPLETED, completed_at=journey.created_at
    )
    world.skipped(SkipReason.NO_ACTIVE_JOURNEY)


def test_no_active_task(world: World) -> None:
    journey = world.uow.journeys.journeys["j-1"]
    done = tuple(replace(t, status=TaskStatus.COMPLETED, completed_at=journey.created_at) for t in journey.tasks)
    world.uow.journeys.journeys["j-1"] = replace(journey, tasks=done)
    world.skipped(SkipReason.NO_ACTIVE_TASK)


def test_unknown_patient_raises_and_records_nothing(world: World) -> None:
    with pytest.raises(PatientNotFoundError):
        world.service.evaluate("nope")
    assert world.events() == []
