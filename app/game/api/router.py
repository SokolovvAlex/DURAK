# import json
import json
import uuid
from datetime import datetime
import random

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from app.database import SessionDep
from app.game.api.schemas import FindPartnerResponse, FindPartnerRequest, ReadyResponse, ReadyRequest, MoveRequest
from app.game.api.utils import send_msg, get_all_rooms
from app.game.core.burkozel import Burkozel
from app.game.core.constants import CARDS_IN_HAND_MAX, DECK, NAME_TO_VALUE
# from app.game.core.burkozel import Durak
from app.game.redis_dao.custom_redis import CustomRedis
from app.game.redis_dao.manager import get_redis
from app.users.dao import UserDAO

router = APIRouter(prefix="/durak", tags=["DURAK"])


@router.post("/find_player", response_model=FindPartnerResponse)
async def find_players(
    req: FindPartnerRequest,
    redis: CustomRedis = Depends(get_redis)
):
    """
    Поиск комнаты по ставке:
    - если есть "waiting" → присоединяемся как игрок
    - если нет → создаём новую
    """
    keys = await redis.keys(f"{req.stake}_*")
    room = None

    if keys:
        for key in keys:
            raw = await redis.get(key)
            if raw:
                room_data = json.loads(raw)
                if room_data.get("status") == "waiting":
                    room = room_data
                    break

    if room:  # нашли комнату
        room_id = room["room_id"]
        room["players"][str(req.tg_id)] = {
            "nickname": req.nickname,
            "is_ready": False,
        }
        room["status"] = "matched"
        await redis.set(room_id, json.dumps(room))

        opponent = next(
            p["nickname"] for uid, p in room["players"].items() if int(uid) != req.tg_id
        )
        logger.info(f"Игрок {req.tg_id} присоединился к комнате {room_id}")

        return FindPartnerResponse(
            room_id=room_id,
            status="matched",
            message="Игрок найден",
            stake=req.stake,
            opponent=opponent,
        )

    # создаём новую
    room_id = f"{req.stake}_{uuid.uuid4().hex[:8]}"
    room_data = {
        "room_id": room_id,
        "stake": req.stake,
        "created_at": datetime.utcnow().isoformat(),
        "status": "waiting",
        "players": {
            str(req.tg_id): {
                "nickname": req.nickname,
                "is_ready": False,
            }
        },
    }
    await redis.set(room_id, json.dumps(room_data))
    logger.info(f"Создана новая комната {room_id} пользователем {req.tg_id}")

    return FindPartnerResponse(
        room_id=room_id,
        status="waiting",
        message="Ожидание второго игрока",
        stake=req.stake,
    )


@router.post("/ready")
async def ready(req: ReadyRequest, redis=Depends(get_redis)):
    logger.info(f"[READY] tg_id={req.tg_id}, room_id={req.room_id}")

    raw = await redis.get(req.room_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    room = json.loads(raw)

    players = room.get("players", {})
    player = players.get(str(req.tg_id))
    if not player:
        raise HTTPException(status_code=404, detail="Игрок не найден в комнате")

    player["is_ready"] = True
    room["players"] = players
    await redis.set(req.room_id, json.dumps(room))

    # если все готовы → старт
    if all(p["is_ready"] for p in players.values()) and "deck" not in room:
        logger.info("[READY] Все игроки готовы, стартуем!")

        deck = list(DECK)
        random.shuffle(deck)

        for tg_id, pdata in players.items():
            hand = deck[:4]  # в Буркозле 4 карты на старте
            deck = deck[4:]
            pdata["hand"] = hand
            pdata["round_score"] = 0
            pdata["penalty"] = 0
            logger.debug(f"[READY] {tg_id} ({pdata['nickname']}) получил {hand}")

        trump = deck[0][1]
        room.update({
            "deck": deck,
            "trump": trump,
            "field": {"attack": None, "defend": None, "winner": None},
            "attacker": list(players.keys())[0],
            "status": "playing"
        })
        await redis.set(req.room_id, json.dumps(room))

        for tg_id, pdata in players.items():
            await send_msg(
                "hand",
                {
                    "hand": pdata["hand"],
                    "trump": trump,
                    "deck_count": len(deck),
                    "attacker": room["attacker"],
                },
                channel_name=f"user#{tg_id}",
            )

        await send_msg(
            "game_start",
            {
                "room_id": req.room_id,
                "trump": trump,
                "deck_count": len(deck),
                "attacker": room["attacker"],
            },
            channel_name=f"room#{req.room_id}",
        )

    return {"ok": True}



@router.post("/move")
async def move(req: MoveRequest, redis: CustomRedis = Depends(get_redis)):
    """
    Обработка хода игрока (атака или защита).
    Вход:
      - room_id
      - tg_id
      - cards: список карт [["10","♣"],["8","♣"]]

    Логика:
      • если поле пустое -> атака
      • если поле уже есть -> защита
      • после раздачи — определяем победителя взятки, начисляем очки
      • добор карт по одной (сначала победитель, потом проигравший)
    """
    logger.info(f"[MOVE] room_id={req.room_id}, tg_id={req.tg_id}, cards={req.cards}")

    raw = await redis.get(req.room_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    room = json.loads(raw)

    players = room["players"]
    field = room["field"]
    trump = room["trump"]
    deck = room["deck"]
    attacker = room["attacker"]

    # проверка игрока
    player = players.get(str(req.tg_id))
    if not player:
        raise HTTPException(status_code=404, detail="Игрок не найден в комнате")

    hand = player["hand"]
    cards = [tuple(c) for c in req.cards]

    # проверяем что карты есть в руке
    for c in cards:
        if list(c) not in hand:
            raise HTTPException(status_code=400, detail=f"Карты {c} нет в руке")

    # ========================
    # атака
    # ========================
    if field["attack"] is None:
        # в атаке можно только одной мастью или комбинацией
        suits = {c[1] for c in cards}
        if len(suits) != 1:
            raise HTTPException(status_code=400, detail="Можно ходить только картами одной масти или комбинацией")

        # убираем карты из руки
        for c in cards:
            hand.remove(list(c))

        # сохраняем атаку
        field["attack"] = {"player": req.tg_id, "cards": [list(c) for c in cards]}
        field["defend"] = None
        field["winner"] = None

        logger.info(f"[MOVE] Игрок {req.tg_id} атаковал {cards}")

    # ========================
    # защита
    # ========================
    else:
        if str(req.tg_id) == attacker:
            raise HTTPException(status_code=400, detail="Атакующий не может защищаться")

        atk_cards = [tuple(c) for c in field["attack"]["cards"]]
        if len(cards) != len(atk_cards):
            raise HTTPException(status_code=400, detail="Количество карт для защиты должно совпадать с атакой")

        # проверка побития
        beats_all = True
        for atk, dfn in zip(atk_cards, cards):
            if not can_beat(atk, dfn, trump):
                beats_all = False
                break

        # убираем карты из руки
        for c in cards:
            hand.remove(list(c))

        # сохраняем защиту
        field["defend"] = {"player": req.tg_id, "cards": [list(c) for c in cards]}

        if beats_all:
            winner = req.tg_id
        else:
            winner = field["attack"]["player"]

        field["winner"] = winner
        logger.info(f"[MOVE] Победитель раздачи: {winner}")

        # начисляем очки победителю
        taken_cards = atk_cards + cards
        points = sum(card_points(c) for c in taken_cards)
        players[str(winner)]["round_score"] += points

        # добор карт по одной: сначала победитель, потом проигравший
        order = [str(winner)] + [pid for pid in players.keys() if int(pid) != winner]
        for pid in order:
            if deck and len(players[pid]["hand"]) < 6:
                card = deck.pop(0)
                players[pid]["hand"].append(card)
                logger.debug(f"[MOVE] Игрок {pid} добрал карту {card}")

        # следующий атакующий = победитель
        room["attacker"] = str(winner)

        # очищаем поле
        room["field"] = {"attack": None, "defend": None, "winner": None}

    # сохраняем
    players[str(req.tg_id)]["hand"] = hand
    room["players"] = players
    room["deck"] = deck
    room["field"] = field
    await redis.set(req.room_id, json.dumps(room))

    # уведомляем игроков
    await send_msg(
        event="move",
        payload={"room": room},
        channel_name=f"room#{req.room_id}",
    )

    return {"ok": True, "room": room}


# ========================
# Вспомогательные функции
# ========================

def card_points(card):
    """Очки карты"""
    from app.game.core.constants import CARD_POINTS
    return CARD_POINTS.get(card[0], 0)


def can_beat(atk, dfn, trump):
    """Можно ли побить карту atk картой dfn"""
    from app.game.core.constants import NAME_TO_VALUE
    n1, s1 = atk
    n2, s2 = dfn
    if s1 == s2:
        return NAME_TO_VALUE[n2] > NAME_TO_VALUE[n1]
    if s2 == trump and s1 != trump:
        return True
    return False


@router.get("/rooms")
async def list_rooms(redis: CustomRedis = Depends(get_redis)):
    """Получить список всех комнат."""
    rooms = await get_all_rooms(redis)
    return {"count": len(rooms), "rooms": rooms}


@router.post("/clear_room/{room_id}")
async def clear_room(room_id: str, redis_client: CustomRedis = Depends(get_redis)):
    # Асинхронно удаляем ключ, связанный с room_id
    await redis_client.unlink(room_id)
    return {"status": "ok", "message": f"Ключ для комнаты {room_id} удален"}


@router.post("/clear_redis")
async def clear_redis(redis_client: CustomRedis = Depends(get_redis)):
    # Очищаем все ключи из Redis
    await redis_client.flushdb()
    return {"message": "Redis база данных очищена"}


@router.post("/create_test_room")
async def create_test_room(redis: CustomRedis = Depends(get_redis)):
    room_id = f"10_{uuid.uuid4().hex[:8]}"
    trump = "♦"

    room = {
        "room_id": room_id,
        "stake": 10,
        "created_at": datetime.utcnow().isoformat(),
        "status": "matched",
        "players": {
            "7022782558": {
                "nickname": "sasha",
                "is_ready": True,
                "hand": [["7","♠"],["J","♠"],["8","♣"],["6","♥"]],
                "round_score": 0,
                "penalty": 0
            },
            "5254325840": {
                "nickname": "ed",
                "is_ready": True,
                "hand": [["A","♣"],["Q","♥"],["10","♠"],["8","♥"]],
                "round_score": 0,
                "penalty": 0
            }
        },
        "deck": [["A","♦"],["K","♥"],["Q","♣"],["9","♠"]],
        "trump": trump,
        "field": {"attack": None, "defend": None, "winner": None},
        "attacker": "7022782558"
    }

    await redis.set(room_id, json.dumps(room))
    logger.info(f"[TEST] Создана тестовая комната {room_id}")

    return {"ok": True, "room": room}
