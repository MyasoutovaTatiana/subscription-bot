"""Security checks for owner-scoped payment method and friend mutations."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.engine import create_engine
from app.models import Base
from app.models.friend import Friend
from app.models.payment_method import PaymentMethod
from app.repositories.friends import FriendRepository, FriendsUnavailableError
from app.repositories.payment_methods import (
    PaymentMethodRepository,
    PaymentMethodUnavailableError,
)
from app.services.users import UserService


@pytest_asyncio.fixture
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'reference-ownership.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _user(session: AsyncSession, telegram_id: int):
    user, _ = await UserService(session).get_or_create_from_telegram(
        telegram_user_id=telegram_id,
        telegram_chat_id=telegram_id,
        username=f"user{telegram_id}",
        first_name=f"User {telegram_id}",
    )
    return user


@pytest.mark.asyncio
async def test_foreign_payment_method_deactivation_is_rejected(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 101)
    attacker = await _user(session, 202)
    repo = PaymentMethodRepository(session)
    method = await repo.create(user_id=owner.id, name="Owner card")

    with pytest.raises(PaymentMethodUnavailableError):
        await repo.deactivate(method, user_id=attacker.id)

    assert (await repo.get_for_user(method.id, owner.id)).is_active is True


@pytest.mark.asyncio
async def test_forged_payment_method_object_does_not_bypass_database_scope(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 303)
    attacker = await _user(session, 404)
    repo = PaymentMethodRepository(session)
    method = await repo.create(user_id=owner.id, name="Owner card")
    forged = PaymentMethod(
        id=method.id,
        user_id=attacker.id,
        name=method.name,
        is_active=True,
    )

    with pytest.raises(PaymentMethodUnavailableError):
        await repo.deactivate(forged, user_id=attacker.id)

    assert (await repo.get_for_user(method.id, owner.id)).is_active is True


@pytest.mark.asyncio
async def test_owner_can_deactivate_payment_method(session: AsyncSession) -> None:
    owner = await _user(session, 505)
    repo = PaymentMethodRepository(session)
    method = await repo.create(user_id=owner.id, name="Owner card")

    changed = await repo.deactivate(method, user_id=owner.id)

    assert changed.is_active is False


@pytest.mark.asyncio
async def test_foreign_friend_deletion_is_rejected(session: AsyncSession) -> None:
    owner = await _user(session, 606)
    attacker = await _user(session, 707)
    repo = FriendRepository(session)
    friend = await repo.create(user_id=owner.id, name="Owner friend")

    with pytest.raises(FriendsUnavailableError):
        await repo.delete(friend, user_id=attacker.id)

    assert await repo.get_for_user(friend.id, owner.id) is not None


@pytest.mark.asyncio
async def test_forged_friend_object_does_not_bypass_database_scope(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 808)
    attacker = await _user(session, 909)
    repo = FriendRepository(session)
    friend = await repo.create(user_id=owner.id, name="Owner friend")
    forged = Friend(id=friend.id, user_id=attacker.id, name=friend.name)

    with pytest.raises(FriendsUnavailableError):
        await repo.delete(forged, user_id=attacker.id)

    assert await repo.get_for_user(friend.id, owner.id) is not None


@pytest.mark.asyncio
async def test_owner_can_delete_friend(session: AsyncSession) -> None:
    owner = await _user(session, 1001)
    repo = FriendRepository(session)
    friend = await repo.create(user_id=owner.id, name="Owner friend")
    friend_id = friend.id

    await repo.delete(friend, user_id=owner.id)

    assert await repo.get_for_user(friend_id, owner.id) is None
