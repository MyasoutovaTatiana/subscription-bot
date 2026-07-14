"""FSM states for one-time payments."""

from aiogram.fsm.state import State, StatesGroup


class OneTimePaymentSG(StatesGroup):
    name = State()
    currency = State()
    amount = State()
    payment_date = State()
    payment_method = State()
    new_payment_method_name = State()
    friends = State()
    new_friend_name = State()
    include_owner = State()
    split_mode = State()
    confirm = State()
