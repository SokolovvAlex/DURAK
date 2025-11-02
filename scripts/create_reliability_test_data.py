"""
Скрипт для создания тестовых данных надежности игроков.
Создаёт GameResult записи для проверки надежности:
- 2 надежных игрока (1-2 лива за последние 10 игр)
- 1 ненадежный игрок (3+ лива за последние 10 игр)
"""
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy import select
from app.database import async_session_maker
from app.users.models import User
from app.game.models import GameResult, GameResultEnum

# Важно: импортируем все модели ПЕРЕД импортом User,
# чтобы SQLAlchemy могла правильно разрешить relationships
from app.friends.models import Friend
from app.payments.models import PaymentTransaction


async def create_reliability_test_data():
    """Создаёт тестовые данные для проверки надежности игроков."""
    async with async_session_maker() as session:
        # Получаем или создаём тестовых пользователей
        user1 = await session.scalar(select(User).where(User.tg_id == 111111))
        user2 = await session.scalar(select(User).where(User.tg_id == 222222))
        user3 = await session.scalar(select(User).where(User.tg_id == 333333))
        
        if not user1:
            user1 = User(tg_id=111111, username="reliable_user_1", name="Надежный 1", balance=Decimal("10000.00"), is_active=True)
            session.add(user1)
            await session.flush()
        
        if not user2:
            user2 = User(tg_id=222222, username="reliable_user_2", name="Надежный 2", balance=Decimal("10000.00"), is_active=True)
            session.add(user2)
            await session.flush()
        
        if not user3:
            user3 = User(tg_id=333333, username="unreliable_user", name="Ненадежный", balance=Decimal("10000.00"), is_active=True)
            session.add(user3)
            await session.flush()
        
        await session.commit()
        await session.refresh(user1)
        await session.refresh(user2)
        await session.refresh(user3)
        
        # Создаём GameResult записи для проверки надежности
        now = datetime.utcnow()
        
        # Игрок 1: Надежный - 1 лив за последние 10 игр
        # 7 побед, 2 обычных проигрыша, 1 лив = 1 лив из 10 игр
        results_user1 = []
        for i in range(10):
            created_at = now - timedelta(days=10-i)
            if i == 9:  # Последняя игра - лив
                results_user1.append(GameResult(
                    user_id=user1.id,
                    result=GameResultEnum.LOSS_BY_LEAVE,
                    rate=1000,
                    created_at=created_at
                ))
            elif i < 7:  # 7 побед
                results_user1.append(GameResult(
                    user_id=user1.id,
                    result=GameResultEnum.WIN,
                    rate=1000,
                    created_at=created_at
                ))
            else:  # 2 обычных проигрыша
                results_user1.append(GameResult(
                    user_id=user1.id,
                    result=GameResultEnum.LOSS,
                    rate=1000,
                    created_at=created_at
                ))
        
        # Игрок 2: Надежный - 2 лива за последние 10 игр
        # 5 побед, 3 обычных проигрыша, 2 лива = 2 лива из 10 игр
        results_user2 = []
        for i in range(10):
            created_at = now - timedelta(days=10-i)
            if i >= 8:  # Последние 2 игры - ливы
                results_user2.append(GameResult(
                    user_id=user2.id,
                    result=GameResultEnum.LOSS_BY_LEAVE,
                    rate=1000,
                    created_at=created_at
                ))
            elif i < 5:  # 5 побед
                results_user2.append(GameResult(
                    user_id=user2.id,
                    result=GameResultEnum.WIN,
                    rate=1000,
                    created_at=created_at
                ))
            else:  # 3 обычных проигрыша
                results_user2.append(GameResult(
                    user_id=user2.id,
                    result=GameResultEnum.LOSS,
                    rate=1000,
                    created_at=created_at
                ))
        
        # Игрок 3: Ненадежный - 3 лива за последние 10 игр
        # 3 победы, 4 обычных проигрыша, 3 лива = 3 лива из 10 игр (> 2, не надежный)
        results_user3 = []
        for i in range(10):
            created_at = now - timedelta(days=10-i)
            if i >= 7:  # Последние 3 игры - ливы
                results_user3.append(GameResult(
                    user_id=user3.id,
                    result=GameResultEnum.LOSS_BY_LEAVE,
                    rate=1000,
                    created_at=created_at
                ))
            elif i < 3:  # 3 победы
                results_user3.append(GameResult(
                    user_id=user3.id,
                    result=GameResultEnum.WIN,
                    rate=1000,
                    created_at=created_at
                ))
            else:  # 4 обычных проигрыша
                results_user3.append(GameResult(
                    user_id=user3.id,
                    result=GameResultEnum.LOSS,
                    rate=1000,
                    created_at=created_at
                ))
        
        # Удаляем старые записи для этих пользователей (если есть)
        await session.execute(
            select(GameResult).where(GameResult.user_id.in_([user1.id, user2.id, user3.id])).delete()
        )
        
        # Добавляем новые записи
        session.add_all(results_user1 + results_user2 + results_user3)
        await session.commit()
        
        print("✅ Созданы тестовые данные надежности:")
        print(f"   Игрок 1 (111111): 1 лив из 10 игр - НАДЕЖНЫЙ ✅")
        print(f"   Игрок 2 (222222): 2 лива из 10 игр - НАДЕЖНЫЙ ✅")
        print(f"   Игрок 3 (333333): 3 лива из 10 игр - НЕНАДЕЖНЫЙ ❌")


if __name__ == "__main__":
    asyncio.run(create_reliability_test_data())

