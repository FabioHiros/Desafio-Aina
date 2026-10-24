"""Erros da aplicação. Não conhecem HTTP: o mapeamento para status fica em api/errors.py.

Cada erro herda de uma categoria (NotFound, Conflict, PermissionDenied, BusinessRuleViolation), e o
status HTTP é decidido pela categoria. Mensagens são fixas por tipo e nunca incluem dados do paciente.
"""


class AppError(Exception):
    code: str = "internal_error"
    message: str = "Erro interno."

    def __init__(self, message: str | None = None) -> None:
        if message is not None:
            self.message = message
        super().__init__(self.message)


# ─────────────── Categorias ───────────────


class NotFoundError(AppError):
    code = "not_found"
    message = "Recurso não encontrado."


class ConflictError(AppError):
    """A operação conflita com o estado atual (duplicidade, estado encerrado, operação concorrente)."""

    code = "conflict"
    message = "Conflito com o estado atual."


class PermissionDeniedError(AppError):
    """Uma regra do domínio impede a operação (ex.: falta de consentimento)."""

    code = "permission_denied"
    message = "Operação não permitida."


class BusinessRuleViolationError(AppError):
    """Dados bem formados que violam uma regra de negócio (ex.: resposta fora da escala)."""

    code = "business_rule_violation"
    message = "Regra de negócio violada."


# ─────────────── Pacientes ───────────────


class PatientNotFoundError(NotFoundError):
    code = "patient_not_found"
    message = "Paciente não encontrado."


class PatientAlreadyExistsError(ConflictError):
    code = "patient_already_exists"
    message = "Já existe um paciente com este telefone."


class ConsentRequiredError(PermissionDeniedError):
    code = "missing_consent"
    message = "Paciente não aceitou os termos."


# ─────────────── Protocolo ───────────────


class InvalidAnswerError(BusinessRuleViolationError):
    code = "invalid_answer"
    message = "Resposta inválida para a pergunta atual."


class SessionClosedError(ConflictError):
    code = "session_closed"
    message = "A sessão de protocolo já foi concluída."


class ProtocolInProgressError(ConflictError):
    code = "protocol_in_progress"
    message = "Paciente já possui uma sessão de protocolo em andamento."


# ─────────────── Jornada ───────────────


class JourneyAlreadyActiveError(ConflictError):
    code = "journey_already_active"
    message = "Paciente já possui uma jornada em andamento."
