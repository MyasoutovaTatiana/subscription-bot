"""Cancel current FSM scenario."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.keyboards.main_menu import main_menu_keyboard
from app.ui import toast_cancelled
from app.ui.tokens import Copy

router = Router(name="cancel")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer(Copy.NOTHING_TO_CANCEL, reply_markup=main_menu_keyboard())
        return
    await state.clear()
    await message.answer(toast_cancelled(), reply_markup=main_menu_keyboard())
