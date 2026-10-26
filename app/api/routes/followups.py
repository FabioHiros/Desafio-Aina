from fastapi import APIRouter

from app.api.dependencies import FollowupServiceDep
from app.models.followup import Decision, Eligible, Skipped
from app.schemas.common import ErrorResponse
from app.schemas.followup import FollowupDecisionOut, FollowupEvaluate

router = APIRouter(tags=["followups"])


@router.post(
    "/followups/evaluate",
    response_model=FollowupDecisionOut,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def evaluate(body: FollowupEvaluate, service: FollowupServiceDep) -> FollowupDecisionOut:
    """Aplica as regras de rules/followup.json e registra followup_eligible ou followup_skipped.

    Não envia mensagem: só devolve a decisão. "Não elegível" é uma resposta 200, não um erro.
    """
    return to_out(service.evaluate(str(body.patient_id)))


def to_out(decision: Decision) -> FollowupDecisionOut:
    match decision:
        case Eligible(template_key=template_key):
            return FollowupDecisionOut(eligible=True, template_key=template_key, reason=None)
        case Skipped(reason=reason):
            return FollowupDecisionOut(eligible=False, template_key=None, reason=reason)
