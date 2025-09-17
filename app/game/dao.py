from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.base import BaseDAO
from app.game.models import GameType


class GameTypeDAO(BaseDAO):
    model = GameType

    @classmethod
    async def get_active_games(cls, session: AsyncSession):
        """Получить все активные игры"""
        return await cls.find_all(session, is_active=True)

    @classmethod
    async def get_game_by_name(cls, session: AsyncSession, name: str):
        """Получить игру по названию"""
        return await cls.find_one_or_none(session, name=name)

