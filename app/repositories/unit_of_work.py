from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from app.repositories.event import SqlAlchemyEventRepository
from app.repositories.patient import SqlAlchemyPatientRepository


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
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        try:
            self.rollback()  # não faz nada se commit() já rodou; desfaz tudo caso contrário
        finally:
            self._active_session.close()
            self._session = None

    @property
    def patients(self) -> SqlAlchemyPatientRepository:
        self._active_session  # noqa: B018 - falha se usado fora do `with`
        return self._patients

    @property
    def events(self) -> SqlAlchemyEventRepository:
        self._active_session  # noqa: B018 - falha se usado fora do `with`
        return self._events

    def commit(self) -> None:
        self._active_session.commit()

    def rollback(self) -> None:
        self._active_session.rollback()

    @property
    def _active_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("UnitOfWork usado fora de um bloco `with`")
        return self._session
