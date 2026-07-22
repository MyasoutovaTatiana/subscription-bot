"""Regression coverage for subscription friend selection and editing (#20)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.handlers.subscriptions import (
    add_friends_step,
    cb_edit_field,
    edit_friends_toggle,
)
from app.keyboards.subscriptions import edit_fields_keyboard, friends_step_keyboard
from app.models import Base
from app.models.enums import BillingType, CurrencyCode, SubscriptionCategory
from app.models.friend import Friend
from app.models.subscription import SubscriptionParticipant
from app.models.user import User
from app.repositories.friends import FRIENDS_UNAVAILABLE_MESSAGE, FriendRepository
from app.services.subscription_cards import format_subscription_card
from app.services.subscriptions import CreateSubscriptionDTO, SubscriptionService
from app.services.users import UserService
from app.states.subscriptions import EditSubscriptionSG
from app.utils.callback_data import MenuCb, SubCb


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _user(session: AsyncSession, telegram_user_id: int) -> User:
    user, _ = await UserService(session).get_or_create_from_telegram(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_user_id,
        username=f"user{telegram_user_id}",
        first_name=f"User {telegram_user_id}",
    )
    return user


async def _friend(session: AsyncSession, user_id: int, name: str) -> Friend:
    return await FriendRepository(session).create(user_id=user_id, name=name)


def _dto(user_id: int, friend_ids: list[int]) -> CreateSubscriptionDTO:
    return CreateSubscriptionDTO(
        user_id=user_id,
        name="Figma",
        category=SubscriptionCategory.AI_WORK.value,
        amount=Decimal("22"),
        currency=CurrencyCode.USD.value,
        billing_type=BillingType.MONTHLY.value,
        billing_interval=None,
        billing_day=2,
        next_charge_date=date(2026, 8, 2),
        payment_method_id=None,
        reminder_offsets=[1, 0],
        reminder_time="10:00",
        notes="Командная подписка",
        friend_ids=friend_ids,
    )


def _callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.message.edit_reply_markup = AsyncMock()
    return callback


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_creation_and_edit_keyboards_expose_friends_without_later() -> None:
    create_labels = _button_texts(friends_step_keyboard())
    edit_labels = _button_texts(edit_fields_keyboard(42))

    assert create_labels == ["Без друзей", "С друзьями"]
    assert "Позже" not in create_labels
    assert "Друзья" in edit_labels


@pytest.mark.asyncio
async def test_with_friends_opens_owned_friend_picker(session: AsyncSession) -> None:
    owner = await _user(session, 1)
    await _friend(session, owner.id, "Катя")
    state = AsyncMock()
    callback = _callback()

    await add_friends_step(
        callback,
        MenuCb(action="fr", value="with"),
        state,
        session,
        owner,
    )

    state.update_data.assert_awaited_once_with(friend_ids=[])
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    labels = _button_texts(markup)
    assert "Катя" in labels
    assert "➕ Новый друг" in labels
    assert "Готово" in labels


@pytest.mark.asyncio
async def test_edit_picker_marks_existing_friends(session: AsyncSession) -> None:
    owner = await _user(session, 1)
    friend = await _friend(session, owner.id, "Катя")
    sub = await SubscriptionService(session).create(_dto(owner.id, [friend.id]))
    state = AsyncMock()
    callback = _callback()

    await cb_edit_field(
        callback,
        SubCb(action="ef_friends", sid=sub.id),
        state,
        session,
        owner,
    )

    state.set_state.assert_awaited_once_with(EditSubscriptionSG.friends)
    state.update_data.assert_awaited_once_with(
        edit_sid=sub.id,
        edit_friend_ids=[friend.id],
    )
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    assert "✅ Катя" in _button_texts(markup)


@pytest.mark.asyncio
async def test_update_friends_adds_removes_and_deduplicates_without_other_changes(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    katya = await _friend(session, owner.id, "Катя")
    misha = await _friend(session, owner.id, "Миша")
    service = SubscriptionService(session)
    sub = await service.create(_dto(owner.id, []))
    original = (
        sub.name,
        sub.amount,
        sub.currency,
        sub.next_charge_date,
        sub.notes,
    )

    sub = await service.update_friends(
        sub,
        user_id=owner.id,
        friend_ids=[katya.id, misha.id, katya.id],
    )
    assert {participant.friend_id for participant in sub.participants} == {katya.id, misha.id}
    assert len(sub.participants) == 2
    assert "Катя" in format_subscription_card(sub)
    assert "Миша" in format_subscription_card(sub)

    katya_participant = next(
        participant for participant in sub.participants if participant.friend_id == katya.id
    )
    katya_participant.share_value = Decimal("7")
    await session.flush()
    sub = await service.update_friends(
        sub,
        user_id=owner.id,
        friend_ids=[misha.id, katya.id, misha.id],
    )
    assert len(sub.participants) == 2
    assert next(
        participant.share_value
        for participant in sub.participants
        if participant.friend_id == katya.id
    ) == Decimal("7")

    sub = await service.update_friends(
        sub,
        user_id=owner.id,
        friend_ids=[misha.id],
    )
    assert [participant.friend_id for participant in sub.participants] == [misha.id]
    assert (
        sub.name,
        sub.amount,
        sub.currency,
        sub.next_charge_date,
        sub.notes,
    ) == original


@pytest.mark.asyncio
async def test_foreign_friend_edit_is_rejected_and_existing_participant_survives(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    attacker = await _user(session, 2)
    own = await _friend(session, owner.id, "Свой друг")
    foreign = await _friend(session, attacker.id, "Чужой друг")
    sub = await SubscriptionService(session).create(_dto(owner.id, [own.id]))
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={"edit_sid": sub.id, "edit_friend_ids": [foreign.id]}
    )
    callback = _callback()

    await edit_friends_toggle(
        callback,
        MenuCb(action="sfr", value="done"),
        state,
        session,
        owner,
    )

    state.update_data.assert_awaited_with(edit_friend_ids=[])
    state.set_state.assert_awaited_with(EditSubscriptionSG.friends)
    callback.answer.assert_awaited_once_with(
        FRIENDS_UNAVAILABLE_MESSAGE,
        show_alert=True,
    )
    rows = list(
        (
            await session.execute(
                select(SubscriptionParticipant).where(
                    SubscriptionParticipant.subscription_id == sub.id
                )
            )
        ).scalars()
    )
    assert [row.friend_id for row in rows] == [own.id]
