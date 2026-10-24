from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.middleware import request_context
from app.api.routes import health
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.database import create_db_engine, create_session_factory
from app.core.logging import configure_logging
from app.core.security import Hasher
from app.repositories.tables import init_db


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    """Composition root: único lugar onde as dependências concretas são escolhidas.

    Testes passam settings e um relógio falso; em produção tudo vem do ambiente.
    """
    settings = settings or Settings()  # campos obrigatórios vêm do ambiente (.env)
    configure_logging(settings.log_level)

    engine = create_db_engine(settings.database_url)
    init_db(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(
        title="journey-core",
        version="0.1.0",
        description="Núcleo determinístico de jornada de saúde: consentimento, protocolo, eventos e follow-up.",
        lifespan=lifespan,
    )
    app.state.session_factory = create_session_factory(engine)
    app.state.clock = clock or SystemClock()
    app.state.hasher = Hasher(phone_salt=settings.phone_hash_salt, patient_id_salt=settings.event_hash_salt)

    app.middleware("http")(request_context)
    register_exception_handlers(app)
    for module in (health,):
        app.include_router(module.router)
    return app
