"""Infraestrutura de banco: engine, sessões e a base comum das tabelas ORM."""

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, DateTime, Dialect, Engine, MetaData, TypeDecorator, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

SQLITE_BUSY_TIMEOUT_SECONDS = 5


def create_db_engine(database_url: str) -> Engine:
    # hide_parameters: mensagens de erro do SQLAlchemy incluiriam os valores do INSERT (ex.: o telefone).
    if not database_url.startswith("sqlite"):
        return create_engine(database_url, hide_parameters=True)

    # Escritas concorrentes esperam o lock (até o timeout) em vez de falhar com "database is locked".
    engine = create_engine(database_url, hide_parameters=True, connect_args={"timeout": SQLITE_BUSY_TIMEOUT_SECONDS})
    event.listen(engine, "connect", _configure_sqlite_connection)
    event.listen(engine, "begin", _begin_immediate)
    return engine


def _configure_sqlite_connection(dbapi_connection: sqlite3.Connection, _: Any) -> None:
    # O driver sqlite3 emite BEGIN por conta própria (deferred); desligamos para controlar o BEGIN abaixo.
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    # SQLite vem com foreign keys desligadas por padrão; precisa ser ligado por conexão.
    cursor.execute("PRAGMA foreign_keys = ON")
    # WAL: leitores não bloqueiam o escritor e vice-versa.
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.close()


def _begin_immediate(connection: Connection) -> None:
    """Toda transação pega o lock de escrita já no início.

    Sem isso, duas transações podem ler ao mesmo tempo ("não existe follow-up nas últimas 72h") e as duas
    escreverem depois. Com BEGIN IMMEDIATE, verificação e escrita rodam serializadas. O equivalente em
    Postgres seria travar a linha do paciente (SELECT ... FOR UPDATE) no início de cada operação.
    """
    connection.exec_driver_sql("BEGIN IMMEDIATE")


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Fábrica usada pelo UnitOfWork: cada unidade de trabalho abre e fecha a própria sessão."""
    return sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    # Nomes de constraints determinísticos: aparecem nas mensagens de erro e facilitam migrations futuras.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class UTCDateTime(TypeDecorator[datetime]):
    """Grava sempre em UTC e devolve datetime com timezone.

    O SQLite não guarda fuso; sem isso, datas voltariam "naive" e a comparação do cooldown ficaria ambígua.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime sem timezone; use o relógio da aplicação (UTC)")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


def sql_in(column: str, values: Iterable[str]) -> str:
    """Expressão para CHECK (coluna IN (...)), normalmente a partir dos valores de um enum."""
    quoted = ", ".join(f"'{value}'" for value in map(str, values))  # str(): StrEnum vira o próprio valor
    return f"{column} IN ({quoted})"
