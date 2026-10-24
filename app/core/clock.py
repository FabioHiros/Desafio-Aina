from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Fonte única de "agora" (sempre UTC). Nenhum código chama datetime.now() diretamente."""

    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
