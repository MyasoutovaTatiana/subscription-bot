"""Database engine factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _enable_sqlite_foreign_keys(dbapi_conn, connection_record) -> None:
    """Turn on SQLite FK enforcement for this DB-API connection."""
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create async SQLAlchemy engine (SQLite or PostgreSQL)."""
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_async_engine(
        database_url,
        echo=echo,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

    # Per-connection setting; register before any checkout (e.g. init_db).
    if engine.dialect.name == "sqlite":
        event.listens_for(engine.sync_engine, "connect")(_enable_sqlite_foreign_keys)

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Provide a transactional session scope for scripts / scheduler jobs."""
    session = session_factory()
    try:
        async with session.begin():
            yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
