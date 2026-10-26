from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.dependencies import SessionFactoryDep
from app.schemas.common import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut, responses={503: {"model": HealthOut}})
def health(session_factory: SessionFactoryDep) -> HealthOut | JSONResponse:
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content=HealthOut(status="degraded", database="unavailable").model_dump())
    return HealthOut(status="ok", database="ok")
