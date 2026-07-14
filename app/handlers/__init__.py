"""Handler routers aggregation."""

from aiogram import Router

from app.handlers import cancel, charges, debts, one_time_payments, settings, start, subscriptions, upcoming


def setup_routers() -> Router:
    """Global commands and shell navigation are registered before FSM-heavy routers."""
    root = Router(name="root")
    root.include_router(cancel.router)
    root.include_router(start.router)
    root.include_router(settings.router)
    root.include_router(upcoming.router)
    root.include_router(debts.router)
    root.include_router(charges.router)
    root.include_router(subscriptions.router)
    root.include_router(one_time_payments.router)
    return root
