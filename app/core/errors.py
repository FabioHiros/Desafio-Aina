class AppError(Exception):
    code: str = "internal_error"
    message: str = "Erro interno."

    def __init__(self, message: str | None = None) -> None:
        if message is not None:
            self.message = message
        super().__init__(self.message)


class NotFoundError(AppError):
    code = "not_found"
    message = "Recurso não encontrado."


class ConflictError(AppError):
    code = "conflict"
    message = "Conflito com o estado atual."


class PermissionDeniedError(AppError):
    code = "permission_denied"
    message = "Operação não permitida."


class BusinessRuleViolationError(AppError):
    code = "business_rule_violation"
    message = "Regra de negócio violada."


class PatientNotFoundError(NotFoundError):
    code = "patient_not_found"
    message = "Paciente não encontrado."


class PatientAlreadyExistsError(ConflictError):
    code = "patient_already_exists"
    message = "Já existe um paciente com este telefone."


class ConsentRequiredError(PermissionDeniedError):
    code = "missing_consent"
    message = "Paciente não aceitou os termos."


class TemplateNotFoundError(NotFoundError):
    code = "template_not_found"
    message = "Template de protocolo não encontrado."


class ProtocolSessionNotFoundError(NotFoundError):
    code = "protocol_session_not_found"
    message = "Sessão de protocolo não encontrada."


class InvalidAnswerError(BusinessRuleViolationError):
    code = "invalid_answer"
    message = "Valor fora da escala do protocolo."


class UnexpectedQuestionError(ConflictError):
    code = "unexpected_question"
    message = "A pergunta respondida não é a pergunta atual."

    def __init__(self, expected_question_id: str) -> None:
        super().__init__(f"A pergunta respondida não é a pergunta atual. Esperada: {expected_question_id}.")
        self.expected_question_id = expected_question_id


class AnswerAlreadyRecordedError(ConflictError):
    code = "answer_already_recorded"
    message = "Esta pergunta já foi respondida com outro valor."


class SessionClosedError(ConflictError):
    code = "session_closed"
    message = "A sessão de protocolo já foi concluída."


class ProtocolInProgressError(ConflictError):
    code = "protocol_in_progress"
    message = "Paciente já possui uma sessão de protocolo em andamento."


class JourneyNotFoundError(NotFoundError):
    code = "journey_not_found"
    message = "Jornada não encontrada."


class TaskNotFoundError(NotFoundError):
    code = "task_not_found"
    message = "Tarefa não encontrada nesta jornada."


class JourneyAlreadyActiveError(ConflictError):
    code = "journey_already_active"
    message = "Paciente já possui uma jornada em andamento."
