from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

# from app.bot.keyboards.kbs import main_keyboard
from app.database import connection, SessionDep
from app.friends.dao import FriendDAO
from app.friends.models import Friend
from app.users.dao import UserDAO
from app.users.schemas import TelegramIDModel, UserCreate

router = Router()

@router.message(CommandStart())
@connection()
async def cmd_start(message: Message, session: SessionDep, **kwargs):
    username = message.from_user.username or "игрок"
    welcome_text = (
        f"👋 Приветствуем тебя @{username}"
    )

    tg_id = message.from_user.id

    # ищем юзера
    user = await UserDAO.find_one_or_none(session, tg_id=tg_id)
    if not user:
        values = UserCreate(
            tg_id=tg_id,
            username=message.from_user.username,
            name=message.from_user.first_name,
            is_admin=False,
            balance=1_000_000
        )
        user = await UserDAO.add(session, **values.model_dump())

    # --- проверяем реферальную ссылку ---
    if message.text and message.text.startswith("/start ref"):
        try:
            referrer_id = int(message.text.split("ref")[1])
            if referrer_id != tg_id:
                referrer = await UserDAO.find_one_or_none(session, tg_id=referrer_id)
                if referrer:
                    if not await FriendDAO.exists(session, tg_id, referrer_id):
                        session.add(Friend(user_id=tg_id, friend_id=referrer_id))
                        await session.commit()
                        await message.answer(f"🎉 Ты был перешел по реферальной ссылке и добавлен в друзья")
        except Exception as e:
            print(f"[REFERRAL ERROR] {e}")
    await message.answer(welcome_text)
