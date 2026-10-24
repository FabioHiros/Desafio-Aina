"""Avaliação de elegibilidade de follow-up. Não envia mensagem: só decide e registra o evento.

Leitura dos fatos, decisão e evento acontecem na mesma transação. Com BEGIN IMMEDIATE (core/database.py),
avaliações simultâneas do mesmo paciente são serializadas: o cooldown não deixa passar dois follow-ups.
"""

from app.core.clock import Clock
from app.core.errors import PatientNotFoundError
from app.models.events import EventName, FollowupEligible, FollowupSkipped
from app.models.followup import Decision, Eligible, FollowupFacts, FollowupRules, Skipped
from app.repositories.interfaces import UnitOfWork
from app.services.event_store import EventStore


class FollowupService:
    def __init__(self, uow: UnitOfWork, event_store: EventStore, rules: FollowupRules, clock: Clock) -> None:
        self._uow = uow
        self._event_store = event_store
        self._rules = rules
        self._clock = clock

    def evaluate(self, patient_id: str) -> Decision:
        with self._uow as uow:
            patient = uow.patients.get(patient_id)
            if patient is None:
                raise PatientNotFoundError

            facts = FollowupFacts(
                terms_accepted=patient.terms_accepted,
                has_completed_protocol=uow.sessions.has_completed(patient_id),
                journey=uow.journeys.get_current_for_patient(patient_id),
                last_eligible_at=self._event_store.last_occurrence(uow, patient_id, EventName.FOLLOWUP_ELIGIBLE),
            )
            decision = self._rules.evaluate(facts, self._clock.now())

            match decision:
                case Eligible(template_key=template_key):
                    self._event_store.append(uow, patient_id, FollowupEligible(template_key=template_key))
                case Skipped(reason=reason):
                    self._event_store.append(uow, patient_id, FollowupSkipped(reason=reason))
            uow.commit()
            return decision
