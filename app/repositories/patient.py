from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import PatientAlreadyExistsError
from app.models.patient import Patient, Sex
from app.repositories.tables import PatientRow


class SqlAlchemyPatientRepository:
    """Implementação SQLAlchemy de PatientRepository (interfaces.py)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, patient: Patient) -> None:
        self._session.add(
            PatientRow(
                patient_id=patient.patient_id,
                phone=patient.phone,
                phone_hash=patient.phone_hash,
                name=patient.name,
                birth_date=patient.birth_date,
                sex=patient.sex.value,
                terms_accepted=patient.terms_accepted,
                terms_accepted_at=patient.terms_accepted_at,
                created_at=patient.created_at,
            )
        )
        try:
            self._session.flush()
        except IntegrityError as exc:
            # Corrida entre dois cadastros do mesmo telefone: o UNIQUE do banco decide.
            if "phone_hash" in str(exc.orig):
                raise PatientAlreadyExistsError from None
            raise

    def get(self, patient_id: str) -> Patient | None:
        row = self._session.get(PatientRow, patient_id)
        return _to_domain(row) if row is not None else None

    def exists_by_phone_hash(self, phone_hash: str) -> bool:
        return bool(self._session.scalar(select(exists().where(PatientRow.phone_hash == phone_hash))))

    def mark_terms_accepted(self, patient_id: str, accepted_at: datetime) -> None:
        row = self._session.get_one(PatientRow, patient_id)
        row.terms_accepted = True
        row.terms_accepted_at = accepted_at
        self._session.flush()


def _to_domain(row: PatientRow) -> Patient:
    return Patient(
        patient_id=row.patient_id,
        phone=row.phone,
        phone_hash=row.phone_hash,
        name=row.name,
        birth_date=row.birth_date,
        sex=Sex(row.sex),
        terms_accepted=row.terms_accepted,
        terms_accepted_at=row.terms_accepted_at,
        created_at=row.created_at,
    )
