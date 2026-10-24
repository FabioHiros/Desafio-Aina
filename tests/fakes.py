"""Implementações de teste das interfaces da aplicação (Clock e repositories/interfaces.py)."""

from datetime import UTC, datetime, timedelta


class FakeClock:
    """Relógio controlado pelo teste: o tempo só anda quando o teste manda."""

    def __init__(self, start: datetime = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)
