"""Infraestrutura de banco: engine, sessões e a base comum das tabelas ORM."""

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Dialect, Engine, MetaData, TypeDecorator, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def create_db_engine(database_url: str) -> Engine:
    # hide_parameters: mensagens de erro do SQLAlchemy incluiriam os valores do INSERT (ex.: o telefone).
    engine = create_engine(database_url, hide_parameters=True)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection: sqlite3.Connection, _: Any) -> None:
    # SQLite vem com foreign keys desligadas por padrão; precisa ser ligado por conexão.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


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
