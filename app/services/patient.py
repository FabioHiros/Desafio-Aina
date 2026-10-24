"""Regras de negócio do paciente: cadastro, consulta e aceite dos termos."""

from app.core.clock import Clock
from app.core.errors import PatientAlreadyExistsError, PatientNotFoundError
from app.core.ids import new_id
from app.core.security import Hasher
from app.models.events import PatientCreated, TermsAccepted
from app.models.patient import NewPatient, Patient
from app.repositories.interfaces import UnitOfWork
from app.services.event_store import EventStore


class PatientService:
    def __init__(self, uow: UnitOfWork, event_store: EventStore, hasher: Hasher, clock: Clock) -> None:
        self._uow = uow
        self._event_store = event_store
        self._hasher = hasher
        self._clock = clock

    def register(self, data: NewPatient) -> Patient:
        now = self._clock.now()
        patient = Patient(
            patient_id=new_id(),
            phone=data.phone,
            phone_hash=self._hasher.hash_phone(data.phone),
            name=data.name,
            birth_date=data.birth_date,
            sex=data.sex,
            terms_accepted=data.terms_accepted,
            terms_accepted_at=now if data.terms_accepted else None,
            created_at=now,
        )
        with self._uow as uow:
            if uow.patients.exists_by_phone_hash(patient.phone_hash):
                raise PatientAlreadyExistsError
            uow.patients.add(patient)
            self._event_store.append(uow, patient.patient_id, PatientCreated())
            if patient.terms_accepted:
                self._event_store.append(uow, patient.patient_id, TermsAccepted())
            uow.commit()
        return patient

    def get(self, patient_id: str) -> Patient:
        with self._uow as uow:
            return self._get_or_raise(uow, patient_id)

    def accept_terms(self, patient_id: str) -> Patient:
        """Idempotente: aceitar de novo não altera a data nem gera evento duplicado."""
        with self._uow as uow:
            patient = self._get_or_raise(uow, patient_id)
            if patient.terms_accepted:
                return patient
            uow.patients.mark_terms_accepted(patient_id, self._clock.now())
            self._event_store.append(uow, patient_id, TermsAccepted())
            uow.commit()
            return self._get_or_raise(uow, patient_id)

    @staticmethod
    def _get_or_raise(uow: UnitOfWork, patient_id: str) -> Patient:
        patient = uow.patients.get(patient_id)
        if patient is None:
            raise PatientNotFoundError
        return patient
