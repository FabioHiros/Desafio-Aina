from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class JourneyStatus(StrEnum):
    IN_PROGRESS = "em_andamento"
    COMPLETED = "concluida"


class TaskStatus(StrEnum):
    IN_PROGRESS = "em_andamento"
    COMPLETED = "concluida"


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    position: int
    titulo: str
    status: TaskStatus
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class Journey:
    journey_id: str
    patient_id: str
    session_id: str
    objetivo: str = field(repr=False)
    status: JourneyStatus
    created_at: datetime
    completed_at: datetime | None
    tasks: tuple[Task, ...]

    def task(self, task_id: str) -> Task | None:
        return next((task for task in self.tasks if task.task_id == task_id), None)

    @property
    def has_active_task(self) -> bool:
        return any(task.status is TaskStatus.IN_PROGRESS for task in self.tasks)
