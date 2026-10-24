from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    """Formato único de todo erro: {"error": {"code", "message", "details"?}}."""

    error: ErrorDetail


class HealthOut(BaseModel):
    status: str
    database: str
