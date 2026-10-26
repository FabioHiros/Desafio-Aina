from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.journey import JourneyStatus, TaskStatus


class TaskOut(BaseModel):
    id: str
    titulo: str
    status: TaskStatus
    completed_at: datetime | None


class JourneyOut(BaseModel):
    journey_id: str
    session_id: str
    objetivo: str
    status: JourneyStatus
    created_at: datetime
    completed_at: datetime | None
    tarefas: list[TaskOut]


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["concluida"] = Field(examples=["concluida"])
