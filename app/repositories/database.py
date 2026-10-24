import sqlite3
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.repositories.orm import Base


def create_db_engine(database_url: str) -> Engine:
    engine = create_engine(database_url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection: sqlite3.Connection, _: Any) -> None:
    # SQLite vem com foreign keys desligadas por padrão; precisa ser ligado por conexão.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Sessões para os services. Cada operação usa `with session.begin():` como unidade de trabalho:
    estado e eventos são gravados juntos, ou nada é gravado."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Cria tabelas, índices e triggers que ainda não existem. Seguro rodar a cada inicialização."""
    Base.metadata.create_all(engine)
