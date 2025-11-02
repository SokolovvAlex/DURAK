"""
Тесты изменения балансов при игре.
Тестирует:
- Списание денег при завершении игры
- Начисление победителю
- Корректность расчётов для 2 и 3 игроков
"""
import pytest
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.game.api.router import find_players, ready, leave
from app.game.api.schemas import FindPartnerRequest, ReadyRequest
from app.game.redis_dao.custom_redis import CustomRedis
from app.users.models import User
from sqlalchemy import select


@pytest.mark.asyncio
async def test_2players_balance_calculation(
    fake_session: AsyncSession,
    fake_redis: CustomRedis,
    test_users_2players
):
    """
    Тест: Правильность расчёта балансов для 2 игроков.
    Проверяем:
    - Победитель получает ставку проигравшего (+1000)
    - Проигравший теряет свою ставку (-1000)
    """
    user1, user2 = test_users_2players
    
    initial_balance_1 = float(user1.balance)
    initial_balance_2 = float(user2.balance)
    
    # Создаём игру
    req1 = FindPartnerRequest(tg_id=111111, nickname="Игрок 1", stake=1000, capacity=2)
    response1 = await find_players(req1, fake_session, fake_redis)
    room_id = response1.room_id
    
    req2 = FindPartnerRequest(tg_id=222222, nickname="Игрок 2", stake=1000, capacity=2)
    await find_players(req2, fake_session, fake_redis)
    
    # Начинаем игру
    await ready(ReadyRequest(tg_id=111111, room_id=room_id), fake_redis)
    await ready(ReadyRequest(tg_id=222222, room_id=room_id), fake_redis)
    
    # Игрок 2 ливнул - игрок 1 победил
    await leave(ReadyRequest(tg_id=222222, room_id=room_id), fake_session, fake_redis)
    
    # Проверяем балансы
    await fake_session.refresh(user1)
    await fake_session.refresh(user2)
    
    # Победитель получил ставку проигравшего
    assert float(user1.balance) == initial_balance_1 + 1000
    
    # Проигравший потерял ставку
    assert float(user2.balance) == initial_balance_2 - 1000
    
    print("✅ Тест балансов 2 игроков: расчёты корректны")


@pytest.mark.asyncio
async def test_3players_balance_calculation(
    fake_session: AsyncSession,
    fake_redis: CustomRedis,
    test_users_3players
):
    """
    Тест: Правильность расчёта балансов для 3 игроков.
    Проверяем:
    - Победитель получает ставки всех проигравших (2 * 1000 = 2000)
    - Проигравшие теряют по ставке каждый (-1000 каждый)
    """
    user1, user2, user3 = test_users_3players
    
    initial_balance_1 = float(user1.balance)
    initial_balance_2 = float(user2.balance)
    initial_balance_3 = float(user3.balance)
    
    # Создаём игру на 3 игроков
    req1 = FindPartnerRequest(tg_id=111111, nickname="Игрок 1", stake=1000, capacity=3)
    response1 = await find_players(req1, fake_session, fake_redis)
    room_id = response1.room_id
    
    await find_players(FindPartnerRequest(tg_id=222222, nickname="Игрок 2", stake=1000, capacity=3), fake_session, fake_redis)
    await find_players(FindPartnerRequest(tg_id=333333, nickname="Игрок 3", stake=1000, capacity=3), fake_session, fake_redis)
    
    # Начинаем игру
    await ready(ReadyRequest(tg_id=111111, room_id=room_id), fake_redis)
    await ready(ReadyRequest(tg_id=222222, room_id=room_id), fake_redis)
    await ready(ReadyRequest(tg_id=333333, room_id=room_id), fake_redis)
    
    # Игрок 3 ливнул - игра продолжается
    await leave(ReadyRequest(tg_id=333333, room_id=room_id), fake_session, fake_redis)
    
    # Игрок 2 ливнул - игрок 1 победил
    await leave(ReadyRequest(tg_id=222222, room_id=room_id), fake_session, fake_redis)
    
    # Проверяем балансы
    await fake_session.refresh(user1)
    await fake_session.refresh(user2)
    await fake_session.refresh(user3)
    
    # Победитель получил ставки обоих проигравших
    assert float(user1.balance) == initial_balance_1 + 2000  # 2 * 1000
    
    # Оба проигравших потеряли по ставке
    assert float(user2.balance) == initial_balance_2 - 1000
    assert float(user3.balance) == initial_balance_3 - 1000
    
    print("✅ Тест балансов 3 игроков: расчёты корректны")

