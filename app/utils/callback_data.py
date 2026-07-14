"""Short structured callback data helpers."""

from aiogram.filters.callback_data import CallbackData


class SubCb(CallbackData, prefix="sub"):
    action: str
    sid: int = 0


class PayCb(CallbackData, prefix="pay"):
    action: str
    pid: int = 0


class DebtCb(CallbackData, prefix="debt"):
    action: str
    did: int = 0


class MenuCb(CallbackData, prefix="m"):
    action: str
    value: str = ""


class TxCb(CallbackData, prefix="tx"):
    action: str
    tid: int = 0
