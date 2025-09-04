from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

from app.bot.keyboards.kbs import main_keyboard
from app.database import connection, SessionDep
from app.users.dao import UserDAO
from app.users.schemas import TelegramIDModel, UserCreate

router = Router()


@router.message(CommandStart())
@connection()
async def cmd_start(message: Message, session: SessionDep, **kwargs):
    username = message.from_user.username or "игрок"
    welcome_text = (
        f"👋 Приветствуем тебя @{username} в игре Дурак Онлайн!\n"
        "•  Реальные игроки\n"
        "•  Партии от 2 до 5 игроков\n"
        "•  Оптимизировано для игры на мобильном телефоне"
    )

    tg_id = message.from_user.id
    print(tg_id)
    user = await UserDAO.find_one_or_none(session, tg_id=tg_id)
    print(user)
    if not user:
        values = UserCreate(
            tg_id=tg_id,
            username=message.from_user.username,
            name=message.from_user.first_name,
            is_admin=False,
        )
        user = await UserDAO.add(session, **values.model_dump())

    await message.answer(welcome_text, reply_markup=main_keyboard())
