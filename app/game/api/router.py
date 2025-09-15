# import json
import json
import uuid
from datetime import datetime
import random
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from loguru import logger

from app.database import SessionDep
from app.game.api.schemas import FindPartnerResponse, FindPartnerRequest, ReadyResponse, ReadyRequest, MoveRequest
from app.game.api.utils import send_msg, get_all_rooms, _is_waiting, card_points, can_beat
from app.game.core.burkozel import Burkozel
from app.game.core.constants import CARDS_IN_HAND_MAX, DECK, NAME_TO_VALUE
# from app.game.core.burkozel import Durak
from app.game.redis_dao.custom_redis import CustomRedis
from app.game.redis_dao.manager import get_redis
from app.users.dao import UserDAO

router = APIRouter(prefix="/burkozel", tags=["Burkozel"])


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
async def move(session: SessionDep, req: MoveRequest, redis: CustomRedis = Depends(get_redis)):
    """
    Обработка хода игрока.
    • Если поле пустое -> атака.
    • Если поле уже есть -> защита.
    • После защиты:
        - определяем победителя раздачи,
        - начисляем очки,
        - очищаем поле,
        - добираем карты по одной, пока у игроков не будет по 4.
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
        # можно ходить только одной мастью или комбинацией
        suits = {c[1] for c in cards}
        if len(suits) != 1:
            raise HTTPException(status_code=400, detail="Можно ходить только картами одной масти или комбинацией")

        for c in cards:
            hand.remove(list(c))

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
        beats_all = all(can_beat(atk, dfn, trump) for atk, dfn in zip(atk_cards, cards))

        for c in cards:
            hand.remove(list(c))

        field["defend"] = {"player": req.tg_id, "cards": [list(c) for c in cards]}

        # определяем победителя
        if beats_all:
            winner = req.tg_id
        else:
            winner = field["attack"]["player"]

        field["winner"] = winner
        logger.info(f"[MOVE] Победитель раздачи: {winner}")

        # начисляем очки
        taken_cards = atk_cards + cards
        points = sum(card_points(c) for c in taken_cards)
        players[str(winner)]["round_score"] += points

        # очищаем поле
        room["field"] = {"attack": None, "defend": None, "winner": None}

        # добор карт по одной
        order = [str(winner)] + [pid for pid in players.keys() if pid != str(winner)]
        for pid in order:
            while deck and len(players[pid]["hand"]) < 4:
                card = deck.pop(0)
                players[pid]["hand"].append(card)
                logger.debug(f"[MOVE] Игрок {pid} добрал {card}")

        # следующий атакующий = победитель
        room["attacker"] = str(winner)

        # ========================
        # проверка на конец игры
        # ========================
        if any(len(p["hand"]) == 0 for p in players.values()):
            from app.payments.dao import TransactionDAO

            # определяем победителя/проигравшего
            scores = {pid: pdata["penalty"] for pid, pdata in players.items()}
            game_winner = min(scores, key=scores.get)
            game_loser = max(scores, key=scores.get)

            dao = TransactionDAO(session)
            balances = await dao.apply_game_result(
                winner_id=int(game_winner),
                loser_id=int(game_loser),
                stake=room["stake"],
            )
            await session.commit()

            logger.info(f"[GAME_OVER] Победитель {game_winner}, проигравший {game_loser}")

            await send_msg(
                event="game_over",
                payload={
                    "room_id": req.room_id,
                    "winner": game_winner,
                    "loser": game_loser,
                    "stake": room["stake"],
                    "balances": balances,
                },
                channel_name=f"room#{req.room_id}",
            )

            await redis.delete(req.room_id)
            return {
                "ok": True,
                "winner": game_winner,
                "loser": game_loser,
                "balances": balances,
            }

        # сохраняем обновления
    players[str(req.tg_id)]["hand"] = hand
    room["players"] = players
    room["deck"] = deck
    await redis.set(req.room_id, json.dumps(room))

    # уведомляем игроков
    await send_msg(event="move", payload={"room": room}, channel_name=f"room#{req.room_id}")

    return {"ok": True, "room": room}


@router.get("/rooms")
async def list_rooms(
    redis: "CustomRedis" = Depends(get_redis),
    bet: Optional[int] = Query(None, description="Фильтр по ставке: ключи вида '<bet>_<id>'"),
):
    """
    Возвращает только комнаты, которые ожидают подключения.
    Если передан bet — ищем комнаты по ключам, начинающимся с '{bet}_'.
    Если bet не передан — используем общий сборщик get_all_rooms(redis).
    """
    try:
        if bet is not None:
            rooms = await redis.get_rooms_by_bet(bet)
        else:
            rooms = await get_all_rooms(redis)

        waiting = [r for r in rooms if _is_waiting(r)]
        return {"count": len(waiting), "rooms": waiting}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list rooms: {e}")


@router.post("/clear_room/{room_id}")
async def clear_room(room_id: str, redis_client: CustomRedis = Depends(get_redis)):
    # Асинхронно удаляем ключ, связанный с room_id
    await redis_client.unlink(room_id)
    return {"status": "ok", "message": f"Ключ для комнаты {room_id} удален"}


@router.post("/create_test_room")
async def create_test_room(redis: CustomRedis = Depends(get_redis)):
    """
    Создаёт тестовую комнату с полной колодой и раздачей по 4 карты каждому.
    """
    from app.game.core.constants import DECK
    deck = list(DECK)
    random.shuffle(deck)

    room_id = f"10_{uuid.uuid4().hex[:8]}"
    trump = deck[0][1]
    deck = deck[1:]  # убираем карту для козыря (но масть известна)

    # выдаём по 4 карты игрокам
    hand1, hand2 = deck[:4], deck[4:8]
    deck = deck[8:]

    room = {
        "room_id": room_id,
        "stake": 10,
        "created_at": datetime.utcnow().isoformat(),
        "status": "playing",
        "players": {
            "7022782558": {
                "nickname": "sasha",
                "is_ready": True,
                "hand": hand1,
                "round_score": 0,
                "penalty": 0
            },
            "5254325840": {
                "nickname": "ed",
                "is_ready": True,
                "hand": hand2,
                "round_score": 0,
                "penalty": 0
            }
        },
        "deck": deck,
        "trump": trump,
        "field": {"attack": None, "defend": None, "winner": None},
        "attacker": "7022782558"
    }

    await redis.set(room_id, json.dumps(room))
    logger.info(f"[TEST] Создана тестовая комната {room_id}")

    return {"ok": True, "room": room}


@router.post("/join_room")
async def join_room(
    room_id: str = Body(...),
    tg_id: int = Body(...),
    nickname: str = Body(...),
    redis: CustomRedis = Depends(get_redis)
):
    """
    Присоединение игрока к существующей комнате.
    """
    logger.info(f"[JOIN_ROOM] room_id={room_id}, tg_id={tg_id}, nickname={nickname}")

    raw = await redis.get(room_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    room = json.loads(raw)

    players = room.get("players", {})

    if str(tg_id) in players:
        raise HTTPException(status_code=400, detail="Игрок уже в комнате")

    if len(players) >= 2:
        raise HTTPException(status_code=400, detail="Комната уже заполнена")

    # Добавляем игрока
    players[str(tg_id)] = {
        "nickname": nickname,
        "is_ready": False,
        "hand": [],
        "round_score": 0,
        "penalty": 0,
    }

    room["players"] = players
    if len(players) == 2:
        room["status"] = "matched"

    await redis.set(room_id, json.dumps(room))

    # Уведомляем игроков через Centrifugo
    await send_msg(
        "player_joined",
        {
            "room_id": room_id,
            "player": {
                "tg_id": tg_id,
                "nickname": nickname,
            },
            "players": list(players.keys()),
            "status": room["status"],
        },
        channel_name=f"room#{room_id}",
    )

    return {"ok": True, "room": room}


@router.get("/all_rooms")
async def list_rooms(redis: CustomRedis = Depends(get_redis)):
    """Получить список всех комнат."""
    rooms = await get_all_rooms(redis)
    return {"count": len(rooms), "rooms": rooms}



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


@router.post("/create_last_hand_room")
async def create_last_hand_room(redis: CustomRedis = Depends(get_redis)):
    """
    Создаёт комнату с последней раздачей для проверки конца игры.
    Игрок Sasha (10 штрафных очков) против Ed (6 штрафных очков).
    """
    room_id = "10_071b017b"
    trump = "♦"

    room = {
        "room_id": room_id,
        "stake": 10,
        "created_at": datetime.utcnow().isoformat(),
        "status": "playing",
        "players": {
            "7022782558": {
                "nickname": "sasha",
                "is_ready": True,
                "hand": [["7", "♥"]],  # одна карта
                "round_score": 25,
                "penalty": 10
            },
            "5254325840": {
                "nickname": "ed",
                "is_ready": True,
                "hand": [["8", "♥"]],  # одна карта, старше
                "round_score": 28,
                "penalty": 6
            }
        },
        "deck": [],  # колода пуста — игра должна закончиться
        "trump": trump,
        "field": {"attack": None, "defend": None, "winner": None},
        "attacker": "7022782558"  # Саша начинает
    }

    await redis.set(room_id, json.dumps(room))
    logger.info(f"[TEST] Создана тестовая 'последняя раздача' {room_id}")

    return {"ok": True, "room": room}
