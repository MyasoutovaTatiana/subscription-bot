"""Start, help and home screen."""

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.main_menu import BTN_HOME, main_menu_keyboard
from app.models.user import User
from app.ui.home import build_home_screen

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    await state.clear()
    args = (command.args or "").strip()
    if args.startswith("debt_"):
        from app.handlers.debts import show_friend_debt

        token = args[len("debt_") :]
        await show_friend_debt(
            message,
            session,
            token=token,
            telegram_user_id=db_user.telegram_user_id,
        )
        return

    text = await build_home_screen(session, db_user)
    await message.answer(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")


@router.message(F.text == BTN_HOME)
@router.message(Command("menu", "home"))
async def cmd_home(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await state.clear()
    text = await build_home_screen(session, db_user)
    await message.answer(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "ℹ️ <b>Справка</b>\n\n"
        "Бот помогает следить за подписками, списаниями и долгами.\n\n"
        "<b>Меню</b>\n"
        "🏠 Главная — сводка\n"
        "💳 Подписки — список и карточки\n"
        "📅 Списания — ближайшие платежи\n"
        "👥 Долги — кто должен\n"
        "💸 Платёж — разовый расход\n"
        "➕ Подписка — новая подписка\n"
        "⚙️ Настройки\n\n"
        "/cancel — выйти из текущего шага",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
