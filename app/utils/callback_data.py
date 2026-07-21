"""Short structured callback data helpers."""

from aiogram.filters.callback_data import CallbackData


class SubCb(CallbackData, prefix="sub"):
    """Legacy / general subscription actions: ``sub:<action>:<sid>``."""

    action: str
    sid: int = 0


class SubPeriodCb(CallbackData, prefix="sub"):
    """Period-scoped actions: ``sub:<action>:<sid>:<YYYYMMDD>`` (≤64 bytes)."""

    action: str
    sid: int
    period: str


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
