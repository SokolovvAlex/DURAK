"""
Тесты режима игры для надежных игроков (reliable_only).
Тестирует:
- Проверку надежности игроков при входе в комнату
- Блокировку ненадежных игроков
- Разрешение надежным игрокам
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.game.api.router import find_players
from app.game.api.schemas import FindPartnerRequest
from app.game.redis_dao.custom_redis import CustomRedis
from app.game.models import GameResult, GameResultEnum
from app.users.models import User
from sqlalchemy import select
from decimal import Decimal
from datetime import datetime, timedelta


@pytest.mark.asyncio
async def test_reliable_only_blocks_unreliable_player(
    fake_session: AsyncSession,
    fake_redis: CustomRedis,
    test_users_with_reliability
):
    """
    Тест: Ненадежный игрок не может войти в комнату с reliable_only=True.
    Сценарий:
    1. Создаётся комната с reliable_only=True надежным игроком
    2. Ненадежный игрок пытается присоединиться
    3. Должна быть ошибка
    """
    user1, user2, user3 = test_users_with_reliability
    
    # Игрок 1 (надежный) создаёт комнату с reliable_only
    req1 = FindPartnerRequest(
        tg_id=111111,
        nickname="Надежный 1",
        stake=1000,
        capacity=3,
        reliable_only=True
    )
    response1 = await find_players(req1, fake_session, fake_redis)
    room_id = response1.room_id
    assert response1.reliable_only is True
    
    # Игрок 2 (надежный) присоединяется успешно
    req2 = FindPartnerRequest(
        tg_id=222222,
        nickname="Надежный 2",
        stake=1000,
        capacity=3,
        reliable_only=True
    )
    response2 = await find_players(req2, fake_session, fake_redis)
    assert response2.room_id == room_id  # Успешно присоединился
    
    # Игрок 3 (ненадежный) пытается присоединиться - должна быть ошибка
    req3 = FindPartnerRequest(
        tg_id=333333,
        nickname="Ненадежный",
        stake=1000,
        capacity=3,
        reliable_only=True
    )
    
    with pytest.raises(Exception) as exc_info:
        await find_players(req3, fake_session, fake_redis)
    
    # Проверяем, что ошибка содержит информацию о надежности
    error_msg = str(exc_info.value).lower()
    assert "надеж" in error_msg or "reliable" in error_msg or "лив" in error_msg
    print("✅ Тест: ненадежный игрок заблокирован в reliable_only комнате")


@pytest.mark.asyncio
async def test_reliable_only_allows_reliable_players(
    fake_session: AsyncSession,
    fake_redis: CustomRedis,
    test_users_with_reliability
):
    """
    Тест: Надежные игроки могут входить в комнату с reliable_only=True.
    Сценарий:
    1. Создаётся комната с reliable_only=True
    2. Два надежных игрока присоединяются успешно
    """
    user1, user2, user3 = test_users_with_reliability
    
    # Игрок 1 (надежный) создаёт комнату
    req1 = FindPartnerRequest(
        tg_id=111111,
        nickname="Надежный 1",
        stake=1000,
        capacity=2,
        reliable_only=True
    )
    response1 = await find_players(req1, fake_session, fake_redis)
    room_id = response1.room_id
    
    # Игрок 2 (надежный) присоединяется успешно
    req2 = FindPartnerRequest(
        tg_id=222222,
        nickname="Надежный 2",
        stake=1000,
        capacity=2,
        reliable_only=True
    )
    response2 = await find_players(req2, fake_session, fake_redis)
    assert response2.room_id == room_id
    assert response2.status == "matched"
    
    print("✅ Тест: надежные игроки могут входить в reliable_only комнату")


@pytest.mark.asyncio
async def test_reliable_only_not_enforced_for_normal_rooms(
    fake_session: AsyncSession,
    fake_redis: CustomRedis,
    test_users_with_reliability
):
    """
    Тест: В обычных комнатах (reliable_only=False) все игроки могут войти.
    Сценарий:
    1. Создаётся обычная комната
    2. Ненадежный игрок может присоединиться
    """
    user1, user2, user3 = test_users_with_reliability
    
    # Игрок 1 создаёт обычную комнату (без reliable_only)
    req1 = FindPartnerRequest(
        tg_id=111111,
        nickname="Игрок 1",
        stake=1000,
        capacity=2,
        reliable_only=False
    )
    response1 = await find_players(req1, fake_session, fake_redis)
    room_id = response1.room_id
    
    # Ненадежный игрок может присоединиться в обычную комнату
    req3 = FindPartnerRequest(
        tg_id=333333,
        nickname="Ненадежный",
        stake=1000,
        capacity=2,
        reliable_only=False
    )
    response3 = await find_players(req3, fake_session, fake_redis)
    assert response3.room_id == room_id  # Успешно присоединился
    assert response3.status == "matched"
    
    print("✅ Тест: в обычных комнатах все игроки могут входить")


@pytest.mark.asyncio
async def test_reliable_only_matching_only_reliable_rooms(
    fake_session: AsyncSession,
    fake_redis: CustomRedis,
    test_users_with_reliability
):
    """
    Тест: Поиск комнаты учитывает reliable_only режим.
    Сценарий:
    1. Создаётся комната с reliable_only=True
    2. Ненадежный игрок с reliable_only=True ищет комнату
    3. Он должен создать новую комнату, а не присоединиться к существующей
    """
    user1, user2, user3 = test_users_with_reliability
    
    # Игрок 1 (надежный) создаёт комнату с reliable_only
    req1 = FindPartnerRequest(
        tg_id=111111,
        nickname="Надежный 1",
        stake=1000,
        capacity=2,
        reliable_only=True
    )
    response1 = await find_players(req1, fake_session, fake_redis)
    room_id1 = response1.room_id
    
    # Ненадежный игрок с reliable_only=True ищет комнату
    # Он не должен присоединиться к существующей, а создать новую
    req3 = FindPartnerRequest(
        tg_id=333333,
        nickname="Ненадежный",
        stake=1000,
        capacity=2,
        reliable_only=True
    )
    
    # Должен быть заблокирован при попытке присоединиться к существующей комнате
    with pytest.raises(Exception) as exc_info:
        await find_players(req3, fake_session, fake_redis)
    
    # Проверяем, что ошибка содержит информацию о надежности
    error_msg = str(exc_info.value).lower()
    assert "надеж" in error_msg or "reliable" in error_msg or "лив" in error_msg
    print("✅ Тест: ненадежный игрок заблокирован при поиске reliable_only комнаты")

