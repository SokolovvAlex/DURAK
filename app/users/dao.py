from typing import Optional, Any

from sqlalchemy import select, func, case
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.base import BaseDAO
from app.game.models import GameResult, GameResultEnum
from app.users.models import User
from sqlalchemy import select, update as sa_update, delete as sa_delete

from app.users.schemas import UserStatsOut
from app.game.api.reliability import get_player_reliability_stats


class UserDAO:
    model = User

    @classmethod
    async def find_all(cls, session: AsyncSession, **filter_by) -> list[User]:
        q = select(cls.model).filter_by(**filter_by)
        res = await session.execute(q)
        return list(res.scalars().all())

    @classmethod
    async def find_one_or_none(cls, session: AsyncSession, **filter_by) -> Optional[User]:
        q = select(cls.model).filter_by(**filter_by)
        res = await session.execute(q)
        return res.scalar_one_or_none()

    @classmethod
    async def find_one_or_none_by_id(cls, session: AsyncSession, model_id: int) -> Optional[User]:
        q = select(cls.model).where(cls.model.id == model_id)
        res = await session.execute(q)
        return res.scalar_one_or_none()

    @classmethod
    async def add(cls, session: AsyncSession, **values) -> User:
        obj = cls.model(**values)
        session.add(obj)
        try:
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise
        await session.refresh(obj)
        return obj

    @classmethod
    async def update(cls, session: AsyncSession, filter_by: dict[str, Any], **values) -> Optional[User]:
        """Возвращает уже ОБНОВЛЁННОГО пользователя (или None, если не найден)."""
        values = {k: v for k, v in values.items() if v is not None}
        if not values:
            return await cls.find_one_or_none(session, **filter_by)

        try:
            q = sa_update(cls.model).where(
                *[getattr(cls.model, k) == v for k, v in filter_by.items()]
            ).values(**values).returning(cls.model.id)
            res = await session.execute(q)
            row = res.fetchone()
            if not row:
                await session.rollback()
                return None
            await session.commit()

            return await cls.find_one_or_none_by_id(session, row[0])
        except SQLAlchemyError:
            await session.rollback()
            raise

    @classmethod
    async def delete(cls, session: AsyncSession, **filter_by) -> int:
        try:
            q = sa_delete(cls.model).filter_by(**filter_by)
            res = await session.execute(q)
            await session.commit()
            return res.rowcount or 0
        except SQLAlchemyError:
            await session.rollback()
            raise

    @classmethod
    async def get_user_with_stats(cls, session: AsyncSession, tg_id: int) -> Optional[UserStatsOut]:
        # Подзапрос для статистики игр
        game_stats_subquery = (
            select(
                GameResult.user_id,
                func.count(GameResult.id).label('total_games'),
                func.sum(case((GameResult.result == GameResultEnum.WIN, 1), else_=0)).label('wins'),
                func.sum(case((GameResult.result == GameResultEnum.LOSS, 1), else_=0)).label('losses'),
                func.sum(case((GameResult.result == GameResultEnum.WIN, GameResult.rate), else_=0)).label(
                    'total_earned'),
                func.sum(case((GameResult.result == GameResultEnum.LOSS, GameResult.rate), else_=0)).label('total_lost')
            )
            .group_by(GameResult.user_id)
            .subquery()
        )

        stmt = (
            select(
                User,
                func.coalesce(game_stats_subquery.c.total_games, 0).label('total_games'),
                func.coalesce(game_stats_subquery.c.wins, 0).label('wins'),
                func.coalesce(game_stats_subquery.c.losses, 0).label('losses'),
                func.coalesce(game_stats_subquery.c.total_earned, 0).label('total_earned'),
                func.coalesce(game_stats_subquery.c.total_lost, 0).label('total_lost'),
                (func.coalesce(game_stats_subquery.c.total_earned, 0) -
                 func.coalesce(game_stats_subquery.c.total_lost, 0)).label('net_profit')
            )
            .outerjoin(game_stats_subquery, User.id == game_stats_subquery.c.user_id)
            .where(User.tg_id == tg_id)
        )

        result = await session.execute(stmt)
        user_data = result.first()

        if not user_data:
            return None

        user, total_games, wins, losses, total_earned, total_lost, net_profit = user_data

        # Получаем статистику надежности
        reliability_stats = await get_player_reliability_stats(session, user.tg_id)

        return UserStatsOut(
            id=user.id,
            tg_id=user.tg_id,
            username=user.username,
            name=user.name,
            balance=user.balance,
            is_admin=user.is_admin,
            is_active=user.is_active,
            created_at=user.created_at,
            total_games=total_games,
            wins=wins,
            losses=losses,
            total_earned=total_earned,
            total_lost=total_lost,
            net_profit=net_profit,
            is_reliable=reliability_stats["is_reliable"],
            reliability=reliability_stats["reliability"],
            leaves_in_last_10=reliability_stats["leaves"]
        )
