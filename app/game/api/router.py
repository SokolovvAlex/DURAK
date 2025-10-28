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
                # Матчим только ожидающие комнаты с совпадающими режимами и вместимостью
                if room_data.get("status") == "waiting":
                    if room_data.get("capacity", 2) != max(2, min(3, req.capacity)):
                        continue
                    if room_data.get("speed", "normal") != req.speed:
                        continue
                    if bool(room_data.get("redeal", False)) != bool(req.redeal):
                        continue
                    if bool(room_data.get("dark", False)) != bool(req.dark):
                        continue
                    if bool(room_data.get("reliable_only", False)) != bool(req.reliable_only):
                        continue
                    room = room_data
                    break

    if room:  # нашли подходящую комнату
        room_id = room["room_id"]
        # проверка на повторное подключение
        if str(req.tg_id) in room.get("players", {}):
            raise HTTPException(status_code=400, detail="Игрок уже в комнате")

        # проверка лимита вместимости
        if len(room.get("players", {})) >= room.get("capacity", 2):
            raise HTTPException(status_code=400, detail="Комната уже заполнена")

        room["players"][str(req.tg_id)] = {
            "nickname": req.nickname,
            "is_ready": False,
        }
        room["status"] = "matched" if len(room["players"]) >= room.get("capacity", 2) else "waiting"
        await redis.setex(room_id, 3600, json.dumps(room))

        await send_msg(
            event="close_room",
            payload={"room_id": room_id},
            channel_name="rooms"
        )

        opponent = next(
            p["nickname"] for uid, p in room["players"].items() if int(uid) != req.tg_id
        )
        logger.info(f"Игрок {req.tg_id} присоединился к комнате {room_id}")

        return FindPartnerResponse(
            room_id=room_id,
            status=room["status"],
            message="Игрок найден" if room["status"] == "matched" else "Ожидание игроков",
            stake=req.stake,
            capacity=room.get("capacity", 2),
            speed=room.get("speed", "normal"),
            redeal=bool(room.get("redeal", False)),
            dark=bool(room.get("dark", False)),
            reliable_only=bool(room.get("reliable_only", False)),
            opponent=opponent if room["status"] == "matched" else None,
        )

    # создаём новую
    room_id = f"{req.stake}_{uuid.uuid4().hex[:8]}"
    room_data = {
        "room_id": room_id,
        "stake": req.stake,
        "created_at": datetime.utcnow().isoformat(),
        "status": "waiting",
        "capacity": max(2, min(3, req.capacity)),
        "speed": req.speed,
        "redeal": bool(req.redeal),
        "dark": bool(req.dark),
        "reliable_only": bool(req.reliable_only),
        "players": {
            str(req.tg_id): {
                "nickname": req.nickname,
                "is_ready": False,
            }
        },
    }
    await redis.setex(room_id, 3600, json.dumps(room_data))
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
        message="Ожидание игроков",
        stake=req.stake,
        capacity=room_data["capacity"],
        speed=room_data["speed"],
        redeal=room_data["redeal"],
        dark=room_data["dark"],
        reliable_only=room_data["reliable_only"],
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
    await redis.setex(req.room_id, 3600, json.dumps(room))

    # если все готовы → старт
    if all(p["is_ready"] for p in players.values()) and "deck" not in room:
        logger.info("[READY] Все игроки готовы, стартуем!")

        deck = list(DECK)
        random.shuffle(deck)

        # Создаём фиксированный порядок игроков (seats)
        seats = list(players.keys())
        
        for tg_id, pdata in players.items():
            hand = deck[:4]  # в Буркозле 4 карты на старте
            deck = deck[4:]
            pdata["hand"] = hand
            pdata["round_score"] = 0
            pdata["penalty"] = 0
            pdata["taken_tricks"] = 0  # количество взяток в партии
            logger.debug(f"[READY] {tg_id} ({pdata['nickname']}) получил {hand}")

        trump = deck[0][1]
        room.update({
            "deck": deck,
            "trump": trump,
            "field": {"attack": None, "defend": None, "winner": None},
            "last_turn": {"attack": None, "defend": None, "turns": []},
            "seats": seats,  # фиксированный порядок игроков
            "attacker": seats[0],
            "defender": seats[1] if len(seats) > 1 else None,
            "turn_order": seats.copy(),  # для определения следующего
            "turns": [],  # список ходов текущего раунда
            "current_turn_idx": 0,  # индекс текущего хода
            "status": "playing"
        })
        await redis.setex(req.room_id, 3600, json.dumps(room))

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
    # ЛОГИКА ХОДА: Все игроки выкладывают карты, потом определяется победитель
    # ========================
    
    # Определяем порядок ходов
    seats = room.get("seats", list(players.keys()))
    
    # Фильтруем активных игроков (у кого < 12 штрафных очков)
    active_seats = [pid for pid in seats if players[pid]["penalty"] < 12]
    
    current_turn_idx = room.get("current_turn_idx", 0)
    turns = room.get("turns", [])  # список карт, выложенных на стол
    
    # Проверяем, что ходит правильный игрок (из активных)
    expected_player = active_seats[current_turn_idx % len(active_seats)] if active_seats else seats[current_turn_idx % len(seats)]
    if str(req.tg_id) != expected_player:
        raise HTTPException(
            status_code=400, 
            detail=f"Сейчас ход игрока {expected_player}, а не {req.tg_id}"
        )
    
    suits = {c[1] for c in cards}
    if len(suits) != 1:
        raise HTTPException(
            status_code=400,
            detail="Можно ходить только картами одной масти"
        )
    
    # Убираем карты из руки игрока
    for c in cards:
        hand.remove(list(c))
    
    # Добавляем ход в список
    turns.append({
        "player": str(req.tg_id),
        "cards": [list(c) for c in cards]
    })
    
    room["turns"] = turns
    room["current_turn_idx"] = current_turn_idx + 1
    
    logger.info(f"[MOVE] Игрок {req.tg_id} выложил {cards}. Всего ходов: {len(turns)}")
    
    # Проверяем, завершился ли раунд (все активные игроки выложили карты)
    if room["current_turn_idx"] >= len(active_seats):
        # Все игроки походили - определяем победителя
        logger.info("[MOVE] Все игроки походили, определяем победителя")
        
        # Находим старшую карту (по масти, затем по значению, учитывая козыри)
        winner_idx = 0
        winner_card = turns[0]["cards"][0]
        
        for i, turn in enumerate(turns):
            card = turn["cards"][0]
            
            # Проверяем, кто старше
            if card[1] == trump and winner_card[1] != trump:
                # Текущая карта козырь, а предыдущая нет - она выигрывает
                winner_idx = i
                winner_card = card
            elif card[1] == trump and winner_card[1] == trump:
                # Обе козыри - сравниваем значения
                from app.game.core.constants import NAME_TO_VALUE
                if NAME_TO_VALUE[card[0]] > NAME_TO_VALUE[winner_card[0]]:
                    winner_idx = i
                    winner_card = card
            elif card[1] == winner_card[1]:
                # Одна масть - сравниваем значения
                from app.game.core.constants import NAME_TO_VALUE
                if NAME_TO_VALUE[card[0]] > NAME_TO_VALUE[winner_card[0]]:
                    winner_idx = i
                    winner_card = card
        
        winner_id = turns[winner_idx]["player"]
        
        # Начисляем очки и взятки
        taken_cards = []
        for turn in turns:
            taken_cards.extend([tuple(c) for c in turn["cards"]])
        
        points = sum(card_points(c) for c in taken_cards)
        players[winner_id]["round_score"] += points
        players[winner_id]["taken_tricks"] += 1
        
        logger.info(f"[MOVE] Победитель раздачи: {winner_id}, очков: {points}")
        
        # Обновляем last_turn с информацией о завершённой взятке
        # Форматируем информацию для last_turn (совместимо со старой логикой)
        room["last_turn"] = {
            "attack": turns[0] if len(turns) > 0 else None,
            "defend": turns[1] if len(turns) > 1 else None,
            "turns": turns  # сохраняем все ходы
        }
        
        # Очищаем поле и сбрасываем индексы
        room["field"] = {"attack": None, "defend": None, "winner": None}
        room["turns"] = []
        room["current_turn_idx"] = 0
        winner = winner_id

        # print(deck)
        # print(all(len(p["hand"]) == 0 for p in players.values()))

        if not deck and all(len(p["hand"]) == 0 for p in players.values()):
            MAX_PENALTY = 12
            num_players = len(players)
            scores_round = {pid: pdata["round_score"] for pid, pdata in players.items()}
            max_score = max(scores_round.values())

            # начисляем штрафные очки по правилам Буркозла
            for pid, pdata in players.items():
                score = pdata["round_score"]
                tricks = pdata["taken_tricks"]
                
                if num_players == 2:
                    # Для двух игроков
                    if score > 60:
                        penalty = 0
                    elif score >= 31:
                        penalty = 2
                    elif score > 0:
                        penalty = 4
                    elif tricks > 0:  # 0 очков но со взятками
                        penalty = 4
                    else:  # 0 очков без взяток
                        penalty = 6
                else:  # Для трёх игроков
                    if score >= 40:
                        penalty = 0
                    elif score >= 21:
                        penalty = 2
                    elif score > 0:
                        penalty = 4
                    elif tricks > 0:  # 0 очков но со взятками
                        penalty = 4
                    else:  # 0 очков без взяток
                        penalty = 6

                players[pid]["penalty"] += penalty
                logger.info(f"[PENALTY] {pid} получил {penalty}, всего {players[pid]['penalty']}")

            # проверяем лимит штрафов
            losers = [pid for pid, pdata in players.items() if pdata["penalty"] >= MAX_PENALTY]
            
            if losers:
                # Игра закончена только если остался один игрок или никого
                remaining_players = {pid: pdata for pid, pdata in players.items() if pid not in losers}
                
                if len(remaining_players) <= 1:
                    # Остался один игрок или никого - игра закончена
                    if len(remaining_players) == 1:
                        game_winner = list(remaining_players.keys())[0]
                    else:
                        # Все выбыли - определяем победителя по минимальным штрафам
                        game_winner = min(players.keys(), key=lambda pid: players[pid]["penalty"])
                    
                    logger.info(f"[GAME_OVER] Победитель {game_winner}, проигравшие {losers}")
                    
                    dao = TransactionDAO(session)
                    
                    # Формируем детальную информацию о результатах
                    game_results = {}
                    for pid, pdata in players.items():
                        game_results[pid] = {
                            "nickname": pdata["nickname"],
                            "round_score": pdata["round_score"],
                            "penalty": pdata["penalty"],
                            "taken_tricks": pdata["taken_tricks"],
                            "is_winner": pid == game_winner,
                            "is_loser": pid in losers
                        }
                    
                    if len(players) == 2:
                        # Для двух игроков используем старый метод
                        balances = await dao.apply_game_result(
                            winner_id=int(game_winner),
                            loser_id=int(losers[0]),
                            stake=room["stake"],
                        )
                        balances["winner_result"] = players[game_winner]["penalty"]
                        balances["loser_result"] = players[losers[0]]["penalty"]
                    else:
                        # Для трёх и более игроков используем новый метод
                        balances = await dao.apply_game_result_multiplayer(
                            winner_id=int(game_winner),
                            loser_ids=[int(lid) for lid in losers],
                            stake=room["stake"],
                        )
                        balances["winner_result"] = players[game_winner]["penalty"]
                        balances["losers_result"] = {lid: players[lid]["penalty"] for lid in losers}
                    
                    await session.commit()

                    await send_msg(
                        event="game_over",
                        payload={
                            "room_id": req.room_id,
                            "winner": game_winner,
                            "losers": losers,
                            "stake": room["stake"],
                            "balances": balances,
                            "results": game_results,  # Детальная информация о всех игроках
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

                    return {
                        "ok": True, 
                        "message": "Игра завершена", 
                        "balances": balances,
                        "results": game_results
                    }
                
                else:
                    # Осталось несколько игроков - отправляем уведомление о выбывших
                    logger.info(f"[GAME] Игроки выбыли: {losers}, игра продолжается между {remaining_players.keys()}")
                    
                    # Отправляем уведомление о выбывших игроках
                    await send_msg(
                        event="players_out",
                        payload={
                            "room_id": req.room_id,
                            "losers": losers,
                            "remaining": list(remaining_players.keys()),
                            "last_turn": room["last_turn"],
                        },
                        channel_name=f"room#{req.room_id}",
                    )
                    
                    # Продолжаем игру - переходим к пересдаче

            # Пересдаём партию если не было проигравших ИЛИ есть несколько оставшихся игроков
            if not losers or (losers and len(remaining_players) > 1):
                # пересдаём новую партию
                from app.game.core.constants import DECK
                deck = list(DECK)
                random.shuffle(deck)

                # Определяем активных игроков (у кого < 12 штрафных)
                active_players = {pid: pdata for pid, pdata in players.items() if pdata["penalty"] < 12}
                
                # Раздаём карты только активным игрокам
                for pid, pdata in active_players.items():
                    pdata["hand"] = deck[:4]
                    deck = deck[4:]
                    pdata["round_score"] = 0  # сброс очков партии, penalty сохраняем
                    pdata["taken_tricks"] = 0  # сброс взяток
                
                # У выбывших игроков очищаем руки
                for pid, pdata in players.items():
                    if pid not in active_players:
                        pdata["hand"] = []

                trump = deck[0][1]
                seats = room.get("seats", list(players.keys()))
                # Обновляем attacker на первого активного игрока
                active_seats = [pid for pid in seats if pid in active_players]
                first_active = active_seats[0] if active_seats else seats[0]
                
                room.update({
                    "deck": deck,
                    "trump": trump,
                    "field": {"attack": None, "defend": None, "winner": None},
                    "attacker": first_active,
                    "defender": active_seats[1] if len(active_seats) > 1 else None,
                    "turn_order": active_seats.copy(),  # Только активные игроки
                    "turns": [],
                    "current_turn_idx": 0,
                    "status": "playing"
                })

                await redis.setex(req.room_id, 3600, json.dumps(room))
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
            # Используем фиксированный порядок игроков (turn_order - только активные)
            active_seats = room.get("turn_order", list(players.keys()))
            
            # Находим позицию победителя и начинаем с него
            winner_idx = active_seats.index(winner)
            order = active_seats[winner_idx:] + active_seats[:winner_idx]

            # будем накапливать новые карты для каждого игрока
            new_cards_by_player = {pid: [] for pid in order}

            # сохраняем "старую руку" для каждого игрока (после хода, до добора)
            old_hand_by_player: dict[str, list[list[str]]] = {
                pid: [list(c) for c in players[pid]["hand"]]
                for pid in order
            }

            # раздаём карты по одной за круг
            while deck and any(len(players[pid]["hand"]) < 4 for pid in order):
                for pid in order:
                    if deck and len(players[pid]["hand"]) < 4:
                        card = deck.pop(0)
                        players[pid]["hand"].append(card)
                        new_cards_by_player[pid].append(card)
                        logger.debug(f"[MOVE] Игрок {pid} добрал {card}")

            # print(new_cards_by_player)

            # теперь отправляем уведомления только один раз для каждого игрока
            for pid, new_cards in new_cards_by_player.items():
                if new_cards:  # если реально были выданы карты
                    await send_msg(
                        event="hand",
                        payload={
                            "old_card_user": old_hand_by_player[pid],
                            "new_cards": new_cards,
                            "trump": trump,
                            "deck_count": len(deck),
                            "attacker": room["attacker"],
                        },
                        channel_name=f"user#{pid}",
                    )

        room["attacker"] = winner
        # Следующий атакующий - победитель этой взятки
        room["defender"] = seats[(seats.index(winner) + 1) % len(seats)] if len(seats) > 1 else None
    
    # сохраняем изменения
    players[str(req.tg_id)]["hand"] = hand
    room["players"] = players
    room["deck"] = deck
    await redis.setex(req.room_id, 3600, json.dumps(room))

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
            await redis.setex(req.room_id, 3600, json.dumps(room))

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
            await redis.setex(req.room_id, 3600, json.dumps(room))
            await send_msg(
                "close_room",
                {"room_id": req.room_id},
                channel_name="rooms",
            )

        return {"ok": True, "message": "Игрок вышел из комнаты"}

    # случай 2: игра уже идёт → игрок считается проигравшим
    else:
        logger.info(f"[LEAVE] Игрок {req.tg_id} вышел во время игры (проигрыш)")

        # определяем оставшихся игроков
        remaining_ids = [pid for pid in players.keys() if pid != str(req.tg_id)]
        
        from app.payments.dao import TransactionDAO
        dao = TransactionDAO(session)
        
        if len(players) == 2:
            # Для двух игроков используем старый метод
            balances = await dao.apply_game_result(
                winner_id=int(remaining_ids[0]),
                loser_id=int(req.tg_id),
                stake=room["stake"],
            )
        else:
            # Для трёх и более игроков используем новый метод
            balances = await dao.apply_game_result_multiplayer(
                winner_id=int(remaining_ids[0]),
                loser_ids=[int(req.tg_id)],
                stake=room["stake"],
            )
        await session.commit()

        # уведомляем игроков
        await send_msg(
            event="game_over",
            payload={
                "room_id": req.room_id,
                "winner": remaining_ids[0],
                "losers": [str(req.tg_id)],
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
            "winner": remaining_ids[0],
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

    capacity = int(room.get("capacity", 2))
    if len(players) >= capacity:
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
    if len(players) >= capacity:
        room["status"] = "matched"

    await redis.setex(room_id, 3600, json.dumps(room))

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
    3 игрока, ставка 1000. У всех есть одна карта в руке, колода пуста.
    Игрок 5254325840 (11 штрафных) выбывает, игроки 111 (0) и 222 (0) продолжают.
    """
    room_id = "1000_test_final"
    trump = "♦"

    room = {
        "room_id": room_id,
        "stake": 1000,
        "created_at": datetime.utcnow().isoformat(),
        "status": "playing",
        "capacity": 3,
        "speed": "normal",
        "redeal": False,
        "dark": False,
        "reliable_only": False,
        "players": {
            "5254325840": {
                "nickname": "edward",
                "is_ready": True,
                "hand": [["7", "♦"]],
                "round_score": 0,
                "penalty": 11,
                "taken_tricks": 0
            },
            "111": {
                "nickname": "gg",
                "is_ready": True,
                "hand": [["A", "♠"]],
                "round_score": 0,
                "penalty": 0,
                "taken_tricks": 0
            },
            "222": {
                "nickname": "hh",
                "is_ready": True,
                "hand": [["K", "♦"]],
                "round_score": 0,
                "penalty": 0,
                "taken_tricks": 0
            }
        },
        "deck": [],  # колода пуста — игра должна закончиться
        "trump": trump,
        "field": {"attack": None, "defend": None, "winner": None},
        "last_turn": {"attack": None, "defend": None, "turns": []},
        "seats": ["5254325840", "111", "222"],
        "attacker": "5254325840",
        "defender": "111",
        "turn_order": ["5254325840", "111", "222"],
        "turns": [],
        "current_turn_idx": 0
    }

    await redis.setex(room_id, 3600, json.dumps(room))
    logger.info(f"[TEST] Создана тестовая 'последняя раздача' {room_id}")

    return {"ok": True, "room": room}


@router.post("/create_one_out_room")
async def create_one_out_room(redis: CustomRedis = Depends(get_redis)):
    """
    Создаёт комнату где 1 игрок уже выбыл с 12 штрафными очками.
    2 игрока продолжают игру.
    """
    room_id = "1000_test_one_out"
    trump = "♦"

    room = {
        "room_id": room_id,
        "stake": 1000,
        "created_at": datetime.utcnow().isoformat(),
        "status": "playing",
        "capacity": 3,
        "speed": "normal",
        "redeal": False,
        "dark": False,
        "reliable_only": False,
        "players": {
            "5254325840": {
                "nickname": "edward",
                "is_ready": True,
                "hand": [],
                "round_score": 25,
                "penalty": 12,
                "taken_tricks": 1
            },
            "111": {
                "nickname": "gg",
                "is_ready": True,
                "hand": [["A", "♠"], ["8", "♥"]],
                "round_score": 35,
                "penalty": 2,
                "taken_tricks": 2
            },
            "222": {
                "nickname": "hh",
                "is_ready": True,
                "hand": [["K", "♦"], ["Q", "♣"]],
                "round_score": 28,
                "penalty": 4,
                "taken_tricks": 1
            }
        },
        "deck": [],  # колода пуста
        "trump": trump,
        "field": {"attack": None, "defend": None, "winner": None},
        "last_turn": {
            "attack": {"player": "111", "cards": [["6", "♣"]]},
            "defend": {"player": "222", "cards": [["Q", "♣"]]},
            "turns": [
                {"player": "111", "cards": [["6", "♣"]]},
                {"player": "222", "cards": [["Q", "♣"]]}
            ]
        },
        "seats": ["5254325840", "111", "222"],
        "attacker": "111",
        "defender": "222",
        "turn_order": ["5254325840", "111", "222"],
        "turns": [],
        "current_turn_idx": 0
    }

    await redis.setex(room_id, 3600, json.dumps(room))
    logger.info(f"[TEST] Создана тестовая комната '1 игрок выбыл' {room_id}")

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
