from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.config import settings


# def main_keyboard() -> InlineKeyboardMarkup:
#     kb = InlineKeyboardBuilder()
#
#     kb.button(text="🎮 Старт игры 2048", web_app=WebAppInfo(url=settings.BASE_SITE))
#     kb.button(text="🏆 Лидеры 2048", web_app=WebAppInfo(url=f"{settings.BASE_SITE}/records"))
#     kb.button(text="📈 Мой рекорд", callback_data="show_my_record")
#
#     kb.adjust(1)
#     return kb.as_markup()
