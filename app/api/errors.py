"""Única camada que traduz erros em respostas HTTP. Todo erro sai no mesmo formato:

    {"error": {"code": "...", "message": "...", "details": [...]}}

O mapeamento é por categoria (core/errors.py): um erro novo só precisa herdar da categoria certa.
Nenhum handler devolve ou loga o valor enviado pelo cliente (pode ser telefone, nome ou data de nascimento).
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import (
    AppError,
    BusinessRuleViolationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)

logger = logging.getLogger(__name__)

STATUS_BY_CATEGORY: tuple[tuple[type[AppError], int], ...] = (
    (NotFoundError, 404),
    (PermissionDeniedError, 403),
    (ConflictError, 409),
    (BusinessRuleViolationError, 422),
)


def error_body(code: str, message: str, details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def status_for(exc: AppError) -> int:
    for category, status in STATUS_BY_CATEGORY:
        if isinstance(exc, category):
            return status
    return 500


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    status = status_for(exc)
    if status >= 500:
        logger.error("domain error without category: %s", type(exc).__name__)
    return JSONResponse(status_code=status, content=error_body(exc.code, exc.message))


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """O handler padrão do FastAPI ecoa o `input` recebido; aqui só saem local, tipo e mensagem."""
    details = [
        {"loc": list(err.get("loc", ())), "type": err.get("type"), "msg": err.get("msg")} for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content=error_body("validation_error", "Requisição inválida.", details))


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    """404 de rota inexistente, 405 etc. no mesmo formato dos demais erros."""
    phrase = HTTPStatus(exc.status_code).phrase
    code = phrase.lower().replace(" ", "_")
    return JSONResponse(status_code=exc.status_code, content=error_body(code, phrase), headers=exc.headers)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Loga tipo e rota, nunca o corpo da requisição. Erros do banco não carregam parâmetros (hide_parameters).
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content=error_body("internal_error", "Erro interno."))


def register_exception_handlers(app: FastAPI) -> None:
    # A tipagem do Starlette exige handlers de Exception genérica, mas em runtime cada handler
    # só recebe o tipo para o qual foi registrado.
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)
