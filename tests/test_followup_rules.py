"""Regras de elegibilidade avaliadas sem banco: cada verificação, ordem das regras e o limite das 72h."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.models.followup import Eligible, FollowupFacts, FollowupRules, Skipped, SkipReason
from app.models.journey import Journey, JourneyStatus, Task, TaskStatus

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)

RULES_DATA: dict[str, Any] = {
    "template_key": "checkin_adesao",
    "rules": [
        {"check": "terms_accepted", "reason": "missing_consent"},
        {"check": "protocol_completed", "reason": "no_completed_protocol"},
        {"check": "journey_active", "reason": "no_active_journey"},
        {"check": "has_active_task", "reason": "no_active_task"},
        {"check": "cooldown", "reason": "cooldown", "params": {"hours": 72}},
    ],
}
RULES = FollowupRules.model_validate(RULES_DATA)


def journey(status: JourneyStatus = JourneyStatus.IN_PROGRESS, *task_statuses: TaskStatus) -> Journey:
    statuses = task_statuses or (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED)
    return Journey(
        journey_id="j-1",
        patient_id="p-1",
        session_id="s-1",
        objetivo="x",
        status=status,
        created_at=NOW,
        completed_at=None if status is JourneyStatus.IN_PROGRESS else NOW,
        tasks=tuple(Task(f"t-{i}", i, f"T{i}", s, None) for i, s in enumerate(statuses, start=1)),
    )


ELIGIBLE = FollowupFacts(terms_accepted=True, has_completed_protocol=True, journey=journey(), last_eligible_at=None)


def test_all_rules_pass() -> None:
    assert RULES.evaluate(ELIGIBLE, NOW) == Eligible(template_key="checkin_adesao")


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (replace(ELIGIBLE, terms_accepted=False), SkipReason.MISSING_CONSENT),
        (replace(ELIGIBLE, has_completed_protocol=False, journey=None), SkipReason.NO_COMPLETED_PROTOCOL),
        (replace(ELIGIBLE, journey=None), SkipReason.NO_ACTIVE_JOURNEY),
        (
            replace(ELIGIBLE, journey=journey(JourneyStatus.COMPLETED, TaskStatus.COMPLETED)),
            SkipReason.NO_ACTIVE_JOURNEY,
        ),
        (
            replace(ELIGIBLE, journey=journey(JourneyStatus.IN_PROGRESS, TaskStatus.COMPLETED)),
            SkipReason.NO_ACTIVE_TASK,
        ),
        (replace(ELIGIBLE, last_eligible_at=NOW - timedelta(hours=1)), SkipReason.COOLDOWN),
    ],
    ids=["consent", "protocol", "no-journey", "journey-completed", "no-active-task", "cooldown"],
)
def test_each_rule_has_its_typed_reason(facts: FollowupFacts, reason: SkipReason) -> None:
    assert RULES.evaluate(facts, NOW) == Skipped(reason=reason)


def test_first_failing_rule_defines_the_reason() -> None:
    nothing = FollowupFacts(terms_accepted=False, has_completed_protocol=False, journey=None, last_eligible_at=NOW)
    assert RULES.evaluate(nothing, NOW) == Skipped(SkipReason.MISSING_CONSENT)


@pytest.mark.parametrize(
    ("elapsed", "eligible"),
    [
        (timedelta(0), False),
        (timedelta(hours=71, minutes=59, seconds=59), False),
        (timedelta(hours=72), True),
        (timedelta(hours=73), True),
    ],
)
def test_cooldown_boundary(elapsed: timedelta, eligible: bool) -> None:
    facts = replace(ELIGIBLE, last_eligible_at=NOW - elapsed)
    assert RULES.evaluate(facts, NOW).eligible is eligible


def test_rules_are_configurable_order_and_window() -> None:
    """Mudar a ordem ou a janela é editar o JSON, não o código."""
    custom = FollowupRules.model_validate(
        {
            "template_key": "outro",
            "rules": [
                {"check": "cooldown", "reason": "cooldown", "params": {"hours": 24}},
                {"check": "terms_accepted", "reason": "missing_consent"},
            ],
        }
    )
    facts = replace(ELIGIBLE, terms_accepted=False, last_eligible_at=NOW - timedelta(hours=25))
    assert custom.evaluate(facts, NOW) == Skipped(SkipReason.MISSING_CONSENT)
    assert custom.evaluate(replace(facts, last_eligible_at=NOW), NOW) == Skipped(SkipReason.COOLDOWN)


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ({"check": "unknown_check", "reason": "cooldown"}, "check"),
        ({"check": "terms_accepted", "reason": "made_up_reason"}, "reason"),
        ({"check": "cooldown", "reason": "cooldown"}, "hours"),
        ({"check": "cooldown", "reason": "cooldown", "params": {"hours": 0}}, "positivo"),
        ({"check": "terms_accepted", "reason": "missing_consent", "params": {"hours": 1}}, "vazio"),
        ({"check": "terms_accepted", "reason": "missing_consent", "extra": 1}, "extra"),
    ],
)
def test_invalid_rules_are_rejected(rule: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        FollowupRules.model_validate({"template_key": "x", "rules": [rule]})


@pytest.mark.parametrize(
    "data", [{"template_key": "x", "rules": []}, {"template_key": "Com Espaço", "rules": RULES_DATA["rules"]}]
)
def test_invalid_rule_sets_are_rejected(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FollowupRules.model_validate(data)
