from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models.events import Event, EventName
from app.repositories.tables import EventRow


class SqlAlchemyEventRepository:
    """Implementação SQLAlchemy de EventRepository (interfaces.py). O banco também recusa update/delete."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        event_id: str,
        occurred_at: datetime,
        event_name: EventName,
        patient_id_hash: str,
        properties: dict[str, Any],
    ) -> Event:
        row = EventRow(
            event_id=event_id,
            occurred_at=occurred_at,
            event_name=event_name.value,
            patient_id_hash=patient_id_hash,
            properties=properties,
        )
        self._session.add(row)
        self._session.flush()  # atribui a position
        return _to_domain(row)

    def list_by_patient_hash(self, patient_id_hash: str) -> list[Event]:
        rows = self._session.scalars(
            select(EventRow).where(EventRow.patient_id_hash == patient_id_hash).order_by(EventRow.position)
        )
        return [_to_domain(row) for row in rows]

    def exists_since(self, patient_id_hash: str, event_name: EventName, since: datetime) -> bool:
        query = select(
            exists().where(
                EventRow.patient_id_hash == patient_id_hash,
                EventRow.event_name == event_name.value,
                EventRow.occurred_at > since,
            )
        )
        return bool(self._session.scalar(query))

    def latest_occurred_at(self, patient_id_hash: str, event_name: EventName) -> datetime | None:
        query = select(func.max(EventRow.occurred_at)).where(
            EventRow.patient_id_hash == patient_id_hash, EventRow.event_name == event_name.value
        )
        latest: datetime | None = self._session.scalar(query)
        return latest.replace(tzinfo=UTC) if latest is not None else None


def _to_domain(row: EventRow) -> Event:
    return Event(
        event_id=row.event_id,
        position=row.position,
        occurred_at=row.occurred_at,
        event_name=EventName(row.event_name),
        patient_id_hash=row.patient_id_hash,
        properties=dict(row.properties),
    )
