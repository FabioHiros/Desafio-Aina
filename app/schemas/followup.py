from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.followup import SkipReason


class FollowupEvaluate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: UUID


class FollowupDecisionOut(BaseModel):
    """Elegível: `template_key` do follow-up a disparar. Não elegível: `reason` tipado. Nada é enviado."""

    eligible: bool
    template_key: str | None
    reason: SkipReason | None
