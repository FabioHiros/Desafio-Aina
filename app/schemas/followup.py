from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.followup import SkipReason


class FollowupEvaluate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: UUID


class FollowupDecisionOut(BaseModel):
    eligible: bool
    template_key: str | None
    reason: SkipReason | None
