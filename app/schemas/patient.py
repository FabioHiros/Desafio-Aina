"""Contratos HTTP do paciente. O que não está aqui não sai na resposta."""

import re
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.patient import NewPatient, Patient, Sex

_NON_DIGITS = re.compile(r"\D")


class PatientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(description="Telefone com DDI e DDD; formatação é ignorada.", examples=["+55 11 99999-8888"])
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    birth_date: date
    sex: Sex
    terms_accepted: bool

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        # Normalizar antes do hash: "+55 (11) 99999-8888" e "5511999998888" são o mesmo paciente.
        digits = _NON_DIGITS.sub("", value)
        if not 10 <= len(digits) <= 15:  # faixa do E.164
            raise ValueError("telefone deve ter entre 10 e 15 dígitos")
        return digits

    @field_validator("birth_date")
    @classmethod
    def birth_date_in_range(cls, value: date) -> date:
        if not date(1900, 1, 1) <= value <= date.today():
            raise ValueError("data de nascimento fora do intervalo permitido")
        return value

    def to_domain(self) -> NewPatient:
        return NewPatient(
            phone=self.phone,
            name=self.name,
            birth_date=self.birth_date,
            sex=self.sex,
            terms_accepted=self.terms_accepted,
        )


class PatientOut(BaseModel):
    """Sem telefone, nome ou data de nascimento: minimização de dados na resposta."""

    patient_id: str
    sex: Sex
    terms_accepted: bool
    terms_accepted_at: datetime | None
    created_at: datetime

    @classmethod
    def from_domain(cls, patient: Patient) -> "PatientOut":
        return cls(
            patient_id=patient.patient_id,
            sex=patient.sex,
            terms_accepted=patient.terms_accepted,
            terms_accepted_at=patient.terms_accepted_at,
            created_at=patient.created_at,
        )
