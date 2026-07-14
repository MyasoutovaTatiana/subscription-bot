"""Main reply keyboard — app navigation shell (UI Kit)."""

from app.ui.buttons import main_reply_keyboard
from app.ui.tokens import Nav

# Public button constants used by handlers (F.text == …)
BTN_HOME = Nav.HOME
BTN_ADD_SUBSCRIPTION = Nav.ADD_SUBSCRIPTION
BTN_ONE_TIME = Nav.ONE_TIME
BTN_UPCOMING = Nav.UPCOMING
BTN_MY_SUBSCRIPTIONS = Nav.SUBSCRIPTIONS
BTN_DEBTS = Nav.DEBTS
BTN_SETTINGS = Nav.SETTINGS

# All reply-shell labels — FSM text steps must not consume these
MAIN_MENU_TEXTS: frozenset[str] = frozenset(
    {
        BTN_HOME,
        BTN_ADD_SUBSCRIPTION,
        BTN_ONE_TIME,
        BTN_UPCOMING,
        BTN_MY_SUBSCRIPTIONS,
        BTN_DEBTS,
        BTN_SETTINGS,
    }
)


def main_menu_keyboard():
    return main_reply_keyboard()
