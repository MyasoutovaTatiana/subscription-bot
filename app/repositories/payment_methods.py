"""Payment method repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_method import PaymentMethod

PAYMENT_METHOD_UNAVAILABLE_MESSAGE = (
    "Способ оплаты недоступен. Выберите способ оплаты ещё раз."
)


class PaymentMethodUnavailableError(ValueError):
    """Payment method missing, inactive, or not owned by the user."""

    def __init__(self) -> None:
        super().__init__(PAYMENT_METHOD_UNAVAILABLE_MESSAGE)


class PaymentMethodRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self, user_id: int) -> list[PaymentMethod]:
        result = await self._session.execute(
            select(PaymentMethod)
            .where(PaymentMethod.user_id == user_id, PaymentMethod.is_active.is_(True))
            .order_by(PaymentMethod.name)
        )
        return list(result.scalars().all())

    async def get_for_user(self, payment_method_id: int, user_id: int) -> PaymentMethod | None:
        result = await self._session.execute(
            select(PaymentMethod).where(
                PaymentMethod.id == payment_method_id,
                PaymentMethod.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_user(
        self, payment_method_id: int, user_id: int
    ) -> PaymentMethod | None:
        result = await self._session.execute(
            select(PaymentMethod).where(
                PaymentMethod.id == payment_method_id,
                PaymentMethod.user_id == user_id,
                PaymentMethod.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: int,
        name: str,
        optional_last_four: str | None = None,
        optional_currency: str | None = None,
    ) -> PaymentMethod:
        method = PaymentMethod(
            user_id=user_id,
            name=name.strip(),
            optional_last_four=optional_last_four,
            optional_currency=optional_currency,
            is_active=True,
        )
        self._session.add(method)
        await self._session.flush()
        return method

    async def deactivate(
        self,
        method: PaymentMethod,
        *,
        user_id: int,
    ) -> PaymentMethod:
        if method.user_id != user_id:
            raise PaymentMethodUnavailableError
        owned = await self.get_for_user(method.id, user_id)
        if owned is None:
            raise PaymentMethodUnavailableError
        owned.is_active = False
        await self._session.flush()
        return owned
