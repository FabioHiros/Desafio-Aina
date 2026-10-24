from uuid import UUID

from fastapi import APIRouter, status

from app.api.dependencies import PatientServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.patient import PatientCreate, PatientOut

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PatientOut,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_patient(body: PatientCreate, service: PatientServiceDep) -> PatientOut:
    return PatientOut.from_domain(service.register(body.to_domain()))


@router.get("/{patient_id}", response_model=PatientOut, responses={404: {"model": ErrorResponse}})
def get_patient(patient_id: UUID, service: PatientServiceDep) -> PatientOut:
    return PatientOut.from_domain(service.get(str(patient_id)))


@router.post("/{patient_id}/terms", response_model=PatientOut, responses={404: {"model": ErrorResponse}})
def accept_terms(patient_id: UUID, service: PatientServiceDep) -> PatientOut:
    """Aceite dos termos após o cadastro. Idempotente."""
    return PatientOut.from_domain(service.accept_terms(str(patient_id)))
