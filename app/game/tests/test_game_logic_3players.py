"""
Тесты игровой логики для 3 игроков.
Тестирует:
- Создание комнаты на 3 игроков
- Лив игрока во время игры (игра продолжается между оставшимися)
- Завершение игры
- Начисление балансов
"""
import pytest
import json
from decimal import Decimal
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.game.api.router import find_players, ready, leave
from app.game.api.schemas import FindPartnerRequest, ReadyRequest
from app.game.redis_dao.custom_redis import CustomRedis
from app.users.models import User
from app.game.models import GameResult, GameResultEnum
from sqlalchemy import select


@pytest.mark.asyncio
async def test_3players_leave_continues_game(
    fake_session: AsyncSession,
    fake_redis: CustomRedis,
    test_users_3players
):
    """
    Тест: Лив игрока во время игры на 3 игроков.
    Сценарий:
    1. Три игрока создают комнату и начинают игру
    2. Один игрок ливнул
    3. Игра продолжается между оставшимися 2 игроками
    4. Проверяем балансы и GameResult
    """
    user1, user2, user3 = test_users_3players
    
    # Шаг 1: Создаём комнату на 3 игроков
    req1 = FindPartnerRequest(
        tg_id=111111,
        nickname="Игрок 1",
        stake=1000,
        capacity=3
    )
    response1 = await find_players(req1, fake_session, fake_redis)
    room_id = response1.room_id
    
    # Шаг 2: Второй игрок присоединяется
    req2 = FindPartnerRequest(
        tg_id=222222,
        nickname="Игрок 2",
        stake=1000,
        capacity=3
    )
    await find_players(req2, fake_session, fake_redis)
    
    # Шаг 3: Третий игрок присоединяется
    req3 = FindPartnerRequest(
        tg_id=333333,
        nickname="Игрок 3",
        stake=1000,
        capacity=3
    )
    await find_players(req3, fake_session, fake_redis)
    
    # Шаг 4: Все готовы - игра начинается
    await ready(ReadyRequest(tg_id=111111, room_id=room_id), fake_redis)
    await ready(ReadyRequest(tg_id=222222, room_id=room_id), fake_redis)
    await ready(ReadyRequest(tg_id=333333, room_id=room_id), fake_redis)
    
    # Проверяем, что игра началась
    room_data = json.loads(await fake_redis.get(room_id))
    assert room_data["status"] == "playing"
    assert len(room_data["players"]) == 3
    
    # Шаг 5: Один игрок ливнул
    initial_balance_3 = float(user3.balance)
    leave_req = ReadyRequest(tg_id=333333, room_id=room_id)
    result = await leave(leave_req, fake_session, fake_redis)
    
    # Проверяем, что игра продолжилась (не завершилась)
    assert result["ok"] is True
    assert "remaining" in result
    assert len(result["remaining"]) == 2  # Осталось 2 игрока
    assert "111111" in result["remaining"]
    assert "222222" in result["remaining"]
    
    # Проверяем, что комната все ещё существует и игра продолжается
    room_data = json.loads(await fake_redis.get(room_id))
    assert room_data["status"] == "playing"
    assert len(room_data["players"]) == 2  # Осталось 2 игрока
    
    # Шаг 6: Проверяем GameResult для ливера
    await fake_session.refresh(user3)
    result3 = await fake_session.scalar(
        select(GameResult).where(GameResult.user_id == user3.id)
    )
    assert result3 is not None
    assert result3.result == GameResultEnum.LOSS_BY_LEAVE
    
    # Шаг 7: Второй игрок ливнул - игра завершается
    leave_req2 = ReadyRequest(tg_id=222222, room_id=room_id)
    result2 = await leave(leave_req2, fake_session, fake_redis)
    
    # Теперь игра завершена
    assert result2["ok"] is True
    assert result2["winner"] == "111111"
    assert "losers" in result2  # Теперь это список всех ливеров
    assert "222222" in result2["losers"]
    assert "333333" in result2["losers"]  # Первый ливер тоже должен быть в списке
    
    # Шаг 8: Проверяем балансы
    await fake_session.refresh(user1)
    await fake_session.refresh(user2)
    
    # Победитель получил ставки обоих проигравших (2 * 1000 = 2000)
    initial_balance_1 = 10000.0
    assert float(user1.balance) == initial_balance_1 + 2000
    
    # Второй проигравший потерял ставку
    initial_balance_2 = 10000.0
    assert float(user2.balance) == initial_balance_2 - 1000
    
    print("✅ Тест 3 игроков: лив и продолжение игры работают корректно")

