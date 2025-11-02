"""
Скрипт для создания тестовых пользователей.
Запускается для заполнения БД тестовыми данными перед тестированием.
"""
import asyncio
from decimal import Decimal
from sqlalchemy import select

# Важно: импортируем все модели ПЕРЕД импортом User,
# чтобы SQLAlchemy могла правильно разрешить relationships
from app.friends.models import Friend
from app.game.models import GameResult, GameType
from app.payments.models import PaymentTransaction
from app.users.models import User
from app.database import async_session_maker

# После импорта всех моделей, SQLAlchemy сможет корректно разрешить relationships


async def create_test_users():
    """Создаёт тестовых пользователей для игры."""
    async with async_session_maker() as session:
        # Проверяем, есть ли уже тестовые пользователи
        test_user_1 = await session.scalar(
            select(User).where(User.tg_id == 111111)
        )
        test_user_2 = await session.scalar(
            select(User).where(User.tg_id == 222222)
        )
        test_user_3 = await session.scalar(
            select(User).where(User.tg_id == 333333)
        )
        
        # Создаём пользователей, если их нет
        if not test_user_1:
            user1 = User(
                tg_id=111111,
                username="test_user_1",
                name="Тестовый Игрок 1",
                balance=Decimal("10000.00"),  # 10000 для тестов
                is_active=True
            )
            session.add(user1)
            print(f"✅ Создан пользователь 1: tg_id=111111, balance=10000")
        else:
            # Обновляем баланс если пользователь существует
            test_user_1.balance = Decimal("10000.00")
            print(f"✅ Обновлён пользователь 1: tg_id=111111, balance=10000")
        
        if not test_user_2:
            user2 = User(
                tg_id=222222,
                username="test_user_2",
                name="Тестовый Игрок 2",
                balance=Decimal("10000.00"),
                is_active=True
            )
            session.add(user2)
            print(f"✅ Создан пользователь 2: tg_id=222222, balance=10000")
        else:
            test_user_2.balance = Decimal("10000.00")
            print(f"✅ Обновлён пользователь 2: tg_id=222222, balance=10000")
        
        if not test_user_3:
            user3 = User(
                tg_id=333333,
                username="test_user_3",
                name="Тестовый Игрок 3",
                balance=Decimal("10000.00"),
                is_active=True
            )
            session.add(user3)
            print(f"✅ Создан пользователь 3: tg_id=333333, balance=10000")
        else:
            test_user_3.balance = Decimal("10000.00")
            print(f"✅ Обновлён пользователь 3: tg_id=333333, balance=10000")
        
        await session.commit()
        print("\n✅ Все тестовые пользователи готовы!")
        print("   tg_id: 111111, 222222, 333333")
        print("   balance: 10000 у каждого")


if __name__ == "__main__":
    asyncio.run(create_test_users())

