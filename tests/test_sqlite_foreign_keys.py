"""SQLite foreign-key enforcement via app create_engine helper."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.database.engine import _enable_sqlite_foreign_keys, create_engine
from app.models import Base
from app.models.friend import Friend
from app.models.user import User


@pytest_asyncio.fixture
async def sqlite_engine() -> AsyncEngine:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(sqlite_engine: AsyncEngine) -> AsyncSession:
    factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


async def _pragma_foreign_keys(conn) -> int:
    result = await conn.execute(text("PRAGMA foreign_keys"))
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_foreign_keys_pragma_is_on_for_app_sqlite_engine(
    sqlite_engine: AsyncEngine,
) -> None:
    async with sqlite_engine.connect() as conn:
        assert await _pragma_foreign_keys(conn) == 1


@pytest.mark.asyncio
async def test_foreign_keys_pragma_is_on_for_new_connection(
    sqlite_engine: AsyncEngine,
) -> None:
    async with sqlite_engine.connect() as conn1:
        assert await _pragma_foreign_keys(conn1) == 1

    # Dispose closes the pool, so the next connect creates a new DB-API connection.
    await sqlite_engine.dispose()

    async with sqlite_engine.connect() as conn2:
        assert await _pragma_foreign_keys(conn2) == 1


@pytest.mark.asyncio
async def test_orphan_child_insert_raises_integrity_error(
    session: AsyncSession,
) -> None:
    session.add(Friend(user_id=999_999, name="orphan"))
    with pytest.raises(IntegrityError):
        await session.flush()

    await session.rollback()

    # Session remains usable after rollback.
    user = User(
        telegram_user_id=42,
        telegram_chat_id=42,
        username="alice",
        first_name="Alice",
    )
    session.add(user)
    await session.flush()
    assert user.id is not None

    friend = Friend(user_id=user.id, name="bob")
    session.add(friend)
    await session.flush()
    assert friend.id is not None
    assert friend.user_id == user.id


@pytest.mark.asyncio
async def test_valid_parent_child_insert_succeeds(session: AsyncSession) -> None:
    user = User(
        telegram_user_id=7,
        telegram_chat_id=7,
        username="carol",
        first_name="Carol",
    )
    session.add(user)
    await session.flush()

    friend = Friend(user_id=user.id, name="dave")
    session.add(friend)
    await session.flush()

    assert friend.id is not None
    assert friend.user_id == user.id


def test_sqlite_fk_listener_not_registered_on_postgres_engine() -> None:
    engine = create_engine("postgresql+asyncpg://user:pass@127.0.0.1:1/db")
    try:
        assert engine.dialect.name == "postgresql"
        assert not event.contains(
            engine.sync_engine,
            "connect",
            _enable_sqlite_foreign_keys,
        )
    finally:
        engine.sync_engine.dispose()


def test_sqlite_fk_listener_registered_on_sqlite_engine() -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        assert engine.dialect.name == "sqlite"
        assert event.contains(
            engine.sync_engine,
            "connect",
            _enable_sqlite_foreign_keys,
        )
    finally:
        engine.sync_engine.dispose()
