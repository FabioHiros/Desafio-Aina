from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.events import Event, EventName


class EventOut(BaseModel):
    """Envelope como persistido: sem patient_id em claro e sem PII."""

    event_id: str
    occurred_at: datetime
    event_name: EventName
    patient_id_hash: str
    properties: dict[str, Any]

    @classmethod
    def from_domain(cls, event: Event) -> "EventOut":
        return cls(
            event_id=event.event_id,
            occurred_at=event.occurred_at,
            event_name=event.event_name,
            patient_id_hash=event.patient_id_hash,
            properties=event.properties,
        )
