from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.base import BaseDAO
from app.users.models import User
from sqlalchemy import select, update as sa_update, delete as sa_delete


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
