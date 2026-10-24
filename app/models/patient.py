"""Modelos de domínio do paciente: dataclasses imutáveis, sem dependência de banco ou HTTP.

Campos com PII usam repr=False para nunca aparecerem em logs ou tracebacks por acidente.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class Sex(StrEnum):
    F = "F"
    M = "M"
    O = "O"  # noqa: E741 - "outro", valor definido no contrato


@dataclass(frozen=True, slots=True)
class Patient:
    patient_id: str
    phone: str = field(repr=False)
    phone_hash: str = field(repr=False)
    name: str = field(repr=False)
    birth_date: date = field(repr=False)
    sex: Sex
    terms_accepted: bool
    terms_accepted_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NewPatient:
    """Dados de entrada do cadastro, já validados e normalizados pela camada de API."""

    phone: str = field(repr=False)
    name: str = field(repr=False)
    birth_date: date = field(repr=False)
    sex: Sex
    terms_accepted: bool
