"""
Тесты игровой логики для 2 игроков.
Тестирует:
- Создание комнаты и старт игры
- Завершение игры
- Начисление штрафных очков
- Изменение балансов
- Записи GameResult
"""
import pytest
import json
from decimal import Decimal
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.game.api.router import find_players, ready, move, leave
from app.game.api.schemas import FindPartnerRequest, ReadyRequest, MoveRequest
from app.game.redis_dao.custom_redis import CustomRedis
from app.users.models import User
from app.game.models import GameResult, GameResultEnum
from app.payments.models import PaymentTransaction, TxTypeEnum
from app.users.dao import UserDAO


@pytest.mark.asyncio
async def test_2players_full_game_winner_loser_balances(
    fake_session: AsyncSession,
    fake_redis: CustomRedis,
    test_users_2players
):
    """
    Тест: Полная игра на 2 игроков с проверкой балансов.
    Сценарий:
    1. Два игрока создают комнату и начинают игру
    2. Игра завершается с победителем и проигравшим
    3. Проверяем изменение балансов
    4. Проверяем записи GameResult
    """
    user1, user2 = test_users_2players
    
    # Шаг 1: Первый игрок создаёт комнату
    req1 = FindPartnerRequest(
        tg_id=111111,
        nickname="Игрок 1",
        stake=1000,
        capacity=2,
        speed="normal",
        redeal=False,
        dark=False,
        reliable_only=False
    )
    response1 = await find_players(req1, fake_session, fake_redis)
    room_id = response1.room_id
    assert response1.status == "waiting"
    
    # Проверяем начальные балансы
    await fake_session.refresh(user1)
    initial_balance_1 = float(user1.balance)
    assert initial_balance_1 == 10000.0
    
    # Шаг 2: Второй игрок присоединяется
    req2 = FindPartnerRequest(
        tg_id=222222,
        nickname="Игрок 2",
        stake=1000,
        capacity=2,
        speed="normal",
        redeal=False,
        dark=False,
        reliable_only=False
    )
    response2 = await find_players(req2, fake_session, fake_redis)
    assert response2.room_id == room_id
    assert response2.status == "matched"
    
    # Шаг 3: Оба игрока готовы - игра начинается
    ready_req1 = ReadyRequest(tg_id=111111, room_id=room_id)
    await ready(ready_req1, fake_redis)
    
    ready_req2 = ReadyRequest(tg_id=222222, room_id=room_id)
    await ready(ready_req2, fake_redis)
    
    # Проверяем, что игра началась (есть карты)
    room_data = json.loads(await fake_redis.get(room_id))
    assert room_data["status"] == "playing"
    assert "deck" in room_data
    assert len(room_data["players"]["111111"]["hand"]) == 4
    assert len(room_data["players"]["222222"]["hand"]) == 4
    
    # Шаг 4: Симулируем завершение игры через лив одного игрока
    # (Это самый простой способ завершить игру для теста)
    leave_req = ReadyRequest(tg_id=222222, room_id=room_id)
    result = await leave(leave_req, fake_session, fake_redis)

    # Проверяем результат
    assert result["ok"] is True
    assert result["winner"] == "111111"
    assert "losers" in result  # Теперь это список ливеров
    assert "222222" in result["losers"]
    
    # Шаг 5: Проверяем изменение балансов
    await fake_session.refresh(user1)
    await fake_session.refresh(user2)
    
    # Победитель получил ставку проигравшего (1000)
    assert float(user1.balance) == initial_balance_1 + 1000
    
    # Проигравший потерял ставку (1000)
    initial_balance_2 = 10000.0
    assert float(user2.balance) == initial_balance_2 - 1000
    
    # Шаг 6: Проверяем записи GameResult
    from sqlalchemy import select
    result1 = await fake_session.scalar(
        select(GameResult).where(GameResult.user_id == user1.id)
    )
    assert result1 is not None
    assert result1.result == GameResultEnum.WIN
    assert float(result1.rate) == 1000.0
    
    result2 = await fake_session.scalar(
        select(GameResult).where(GameResult.user_id == user2.id)
    )
    assert result2 is not None
    assert result2.result == GameResultEnum.LOSS_BY_LEAVE  # Ливер!
    
    print("✅ Тест 2 игроков: балансы и GameResult корректны")


@pytest.mark.asyncio
async def test_2players_insufficient_balance(
    fake_session: AsyncSession,
    fake_redis: CustomRedis,
    test_users_2players
):
    """
    Тест: Игрок с недостаточным балансом не может создать комнату.
    """
    user1, user2 = test_users_2players
    
    # Устанавливаем недостаточный баланс
    user1.balance = Decimal("500.00")
    await fake_session.commit()
    
    # Попытка создать комнату с большей ставкой
    req = FindPartnerRequest(
        tg_id=111111,
        nickname="Игрок 1",
        stake=1000,  # Больше чем баланс (500)
        capacity=2
    )
    
    with pytest.raises(Exception) as exc_info:
        await find_players(req, fake_session, fake_redis)
    
    assert "Недостаточно средств" in str(exc_info.value)
    print("✅ Тест: недостаточный баланс обработан корректно")

