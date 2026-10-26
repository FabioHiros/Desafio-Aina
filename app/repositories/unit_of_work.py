from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from app.repositories.event import SqlAlchemyEventRepository
from app.repositories.journey import SqlAlchemyJourneyRepository
from app.repositories.patient import SqlAlchemyPatientRepository
from app.repositories.protocol_session import SqlAlchemyProtocolSessionRepository


class SqlAlchemyUnitOfWork:
    """Implementação SQLAlchemy de UnitOfWork (interfaces.py).

    Cada `with` abre uma sessão própria e cria os repositórios sobre ela: é isso que garante que estado e
    eventos de uma operação estão na mesma transação. Não é reentrante: abrir um `with` dentro de outro na
    mesma instância é um erro de programação e falha na hora.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("UnitOfWork já está aberto; não é reentrante")
        self._session = self._session_factory()
        self._patients = SqlAlchemyPatientRepository(self._session)
        self._events = SqlAlchemyEventRepository(self._session)
        self._sessions = SqlAlchemyProtocolSessionRepository(self._session)
        self._journeys = SqlAlchemyJourneyRepository(self._session)
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        try:
            self.rollback()  # não faz nada se commit() já rodou; desfaz tudo caso contrário
        finally:
            self._open_session().close()
            self._session = None

    @property
    def patients(self) -> SqlAlchemyPatientRepository:
        self._open_session()
        return self._patients

    @property
    def events(self) -> SqlAlchemyEventRepository:
        self._open_session()
        return self._events

    @property
    def sessions(self) -> SqlAlchemyProtocolSessionRepository:
        self._open_session()
        return self._sessions

    @property
    def journeys(self) -> SqlAlchemyJourneyRepository:
        self._open_session()
        return self._journeys

    def commit(self) -> None:
        self._open_session().commit()

    def rollback(self) -> None:
        self._open_session().rollback()

    def _open_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("UnitOfWork usado fora de um bloco `with`")
        return self._session
