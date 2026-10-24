"""Elegibilidade de follow-up: regras declarativas (rules/followup.json) avaliadas em ordem.

Cada regra aponta para uma verificação conhecida pelo código (`check`) e diz o motivo tipado de recusa
(`reason`). A primeira regra que falha define o motivo; se todas passam, o paciente é elegível.
A avaliação é pura: recebe um retrato dos fatos (FollowupFacts) e o instante atual, sem acessar banco.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.journey import Journey, JourneyStatus


class Check(StrEnum):
    TERMS_ACCEPTED = "terms_accepted"
    PROTOCOL_COMPLETED = "protocol_completed"
    JOURNEY_ACTIVE = "journey_active"
    HAS_ACTIVE_TASK = "has_active_task"
    COOLDOWN = "cooldown"


class SkipReason(StrEnum):
    MISSING_CONSENT = "missing_consent"
    NO_COMPLETED_PROTOCOL = "no_completed_protocol"
    NO_ACTIVE_JOURNEY = "no_active_journey"
    NO_ACTIVE_TASK = "no_active_task"
    COOLDOWN = "cooldown"


@dataclass(frozen=True, slots=True)
class FollowupFacts:
    """O que as regras precisam saber sobre o paciente, lido numa única transação."""

    terms_accepted: bool
    has_completed_protocol: bool
    journey: Journey | None
    last_eligible_at: datetime | None


@dataclass(frozen=True, slots=True)
class Eligible:
    template_key: str
    eligible: ClassVar[bool] = True


@dataclass(frozen=True, slots=True)
class Skipped:
    reason: SkipReason
    eligible: ClassVar[bool] = False


Decision = Eligible | Skipped


class FollowupRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check: Check
    reason: SkipReason
    description: str = ""
    params: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_params(self) -> Self:
        expected = {"hours"} if self.check is Check.COOLDOWN else set()
        if set(self.params) != expected:
            raise ValueError(f"check '{self.check}' espera params {sorted(expected) or 'vazio'}")
        if self.check is Check.COOLDOWN and self.params["hours"] <= 0:
            raise ValueError("cooldown.hours deve ser positivo")
        return self

    def passes(self, facts: FollowupFacts, now: datetime) -> bool:
        return _CHECKS[self.check](facts, self, now)


class FollowupRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    template_key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    rules: tuple[FollowupRule, ...] = Field(min_length=1)

    def evaluate(self, facts: FollowupFacts, now: datetime) -> Decision:
        for rule in self.rules:
            if not rule.passes(facts, now):
                return Skipped(reason=rule.reason)
        return Eligible(template_key=self.template_key)


def _journey_active(facts: FollowupFacts) -> bool:
    return facts.journey is not None and facts.journey.status is JourneyStatus.IN_PROGRESS


def _cooldown(facts: FollowupFacts, rule: FollowupRule, now: datetime) -> bool:
    """Passa se não houve follow-up elegível nas últimas `hours` horas."""
    if facts.last_eligible_at is None:
        return True
    return now - facts.last_eligible_at >= timedelta(hours=rule.params["hours"])


_CHECKS: dict[Check, Callable[[FollowupFacts, FollowupRule, datetime], bool]] = {
    Check.TERMS_ACCEPTED: lambda facts, _rule, _now: facts.terms_accepted,
    Check.PROTOCOL_COMPLETED: lambda facts, _rule, _now: facts.has_completed_protocol,
    Check.JOURNEY_ACTIVE: lambda facts, _rule, _now: _journey_active(facts),
    Check.HAS_ACTIVE_TASK: lambda facts, _rule, _now: facts.journey is not None and facts.journey.has_active_task,
    Check.COOLDOWN: _cooldown,
}
