"""
Фикстуры для тестов игровой логики.
"""
import pytest
import pytest_asyncio
import json
import fakeredis.aioredis
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from app.database import Base

# Важно: импортируем все модели ПЕРЕД импортом User,
# чтобы SQLAlchemy могла правильно разрешить relationships
from app.friends.models import Friend
from app.game.models import GameResult, GameResultEnum, GameType
from app.payments.models import PaymentTransaction
from app.users.models import User

from app.game.redis_dao.custom_redis import CustomRedis
from app.game.redis_dao.manager import get_redis


@pytest.fixture
def fake_redis(monkeypatch):
    """Создаёт фейковый Redis для тестов."""
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    
    # Создаём обёртку CustomRedis
    class FakeCustomRedis(CustomRedis):
        def __init__(self):
            self.redis = fake_redis
        
        async def get(self, key):
            return await fake_redis.get(key)
        
        async def set(self, key, value):
            return await fake_redis.set(key, value)
        
        async def setex(self, key, time, value):
            return await fake_redis.setex(key, time, value)
        
        async def keys(self, pattern):
            return await fake_redis.keys(pattern)
        
        async def unlink(self, *keys):
            return await fake_redis.delete(*keys)
        
        async def flushdb(self):
            return await fake_redis.flushdb()
    
    fake_custom_redis = FakeCustomRedis()
    
    # Мокаем get_redis
    async def get_fake_redis():
        return fake_custom_redis
    
    monkeypatch.setattr("app.game.redis_dao.manager.get_redis", get_fake_redis)
    
    return fake_custom_redis


@pytest_asyncio.fixture
async def fake_session(monkeypatch):
    """Создаёт фейковую сессию БД для тестов."""
    # Создаём in-memory SQLite базу для тестов
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    # Мокаем session dependency для роутера
    async def get_fake_session():
        async with async_session() as session:
            yield session
    
    monkeypatch.setattr("app.database.SessionDep", get_fake_session)
    
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.rollback()
    
    await engine.dispose()


@pytest_asyncio.fixture
async def test_users_2players(fake_session):
    """Создаёт 2 тестовых пользователя."""
    user1 = User(
        tg_id=111111,
        username="test_user_1",
        name="Тестовый Игрок 1",
        balance=Decimal("10000.00"),
        is_active=True
    )
    user2 = User(
        tg_id=222222,
        username="test_user_2",
        name="Тестовый Игрок 2",
        balance=Decimal("10000.00"),
        is_active=True
    )
    
    fake_session.add(user1)
    fake_session.add(user2)
    await fake_session.commit()
    await fake_session.refresh(user1)
    await fake_session.refresh(user2)
    
    return user1, user2


@pytest_asyncio.fixture
async def test_users_3players(fake_session):
    """Создаёт 3 тестовых пользователя."""
    user1 = User(
        tg_id=111111,
        username="test_user_1",
        name="Тестовый Игрок 1",
        balance=Decimal("10000.00"),
        is_active=True
    )
    user2 = User(
        tg_id=222222,
        username="test_user_2",
        name="Тестовый Игрок 2",
        balance=Decimal("10000.00"),
        is_active=True
    )
    user3 = User(
        tg_id=333333,
        username="test_user_3",
        name="Тестовый Игрок 3",
        balance=Decimal("10000.00"),
        is_active=True
    )
    
    fake_session.add(user1)
    fake_session.add(user2)
    fake_session.add(user3)
    await fake_session.commit()
    await fake_session.refresh(user1)
    await fake_session.refresh(user2)
    await fake_session.refresh(user3)
    
    return user1, user2, user3


@pytest.fixture(autouse=True)
def mock_send_msg(monkeypatch):
    """Мокает отправку сообщений через Centrifugo."""
    sent_messages = []
    
    async def fake_send_msg(event, payload, channel_name):
        sent_messages.append({
            "event": event,
            "payload": payload,
            "channel": channel_name
        })
    
    monkeypatch.setattr("app.game.api.utils.send_msg", fake_send_msg)
    
    return sent_messages


@pytest_asyncio.fixture
async def test_users_with_reliability(fake_session):
    """Создаёт 3 тестовых пользователя с данными о надежности."""
    from datetime import datetime, timedelta
    
    user1 = User(
        tg_id=111111,
        username="reliable_user_1",
        name="Надежный 1",
        balance=Decimal("10000.00"),
        is_active=True
    )
    user2 = User(
        tg_id=222222,
        username="reliable_user_2",
        name="Надежный 2",
        balance=Decimal("10000.00"),
        is_active=True
    )
    user3 = User(
        tg_id=333333,
        username="unreliable_user",
        name="Ненадежный",
        balance=Decimal("10000.00"),
        is_active=True
    )
    
    fake_session.add(user1)
    fake_session.add(user2)
    fake_session.add(user3)
    await fake_session.commit()
    await fake_session.refresh(user1)
    await fake_session.refresh(user2)
    await fake_session.refresh(user3)
    
    # Создаём GameResult записи для проверки надежности
    now = datetime.utcnow()
    
    # Игрок 1: Надежный - 1 лив за последние 10 игр
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
    
    fake_session.add_all(results_user1 + results_user2 + results_user3)
    await fake_session.commit()
    
    return user1, user2, user3

