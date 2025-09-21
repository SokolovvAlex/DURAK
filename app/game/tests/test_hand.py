import pytest
import fakeredis.aioredis
from unittest.mock import AsyncMock

from app.game.api.router import move
from app.game.api.schemas import MoveRequest


@pytest.mark.asyncio
async def test_move_gives_new_cards_and_sends_event(monkeypatch):
    # --- Подготовка фейкового Redis ---
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    # --- Мокаем send_msg (Centrifugo) ---
    sent_messages = []

    async def fake_send_msg(event, payload, channel_name):
        sent_messages.append({"event": event, "payload": payload, "channel": channel_name})

    monkeypatch.setattr("app.game.api.router.send_msg", fake_send_msg)

    # --- Создаём комнату ---
    room_id = "test_room"
    room = {
        "room_id": room_id,
        "stake": 10,
        "status": "playing",
        "players": {
            "1": {"nickname": "alice", "is_ready": True, "hand": [["7", "♥"]], "round_score": 0, "penalty": 0},
            "2": {"nickname": "bob", "is_ready": True, "hand": [["8", "♥"]], "round_score": 0, "penalty": 0},
        },
        "deck": [["9", "♦"], ["J", "♣"], ["10", "♠"], ["Q", "♣"]],
        "trump": "♦",
        "field": {"attack": None, "defend": None, "winner": None},
        "last_turn": {"attack": None, "defend": None},
        "attacker": "1",
    }
    await fake_redis.set(room_id, __import__("json").dumps(room))

    # --- Эмуляция атаки от Alice ---
    req = MoveRequest(room_id=room_id, tg_id=1, cards=[["7", "♥"]])
    session = AsyncMock()
    await move(session, req, fake_redis)

    # Проверяем что карта ушла из руки Alice
    updated = await fake_redis.get(room_id)
    updated_room = __import__("json").loads(updated)
    assert ["7", "♥"] not in updated_room["players"]["1"]["hand"]

    # Проверяем, что ушло событие move
    move_msgs = [m for m in sent_messages if m["event"] == "move"]
    assert move_msgs
    assert move_msgs[0]["payload"]["room"]["last_turn"]["attack"]["player"] == "1"

    # --- Эмуляция защиты от Bob ---
    req2 = MoveRequest(room_id=room_id, tg_id=2, cards=[["8", "♥"]])
    await move(session, req2, fake_redis)

    # Проверяем, что Bob получил новые карты
    hand_msgs = [m for m in sent_messages if m["event"] == "hand"]
    assert hand_msgs, "Ожидалось событие hand"
    first_hand_msg = hand_msgs[0]["payload"]

    assert "new_cards" in first_hand_msg
    assert isinstance(first_hand_msg["new_cards"], list)
    assert all(isinstance(card, list) for card in first_hand_msg["new_cards"])
