"""FSM states for subscription flows."""

from aiogram.fsm.state import State, StatesGroup


class AddSubscriptionSG(StatesGroup):
    name = State()
    category = State()
    amount = State()
    currency = State()
    billing_type = State()
    billing_interval = State()
    next_charge_date = State()
    payment_method = State()
    new_payment_method_name = State()
    reminders = State()
    friends = State()
    confirm = State()


class EditSubscriptionSG(StatesGroup):
    field = State()
    value = State()


class ConfirmChargeSG(StatesGroup):
    """Ожидание фактической суммы в ₽ после «Списалось» (только иновалюта)."""

    actual_rub = State()


class EditChargeSG(StatesGroup):
    """Редактирование сохранённого списания."""

    amount = State()
    date = State()
    rate = State()
