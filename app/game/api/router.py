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
from app.game.api.utils import send_msg, get_all_rooms, _is_waiting, card_points, can_beat, can_defend_all
from app.game.core.burkozel import Burkozel
from app.game.core.constants import CARDS_IN_HAND_MAX, DECK, NAME_TO_VALUE
# from app.game.core.burkozel import Durak
from app.game.redis_dao.custom_redis import CustomRedis
from app.game.redis_dao.manager import get_redis
from app.payments.dao import TransactionDAO
from app.users.dao import UserDAO

router = APIRouter(prefix="/burkozel", tags=["Burkozel"])


@router.post("/find_player", response_model=FindPartnerResponse)
async def find_players(
    req: FindPartnerRequest,
    session: SessionDep,
    redis: CustomRedis = Depends(get_redis)
):
    """
    Поиск комнаты по ставке:
    - если есть "waiting" → присоединяемся как игрок
    - если нет → создаём новую
    """

    if req.stake <= 0:
        raise HTTPException(status_code=400, detail="Невозможно создать комнату с ставкой о")


    # проверяем баланс игрока
    user = await UserDAO.find_one_or_none(session, **{"tg_id": req.tg_id})
    if not user:
        raise HTTPException(status_code=404, detail="Игрок не найден в базе")
    if user.balance < req.stake:
        raise HTTPException(status_code=400, detail="Недостаточно средств для игры")

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

        await send_msg(
            event="close_room",
            payload={"room_id": req.room_id},
            channel_name="rooms"
        )

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

    # после создания новой комнаты
    await send_msg(
        "new_room",
        {
            "room": room_data
        },
        channel_name="rooms",  # общий канал для всех игроков
    )

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
            "last_turn": {"attack": None, "defend": None},  # новое поле
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
                "last_turn": room["last_turn"],
            },
            channel_name=f"room#{req.room_id}",
        )

    return {"ok": True}



@router.post("/move")
async def move(
    session: SessionDep,
    req: MoveRequest,
    redis: CustomRedis = Depends(get_redis)
):
    """
    Обработка хода игрока.
    • Если поле пустое -> атака.
    • Если поле уже есть -> защита.
    • После защиты:
        - определяем победителя раздачи,
        - начисляем очки,
        - очищаем поле,
        - добор карт по одной, пока у игроков не будет по 4.
        - проверка конца игры или пересдача
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
        suits = {c[1] for c in cards}
        if len(suits) != 1:
            raise HTTPException(
                status_code=400,
                detail="Можно ходить только картами одной масти или комбинацией"
            )

        for c in cards:
            hand.remove(list(c))

        field["attack"] = {"player": str(req.tg_id), "cards": [list(c) for c in cards]}
        field["defend"] = None
        field["winner"] = None

        # сохраняем последний ход
        room["last_turn"] = {
            "attack": {"player": str(req.tg_id), "cards": [list(c) for c in cards]},
            "defend": None
        }

        logger.info(f"[MOVE] Игрок {req.tg_id} атаковал {cards}")

    # ========================
    # защита
    # ========================
    else:
        if str(req.tg_id) == attacker:
            raise HTTPException(
                status_code=400,
                detail="Атакующий не может защищаться"
            )

        atk_cards = [tuple(c) for c in field["attack"]["cards"]]
        if len(cards) != len(atk_cards):
            raise HTTPException(
                status_code=400,
                detail="Количество карт для защиты должно совпадать с атакой"
            )

        beats_all = can_defend_all(atk_cards, cards, trump)

        for c in cards:
            hand.remove(list(c))

        field["defend"] = {"player": str(req.tg_id), "cards": [list(c) for c in cards]}

        # определяем победителя
        winner = str(req.tg_id) if beats_all else field["attack"]["player"]
        field["winner"] = winner

        # обновляем последний ход
        room["last_turn"] = {
            "attack": field["attack"],
            "defend": {"player": str(req.tg_id), "cards": [list(c) for c in cards]}
        }

        logger.info(f"[MOVE] Победитель раздачи: {winner}")

        # начисляем очки
        taken_cards = atk_cards + cards
        points = sum(card_points(c) for c in taken_cards)
        players[str(winner)]["round_score"] += points

        # очищаем поле
        room["field"] = {"attack": None, "defend": None, "winner": None}

        # print(deck)
        # print(all(len(p["hand"]) == 0 for p in players.values()))

        if not deck and all(len(p["hand"]) == 0 for p in players.values()):
            MAX_PENALTY = 2
            scores_round = {pid: pdata["round_score"] for pid, pdata in players.items()}
            max_score = max(scores_round.values())

            # начисляем штрафные очки по правилам Буркозла
            for pid, score in scores_round.items():
                if score == max_score:
                    penalty = 0
                elif score > 31:
                    penalty = 2
                elif score > 0:
                    penalty = 4
                else:  # score == 0
                    penalty = 6

                players[pid]["penalty"] += penalty
                logger.info(f"[PENALTY] {pid} получил {penalty}, всего {players[pid]['penalty']}")

            # print(any(pdata["penalty"] >= MAX_PENALTY for pdata in players.values()))
            # проверяем лимит штрафов
            if any(pdata["penalty"] >= MAX_PENALTY for pdata in players.values()):
                game_winner = min(players.keys(), key=lambda pid: players[pid]["penalty"])
                game_loser = max(players.keys(), key=lambda pid: players[pid]["penalty"])

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
                        "last_turn": room["last_turn"],
                    },
                    channel_name=f"room#{req.room_id}",
                )

                await redis.unlink(req.room_id)

                await send_msg(
                    event="close_room",
                    payload={"room_id": req.room_id},
                    channel_name="rooms"
                )

                return {"ok": True, "message": "Игра завершена", "balances": balances}

            else:
                # пересдаём новую партию
                from app.game.core.constants import DECK
                deck = list(DECK)
                random.shuffle(deck)

                for pid, pdata in players.items():
                    pdata["hand"] = deck[:4]
                    deck = deck[4:]
                    pdata["round_score"] = 0  # сброс очков партии, penalty сохраняем

                trump = deck[0][1]
                room.update({
                    "deck": deck,
                    "trump": trump,
                    "field": {"attack": None, "defend": None, "winner": None},
                    "attacker": list(players.keys())[0],
                    "status": "playing"
                })

                await redis.set(req.room_id, json.dumps(room))
                await send_msg(
                    "reshuffle",
                    {"room": room, "trump": trump, "deck_count": len(deck), "last_turn": room["last_turn"]},
                    channel_name=f"room#{req.room_id}",
                )
                return {"ok": True, "message": "Колода пересдана, новая партия", "room": room}

        # ========================
        # если колода ещё есть → добор карт
        # ========================
        else:
            order = [winner] + [pid for pid in players.keys() if pid != winner]

            # будем накапливать новые карты для каждого игрока
            new_cards_by_player = {pid: [] for pid in order}

            # раздаём карты по одной за круг
            while deck and any(len(players[pid]["hand"]) < 4 for pid in order):
                for pid in order:
                    if deck and len(players[pid]["hand"]) < 4:
                        card = deck.pop(0)
                        players[pid]["hand"].append(card)
                        new_cards_by_player[pid].append(card)
                        logger.debug(f"[MOVE] Игрок {pid} добрал {card}")

            # теперь отправляем уведомления только один раз для каждого игрока
            for pid, new_cards in new_cards_by_player.items():
                if new_cards:  # если реально были выданы карты
                    await send_msg(
                        event="hand",
                        payload={
                            "new_cards": new_cards,
                            "trump": trump,
                            "deck_count": len(deck),
                            "attacker": room["attacker"],
                        },
                        channel_name=f"user#{pid}",
                    )

        room["attacker"] = winner
    # сохраняем изменения
    players[str(req.tg_id)]["hand"] = hand
    room["players"] = players
    room["deck"] = deck
    await redis.set(req.room_id, json.dumps(room))

    await send_msg(event="move", payload={"room": room,
                                          "last_turn": room["last_turn"],
                                          }, channel_name=f"room#{req.room_id}")

    return {"ok": True, "room": room}



@router.post("/leave")
async def leave(
    req: ReadyRequest,
    session: SessionDep,
    redis: CustomRedis = Depends(get_redis),
):
    """
    Игрок выходит из комнаты.
    • Если игра не началась (is_ready=False) → просто убираем игрока.
    • Если игра идёт → игрок считается проигравшим, игра завершается.
    После окончания игра сбрасывается: руки/колода пустые, is_ready=False, status="waiting".
    """
    logger.info(f"[LEAVE] room_id={req.room_id}, tg_id={req.tg_id}")

    raw = await redis.get(req.room_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    room = json.loads(raw)

    players = room.get("players", {})
    player = players.get(str(req.tg_id))
    if not player:
        raise HTTPException(status_code=404, detail="Игрок не найден в комнате")

    # случай 1: игрок еще не нажал ready
    if not player.get("is_ready", False):
        logger.info(f"[LEAVE] Игрок {req.tg_id} вышел до начала игры")
        del players[str(req.tg_id)]

        # если игроки остались → комната ждет
        if players:
            room["players"] = players
            room["status"] = "waiting"
            await redis.set(req.room_id, json.dumps(room))

            await send_msg(
                "new_room",
                {"room": room},
                channel_name="rooms",
            )
        else:
            # если игроков нет → очищаем комнату
            room.update({
                "deck": [],
                "field": {"attack": None, "defend": None, "winner": None},
                "last_turn": {"attack": None, "defend": None},  # сброс последнего хода
                "attacker": None,
                "status": "waiting",
                "players": players
            })
            await redis.set(req.room_id, json.dumps(room))
            await send_msg(
                "close_room",
                {"room_id": req.room_id},
                channel_name="rooms",
            )

        return {"ok": True, "message": "Игрок вышел из комнаты"}

    # случай 2: игра уже идёт → игрок считается проигравшим
    else:
        logger.info(f"[LEAVE] Игрок {req.tg_id} вышел во время игры (проигрыш)")

        # определяем второго игрока
        opponent_id = [pid for pid in players.keys() if pid != str(req.tg_id)][0]

        from app.payments.dao import TransactionDAO
        dao = TransactionDAO(session)
        balances = await dao.apply_game_result(
            winner_id=int(opponent_id),
            loser_id=int(req.tg_id),
            stake=room["stake"],
        )
        await session.commit()

        # уведомляем игроков
        await send_msg(
            event="game_over",
            payload={
                "room_id": req.room_id,
                "winner": opponent_id,
                "loser": str(req.tg_id),
                "stake": room["stake"],
                "balances": balances,
            },
            channel_name=f"room#{req.room_id}",
        )

        # сбрасываем комнату
        for pid, pdata in players.items():
            pdata["hand"] = []
            pdata["round_score"] = 0
            pdata["penalty"] = 0
            pdata["is_ready"] = False

        room["deck"] = []
        room["field"] = {"attack": None, "defend": None, "winner": None}
        room["attacker"] = None
        room["status"] = "waiting"
        room["players"] = players

        await redis.set(req.room_id, json.dumps(room))

        await send_msg(
            "close_room",
            {"room_id": req.room_id},
            channel_name="rooms",
        )

        return {
            "ok": True,
            "winner": opponent_id,
            "loser": str(req.tg_id),
            "balances": balances,
            "message": "Игра завершена, игрок вышел",
        }


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


@router.post("/join_room")
async def join_room(
    session: SessionDep,
    room_id: str = Body(...),
    tg_id: int = Body(...),
    nickname: str = Body(...),
    redis: CustomRedis = Depends(get_redis),
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

    # проверяем баланс игрока
    user = await UserDAO.find_one_or_none(session, **{"tg_id": tg_id})
    if not user:
        raise HTTPException(status_code=404, detail="Игрок не найден в базе")
    if user.balance < room["stake"]:
        raise HTTPException(status_code=400, detail="Недостаточно средств для игры")

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

    await send_msg(
        event="close_room",
        payload={"room_id": room_id},
        channel_name="rooms"
    )

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


@router.post("/clear_room/{room_id}")
async def clear_room(room_id: str, redis_client: CustomRedis = Depends(get_redis)):
    # Асинхронно удаляем ключ, связанный с room_id
    await redis_client.unlink(room_id)

    await send_msg(
        event="close_room",
        payload={"room_id": room_id},
        channel_name="rooms"
    )
    return {"status": "ok", "message": f"Ключ для комнаты {room_id} удален"}


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
                "hand": [["A","♣"],["Q","♥"],["K","♠"],["8","♠"]],
                "round_score": 0,
                "penalty": 0
            }
        },
        "deck": [["A","♦"],["K","♥"]],
        "trump": trump,
        "field": {"attack": None, "defend": None, "winner": None},
        "last_turn": {"attack": None, "defend": None},
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
                "penalty": 0
            }
        },
        "deck": [],  # колода пуста — игра должна закончиться
        "trump": trump,
        "field": {"attack": None, "defend": None, "winner": None},
        "last_turn": {"attack": None, "defend": None},
        "attacker": "7022782558"  # Саша начинает
    }

    await redis.set(room_id, json.dumps(room))
    logger.info(f"[TEST] Создана тестовая 'последняя раздача' {room_id}")

    return {"ok": True, "room": room}



@router.post("/clear_redis")
async def clear_redis(redis_client: CustomRedis = Depends(get_redis)):
    # Очищаем все ключи из Redis
    await redis_client.flushdb()
    return {"message": "Redis база данных очищена"}


@router.get("/room/{room_id}")
async def current_room(
     room_id: str, redis_client: CustomRedis = Depends(get_redis)
):
    # Получаем данные о комнате из Redis
    room_data = await redis_client.get(room_id)
    if not room_data:
        raise HTTPException(status_code=404, detail="Комната не найдена")

    room_info = json.loads(room_data)
    return room_info
