from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.settings import Settings


class Base(DeclarativeBase):
    pass


def create_engine_and_session(settings: Settings):
    engine = create_async_engine(settings.database_url_async, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, session_maker
