from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import User
from app.admin.auth import get_password_hash


class AdminDAO:
    """DAO для работы с администраторами"""

    @staticmethod
    async def create_admin(
        session: AsyncSession,
        login: str,
        password: str,
        name: Optional[str] = None,
        username: Optional[str] = None,
        is_super_admin: bool = False
    ) -> User:
        """Создание нового администратора"""
        # Проверяем, существует ли уже пользователь с таким логином
        existing_user = await AdminDAO.find_admin_by_login(session, login)
        if existing_user:
            raise ValueError("Администратор с таким логином уже существует")

        # Хешируем пароль
        hashed_password = get_password_hash(password)

        # Создаем нового пользователя
        new_admin = User(
            login=login,
            password=hashed_password,
            name=name,
            username=username,
            is_admin=True,
            is_super_admin=is_super_admin,
            is_active=True
        )

        session.add(new_admin)
        try:
            await session.commit()
            await session.refresh(new_admin)
            return new_admin
        except SQLAlchemyError:
            await session.rollback()
            raise

    @staticmethod
    async def find_admin_by_login(session: AsyncSession, login: str) -> Optional[User]:
        """Поиск администратора по логину"""
        query = select(User).where(User.login == login)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def find_admin_by_id(session: AsyncSession, admin_id: int) -> Optional[User]:
        """Поиск администратора по ID"""
        query = select(User).where(User.id == admin_id)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_admins(session: AsyncSession) -> list[User]:
        """Получение всех администраторов"""
        query = select(User).where(User.is_admin == True)
        result = await session.execute(query)
        return list(result.scalars().all())

