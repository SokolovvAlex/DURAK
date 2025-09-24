import pytest
import fakeredis.aioredis
from unittest.mock import AsyncMock
import json
from app.game.api.router import find_players
from app.game.api.schemas import FindPartnerRequest


@pytest.mark.asyncio
async def test_find_player_sends_new_room_and_close_room(monkeypatch):
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.game.redis_dao.manager.get_redis", lambda: fake_redis)

    sent_messages = []
    async def fake_send_msg(event, payload, channel_name):
        print(f"[CENTRIFUGO] event={event}, payload={payload}, channel={channel_name}")
        sent_messages.append({"event": event, "payload": payload, "channel": channel_name})
    monkeypatch.setattr("app.game.api.router.send_msg", fake_send_msg)

    # Мокаем UserDAO.find_one_or_none
    fake_user = type("U", (), {"balance": 100})()
    async def fake_find_one_or_none(session, **kwargs):
        return fake_user
    monkeypatch.setattr("app.users.dao.UserDAO.find_one_or_none", fake_find_one_or_none)

    session = AsyncMock()

    # --- Первый игрок создаёт комнату ---
    req1 = FindPartnerRequest(tg_id=1, nickname="alice", stake=10)
    await find_players(req1, session, fake_redis)

    keys = await fake_redis.keys("10_*")
    print(f"[DEBUG] Redis keys after first player: {keys}")
    raw_room = await fake_redis.get(keys[0])
    print(f"[DEBUG] Room data: {raw_room}")

    assert any(m["event"] == "new_room" for m in sent_messages), "Ожидалось событие new_room"

    # --- Второй игрок присоединяется ---
    req2 = FindPartnerRequest(tg_id=2, nickname="bob", stake=10)
    # тут room_id передадим напрямую, а не в модель
    await find_players(req2, session, fake_redis)

    print(f"[DEBUG] Messages sent: {sent_messages}")

    assert any(m["event"] == "close_room" for m in sent_messages), "Ожидалось событие close_room"
