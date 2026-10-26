from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.errors import (
    AnswerAlreadyRecordedError,
    ConsentRequiredError,
    InvalidAnswerError,
    JourneyAlreadyActiveError,
    PatientNotFoundError,
    ProtocolInProgressError,
    ProtocolSessionNotFoundError,
    SessionClosedError,
    TemplateNotFoundError,
    UnexpectedQuestionError,
)
from app.core.security import Hasher
from app.models.events import EventName
from app.models.patient import Patient, Sex
from app.models.protocol import ProtocolTemplate, SessionStatus
from app.repositories.templates import FileTemplateCatalog
from app.services.event_store import EventStore
from app.services.protocol import ProtocolService, SessionState
from tests.fakes import FakeClock, InMemoryTemplateCatalog, InMemoryUnitOfWork


def load_phq9() -> ProtocolTemplate:
    template = FileTemplateCatalog.load(Path(__file__).resolve().parent.parent / "templates").get("phq9")
    assert template is not None
    return template


PHQ9 = load_phq9()
DEMO = ProtocolTemplate.model_validate(
    {
        "template_id": "demo",
        "name": "Demo",
        "scale": [{"value": 0, "label": "Não"}, {"value": 1, "label": "Sim"}],
        "questions": [{"id": "a", "text": "A?"}, {"id": "b", "text": "B?"}, {"id": "c", "text": "C?"}],
        "rules": [{"after": "a", "when": {"sum": ["a"], "op": "eq", "value": 1}, "action": "end_block"}],
    }
)
PATIENT = Patient(
    patient_id="p-1",
    phone="5511987654321",
    phone_hash="hash",
    name="Maria Teste",
    birth_date=date(1990, 5, 10),
    sex=Sex.F,
    terms_accepted=True,
    terms_accepted_at=None,
    created_at=FakeClock().now(),
)


@dataclass
class World:
    service: ProtocolService
    uow: InMemoryUnitOfWork
    clock: FakeClock

    def events(self) -> list[EventName]:
        return [e.event_name for e in self.uow.events.events]

    def answer_all(self, session_id: str, *values: int) -> SessionState:
        state = self.service.get(session_id)
        for value in values:
            assert state.next_question is not None
            state = self.service.answer(session_id, state.next_question.question.id, value)
        return state


@pytest.fixture
def world() -> World:
    uow, clock = InMemoryUnitOfWork(), FakeClock()
    uow.patients.patients[PATIENT.patient_id] = replace(PATIENT, terms_accepted_at=clock.now())
    hasher = Hasher(phone_salt=SecretStr("phone-salt-0000000"), patient_id_salt=SecretStr("event-salt-0000000"))
    service = ProtocolService(uow, EventStore(hasher, clock), InMemoryTemplateCatalog(PHQ9, DEMO), clock)
    return World(service, uow, clock)


def start(world: World, template_id: str = "phq9") -> SessionState:
    return world.service.start("p-1", template_id, "Perder 5kg em 3 meses")


def test_start_returns_first_question_and_emits_event(world: World) -> None:
    state = start(world)

    assert state.session.status is SessionStatus.IN_PROGRESS
    assert state.next_question is not None
    assert (state.next_question.question.id, state.next_question.position) == ("q1", 1)
    assert world.events() == [EventName.PROTOCOL_STARTED]
    assert world.uow.events.events[0].properties == {"session_id": state.session.session_id, "template_id": "phq9"}


def test_start_requires_consent(world: World) -> None:
    world.uow.patients.patients["p-1"] = replace(PATIENT, terms_accepted=False)

    with pytest.raises(ConsentRequiredError):
        start(world)
    assert world.uow.sessions.sessions == {}
    assert world.events() == []


def test_start_unknown_patient_or_template(world: World) -> None:
    with pytest.raises(PatientNotFoundError):
        world.service.start("nope", "phq9", "x")
    with pytest.raises(TemplateNotFoundError):
        start(world, "unknown")


def test_only_one_session_in_progress(world: World) -> None:
    start(world)
    with pytest.raises(ProtocolInProgressError):
        start(world)


def test_phq2_skip_completes_with_partial_score(world: World) -> None:
    session_id = start(world).session.session_id

    state = world.answer_all(session_id, 1, 1)

    assert state.next_question is None
    assert state.session.status is SessionStatus.COMPLETED
    assert (state.session.score, state.session.ended_by_skip) == (2, True)
    assert state.session.completed_at == world.clock.now()
    assert world.events() == [EventName.PROTOCOL_STARTED, EventName.PROTOCOL_COMPLETED, EventName.JOURNEY_CREATED]
    completed = world.uow.events.events[1].properties
    assert completed == {"session_id": session_id, "template_id": "phq9", "score": 2, "ended_by_skip": True}


def test_no_skip_goes_through_all_nine_questions(world: World) -> None:
    session_id = start(world).session.session_id

    state = world.answer_all(session_id, 2, 1)
    assert state.next_question is not None
    assert state.next_question.question.id == "q3"

    state = world.answer_all(session_id, 3, 0, 1, 2, 3, 1, 0)
    assert state.session.status is SessionStatus.COMPLETED
    assert (state.session.score, state.session.ended_by_skip) == (13, False)
    assert len(state.session.answers) == 9


def test_engine_is_generic_for_another_template(world: World) -> None:
    session_id = start(world, "demo").session.session_id

    state = world.answer_all(session_id, 1)

    assert (state.session.score, state.session.ended_by_skip) == (1, True)


def test_identical_resend_returns_same_state_without_recording(world: World) -> None:
    session_id = start(world).session.session_id
    first = world.service.answer(session_id, "q1", 2)
    events_before = world.events()

    again = world.service.answer(session_id, "q1", 2)

    assert again.next_question == first.next_question
    assert len(again.session.answers) == 1
    assert world.events() == events_before


def test_resend_of_final_answer_returns_final_result(world: World) -> None:
    session_id = start(world).session.session_id
    world.answer_all(session_id, 1, 1)

    again = world.service.answer(session_id, "q2", 1)

    assert again.session.status is SessionStatus.COMPLETED
    assert world.events().count(EventName.PROTOCOL_COMPLETED) == 1


def test_changing_a_recorded_answer_is_rejected(world: World) -> None:
    session_id = start(world).session.session_id
    world.service.answer(session_id, "q1", 2)

    with pytest.raises(AnswerAlreadyRecordedError):
        world.service.answer(session_id, "q1", 3)


def test_out_of_order_answer_names_the_expected_question(world: World) -> None:
    session_id = start(world).session.session_id
    world.service.answer(session_id, "q1", 2)

    with pytest.raises(UnexpectedQuestionError, match="Esperada: q2") as error:
        world.service.answer(session_id, "q5", 1)
    assert error.value.expected_question_id == "q2"


@pytest.mark.parametrize("value", [-1, 4, 99])
def test_value_outside_scale_is_rejected(world: World, value: int) -> None:
    session_id = start(world).session.session_id
    with pytest.raises(InvalidAnswerError):
        world.service.answer(session_id, "q1", value)
    assert world.service.get(session_id).session.answers == ()


def test_new_answer_after_completion_is_rejected(world: World) -> None:
    session_id = start(world).session.session_id
    world.answer_all(session_id, 0, 0)

    with pytest.raises(SessionClosedError):
        world.service.answer(session_id, "q3", 1)


def test_unknown_session(world: World) -> None:
    with pytest.raises(ProtocolSessionNotFoundError):
        world.service.answer("nope", "q1", 1)
    with pytest.raises(ProtocolSessionNotFoundError):
        world.service.get("nope")


def test_objective_never_reaches_events(world: World) -> None:
    session_id = start(world).session.session_id
    world.answer_all(session_id, 1, 1)

    assert "Perder 5kg" not in repr([e.properties for e in world.uow.events.events])


def test_no_journey_while_the_protocol_is_in_progress(world: World) -> None:
    session_id = start(world).session.session_id
    state = world.answer_all(session_id, 2, 1)

    assert state.journey is None
    assert world.uow.journeys.journeys == {}
    assert EventName.JOURNEY_CREATED not in world.events()


@pytest.mark.parametrize("values", [(1, 1), (3, 3, 3, 3, 3, 3, 3, 3, 3)], ids=["skip", "full"])
def test_journey_is_created_when_the_protocol_completes(world: World, values: tuple[int, ...]) -> None:
    session_id = start(world).session.session_id

    state = world.answer_all(session_id, *values)

    journey = state.journey
    assert journey is not None
    assert journey.session_id == session_id
    assert journey.objetivo == "Perder 5kg em 3 meses"
    assert journey.created_at == world.clock.now()
    assert [t.titulo for t in journey.tasks] == ["Tarefa A", "Tarefa B"]
    assert [t.position for t in journey.tasks] == [1, 2]
    assert world.events()[-2:] == [EventName.PROTOCOL_COMPLETED, EventName.JOURNEY_CREATED]
    created = world.uow.events.events[-1].properties
    assert created == {"journey_id": journey.journey_id, "session_id": session_id, "task_count": 2}


def test_resend_of_final_answer_returns_the_same_journey(world: World) -> None:
    session_id = start(world).session.session_id
    first = world.answer_all(session_id, 1, 1)

    again = world.service.answer(session_id, "q2", 1)

    assert again.journey == first.journey
    assert len(world.uow.journeys.journeys) == 1


def test_journey_failure_rolls_back_the_completion(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = start(world).session.session_id
    world.service.answer(session_id, "q1", 1)

    def fail(*args: object) -> None:
        raise RuntimeError("falha ao gravar a jornada")

    monkeypatch.setattr(world.uow.journeys, "add", fail)
    with pytest.raises(RuntimeError):
        world.service.answer(session_id, "q2", 1)

    session = world.service.get(session_id).session
    assert session.status is SessionStatus.IN_PROGRESS
    assert session.answer_values == {"q1": 1}
    assert world.events() == [EventName.PROTOCOL_STARTED]


def test_new_protocol_is_blocked_while_the_journey_is_active(world: World) -> None:
    world.answer_all(start(world).session.session_id, 1, 1)

    with pytest.raises(JourneyAlreadyActiveError):
        start(world)
