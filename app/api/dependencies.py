"""Montagem dos objetos por requisição (injeção de dependência via FastAPI).

Único lugar que escolhe as implementações concretas das interfaces de repositories/interfaces.py.
Singletons (fábrica de sessões, relógio, hasher) vivem em app.state, criados em create_app().
Cada requisição recebe sua própria unidade de trabalho; nada de banco é compartilhado entre requisições.
"""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock
from app.core.security import Hasher
from app.repositories.interfaces import UnitOfWork
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.services.event_store import EventService, EventStore
from app.services.patient import PatientService


def get_session_factory(request: Request) -> sessionmaker[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    return session_factory


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_hasher(request: Request) -> Hasher:
    hasher: Hasher = request.app.state.hasher
    return hasher


SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]
ClockDep = Annotated[Clock, Depends(get_clock)]
HasherDep = Annotated[Hasher, Depends(get_hasher)]


def get_uow(session_factory: SessionFactoryDep) -> UnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory)


def get_event_store(hasher: HasherDep, clock: ClockDep) -> EventStore:
    return EventStore(hasher, clock)


UnitOfWorkDep = Annotated[UnitOfWork, Depends(get_uow)]
EventStoreDep = Annotated[EventStore, Depends(get_event_store)]


def get_patient_service(
    uow: UnitOfWorkDep, event_store: EventStoreDep, hasher: HasherDep, clock: ClockDep
) -> PatientService:
    return PatientService(uow, event_store, hasher, clock)


def get_event_service(uow: UnitOfWorkDep, event_store: EventStoreDep) -> EventService:
    return EventService(uow, event_store)


PatientServiceDep = Annotated[PatientService, Depends(get_patient_service)]
EventServiceDep = Annotated[EventService, Depends(get_event_service)]
