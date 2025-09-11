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
    logger.debug(f"[READY] Игрок {req.tg_id} готов")

    room["players"] = players
    await redis.set(req.room_id, json.dumps(room))

    # если все готовы → старт
    if all(p["is_ready"] for p in players.values()) and "deck" not in room:
        logger.info("[READY] Все игроки готовы, стартуем!")

        deck = list(DECK)
        random.shuffle(deck)

        hands = {}
        for tg_id, pdata in players.items():
            hand = deck[:CARDS_IN_HAND_MAX]
            deck = deck[CARDS_IN_HAND_MAX:]
            hands[tg_id] = hand
            logger.debug(f"[READY] {tg_id} ({pdata['nickname']}) получил {hand}")

        trump = deck[0][1]
        logger.info(f"[READY] Козырь: {trump}, осталось карт: {len(deck)}")

        room.update({
            "deck": deck,
            "hands": hands,
            "trump": trump,
            "field": [],
            "attacker": list(players.keys())[0],
        })
        await redis.set(req.room_id, json.dumps(room))

        for tg_id in players.keys():
            await send_msg(
                "hand",
                {
                    "hand": hands[tg_id],
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
    - Если target == null → атака.
    - Если target != null → защита.
    """
    logger.info(f"[MOVE] tg_id={req.tg_id}, card={req.card}, target={req.target}")

    raw = await redis.get(req.room_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Комната не найдена")

    room = json.loads(raw)
    hands = room.get("hands", {})
    field = room.get("field", [])
    trump = room.get("trump")
    attacker = room.get("attacker")

    # Проверяем игрока
    if str(req.tg_id) not in hands:
        raise HTTPException(status_code=404, detail="Игрок не найден в комнате")

    hand = hands[str(req.tg_id)]
    card = req.card  # ["8", "♥"]

    # --- атака ---
    if req.target is None:
        if str(req.tg_id) != attacker:
            raise HTTPException(status_code=400, detail="Сейчас не твой ход")

        if len(field) >= 6:
            raise HTTPException(status_code=400, detail="Нельзя подкинуть больше 6 карт")

        if card not in hand:
            raise HTTPException(status_code=400, detail="У игрока нет такой карты")

        if field:
            all_values = {f["attack"][0] for f in field} | {
                f["defend"][0] for f in field if f["defend"] is not None
            }
            if card[0] not in all_values:
                raise HTTPException(
                    status_code=400,
                    detail="Можно подкинуть только карту с тем же достоинством, что уже на столе",
                )

        # добавляем атаку
        field.append({"attack": card, "defend": None})
        hand.remove(card)

        logger.debug(f"[MOVE] Игрок {req.tg_id} атаковал {card}")

    # --- защита ---
    else:
        target = req.target  # ["9", "♥"]

        # находим атаку, которую надо отбить
        target_entry = next((f for f in field if f["attack"] == target), None)
        if not target_entry:
            raise HTTPException(status_code=400, detail="Такой карты нет на столе для защиты")

        if str(req.tg_id) == attacker:
            raise HTTPException(status_code=400, detail="Атакующий не может защищаться")

        if target_entry["defend"] is not None:
            raise HTTPException(status_code=400, detail="Эта карта уже отбита")

        if card not in hand:
            raise HTTPException(status_code=400, detail="У игрока нет такой карты")

        # проверка на побитие
        nom1, suit1 = target
        nom2, suit2 = card
        beats = False
        if suit2 == trump and suit1 != trump:
            beats = True
        elif suit1 == suit2 and NAME_TO_VALUE[nom2] > NAME_TO_VALUE[nom1]:
            beats = True

        if not beats:
            raise HTTPException(status_code=400, detail="Этой картой нельзя побить")

        # применяем защиту
        target_entry["defend"] = card
        hand.remove(card)

        logger.debug(f"[MOVE] Игрок {req.tg_id} отбился {card} против {target}")

    # сохраняем
    hands[str(req.tg_id)] = hand
    room["hands"] = hands
    room["field"] = field
    await redis.set(req.room_id, json.dumps(room))

    # шлём обновление в Centrifugo
    await send_msg(
        event="move",
        payload={
            "room_id": req.room_id,
            "field": field,
            "hands_count": {pid: len(h) for pid, h in hands.items()},
        },
        channel_name=f"room#{req.room_id}",
    )

    return {"ok": True, "field": field, "hands": hands}


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
    """
    Создаёт тестовую комнату с заранее заданным положением карт.
    Используется для отладки хода, отбоя и подкидывания.
    """
    room_id = f"10_{uuid.uuid4().hex[:8]}"
    trump = "♦"

    # Жёстко задаём расклад
    room = {
        "room_id": room_id,
        "stake": 10,
        "created_at": datetime.utcnow().isoformat(),
        "status": "matched",
        "players": {
            "7022782558": {"nickname": "sasha", "is_ready": True},
            "5254325840": {"nickname": "ed", "is_ready": True},
        },
        "deck": [
            ["A", "♦"], ["6", "♠"], ["9", "♦"], ["K", "♥"],
            ["6", "♣"], ["10", "♣"], ["Q", "♠"], ["8", "♠"],
            ["7", "♣"], ["9", "♥"], ["10", "♥"], ["9", "♠"],
            ["K", "♦"], ["J", "♥"], ["K", "♣"], ["Q", "♣"],
            ["A", "♥"], ["9", "♣"], ["7", "♦"], ["8", "♦"],
            ["J", "♦"], ["K", "♠"], ["7", "♥"], ["J", "♣"]
        ],
        "hands": {
            "7022782558": [  # атакующий
                ["7", "♠"], ["J", "♠"], ["8", "♣"], ["6", "♥"], ["Q", "♦"]
            ],
            "5254325840": [  # защищающийся
                ["A", "♣"], ["Q", "♥"], ["10", "♠"], ["8", "♥"], ["A", "♠"]
            ],
        },
        "trump": trump,
        "field": [
            {"attack": ["6", "♦"], "defend": ["10", "♦"]}
        ],
        "attacker": "7022782558",  # атакует Саша
    }

    await redis.set(room_id, json.dumps(room))
    logger.info(f"[TEST] Создана тестовая комната {room_id}")

    return {"ok": True, "room": room}


@router.post("/bito")
async def bito(
    req: ReadyRequest,
    session: SessionDep,
    redis: CustomRedis = Depends(get_redis),
):
    """
    Завершение хода (Бито).
    Может вызвать только атакующий игрок.
    - Проверяет, что все карты отбиты.
    - Очищает поле.
    - Добирает карты игрокам до 6.
    - Если у кого-то не осталось карт → завершает игру и обновляет баланс.
    """
    logger.info(f"[BITO] room_id={req.room_id}, tg_id={req.tg_id}")

    raw = await redis.get(req.room_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Комната не найдена")

    room = json.loads(raw)
    field = room.get("field", [])
    deck = room.get("deck", [])
    hands = room.get("hands", {})
    stake = room.get("stake")
    players = room.get("players", {})
    attacker = room.get("attacker")

    # --- Проверяем, что нажал атакующий ---
    if str(req.tg_id) != str(attacker):
        raise HTTPException(status_code=400, detail="Бито может вызвать только атакующий игрок")

    # --- Проверяем, что все карты отбиты ---
    if any(pair["defend"] is None for pair in field):
        raise HTTPException(status_code=400, detail="На столе есть неотбитые карты")

    # --- Очищаем поле ---
    room["field"] = []
    logger.debug("[BITO] Поле очищено")

    # --- Добор карт ---
    order = [attacker] + [pid for pid in players.keys() if pid != attacker]
    for pid in order:
        if deck and len(hands[pid]) < 6:
            need = 6 - len(hands[pid])
            take = deck[:need]
            hands[pid].extend(take)
            deck = deck[need:]
            logger.debug(f"[BITO] Игрок {pid} добрал карты: {take}")

    room["hands"] = hands
    room["deck"] = deck

    # --- Проверка на окончание игры ---
    winner = None
    for pid, hand in hands.items():
        if not hand:  # у игрока кончились карты
            winner = pid

    if winner:
        loser = [pid for pid in players.keys() if pid != winner][0]
        logger.info(f"[BITO] Игра окончена! Победитель {winner}, проигравший {loser}")

        # обновляем балансы
        winner_user = await UserDAO.find_one_or_none(session, tg_id=int(winner))
        loser_user = await UserDAO.find_one_or_none(session, tg_id=int(loser))

        if not winner_user or not loser_user:
            raise HTTPException(status_code=500, detail="Ошибка при обновлении баланса")

        winner_user.balance += stake
        loser_user.balance -= stake
        await session.commit()

        # отправляем сообщение в Centrifugo
        await send_msg(
            event="game_over",
            payload={
                "room_id": req.room_id,
                "winner": winner,
                "loser": loser,
                "stake": stake,
            },
            channel_name=f"room#{req.room_id}",
        )

        # удаляем комнату из Redis
        await redis.delete(req.room_id)
        return {"ok": True, "winner": winner, "loser": loser}

    # --- Обновляем комнату ---
    # меняем атакующего → теперь атакует защищающийся
    next_attacker = [pid for pid in players.keys() if pid != attacker][0]
    room["attacker"] = next_attacker

    await redis.set(req.room_id, json.dumps(room))

    # отправляем обновление в Centrifugo
    await send_msg(
        event="bito",
        payload={
            "room_id": req.room_id,
            "hands_count": {pid: len(h) for pid, h in hands.items()},
            "deck_count": len(deck),
            "attacker": next_attacker,
        },
        channel_name=f"room#{req.room_id}",
    )

    return {"ok": True, "room": room}


@router.post("/beru")
async def beru(
    req: ReadyRequest,
    session: SessionDep,
    redis: CustomRedis = Depends(get_redis),
):
    """
    Защищающийся игрок берёт карты со стола.
    - Может вызвать только защищающийся игрок.
    - Все карты на поле добавляются в его руку.
    - Добор карт из колоды: первым добирает атакующий, потом защищающийся.
    - Если у кого-то не осталось карт → игра завершается.
    """
    logger.info(f"[BERU] room_id={req.room_id}, tg_id={req.tg_id}")

    raw = await redis.get(req.room_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Комната не найдена")

    room = json.loads(raw)
    field = room.get("field", [])
    deck = room.get("deck", [])
    hands = room.get("hands", {})
    players = room.get("players", {})
    attacker = room.get("attacker")

    # --- Проверка, что игрок защищающийся ---
    defenders = [pid for pid in players.keys() if pid != attacker]
    if str(req.tg_id) not in defenders:
        raise HTTPException(status_code=400, detail="Беру может вызвать только защищающийся игрок")

    defender = str(req.tg_id)

    # --- Добавляем все карты со стола защитнику ---
    taken_cards = []
    for pair in field:
        taken_cards.append(pair["attack"])
        if pair["defend"] is not None:
            taken_cards.append(pair["defend"])

    hands[defender].extend(taken_cards)
    logger.debug(f"[BERU] Игрок {defender} взял карты со стола: {taken_cards}")

    # очищаем поле
    room["field"] = []

    # --- Добор карт из колоды ---
    order = [attacker, defender]  # сначала атакующий
    for pid in order:
        if deck and len(hands[pid]) < 6:
            need = 6 - len(hands[pid])
            take = deck[:need]
            hands[pid].extend(take)
            deck = deck[need:]
            logger.debug(f"[BERU] Игрок {pid} добрал карты: {take}")

    room["hands"] = hands
    room["deck"] = deck

    # --- Проверка на окончание игры ---
    winner = None
    for pid, hand in hands.items():
        if not hand:  # у игрока пустая рука
            winner = pid

    if winner:
        loser = [pid for pid in players.keys() if pid != winner][0]
        logger.info(f"[BERU] Игра окончена! Победитель {winner}, проигравший {loser}")

        winner_user = await UserDAO(session).find_one_or_none(tg_id=int(winner))
        loser_user = await UserDAO(session).find_one_or_none(tg_id=int(loser))

        if not winner_user or not loser_user:
            raise HTTPException(status_code=500, detail="Ошибка при обновлении баланса")

        stake = room.get("stake", 0)
        winner_user.balance += stake
        loser_user.balance -= stake
        await session.commit()

        await send_msg(
            event="game_over",
            payload={
                "room_id": req.room_id,
                "winner": winner,
                "loser": loser,
                "stake": stake,
            },
            channel_name=f"room#{req.room_id}",
        )

        await redis.delete(req.room_id)
        return {"ok": True, "winner": winner, "loser": loser}

    # --- Обновляем комнату ---
    # В случае "беру" атакующий остаётся тем же самым
    room["attacker"] = attacker

    await redis.set(req.room_id, json.dumps(room))

    # --- Уведомляем игроков через Centrifugo ---
    await send_msg(
        event="beru",
        payload={
            "room_id": req.room_id,
            "hands_count": {pid: len(h) for pid, h in hands.items()},
            "deck_count": len(deck),
            "attacker": attacker,
        },
        channel_name=f"room#{req.room_id}",
    )

    return {"ok": True, "room": room}


#
#
# @router.post("/find-partner")
# async def find_partner(
#     user: SPartner,
#     session: AsyncSession = Depends(get_session_without_commit),
#     redis_client: CustomRedis = Depends(get_redis),
# ):
#     # Получаем полные данные пользователя
#     user_data = await get_user_info(session, user.id)
#
#     # Данные пользователя
#     user_nickname = user_data["nickname"]
#     user_gender = user_data["gender"]
#     user_age = user_data["age"]
#
#     # Данные для поиска
#     age_from = user.age_from
#     age_to = user.age_to
#     find_gender = user.gender
#
#     # Получаем все комнаты для искомого пола
#     all_rooms = await get_all_rooms_gender(redis_client)
#
#     if len(all_rooms) == 0:
#         # Если нет подходящих комнат, создаем новую
#         return await create_new_room(
#             user_id=user.id,
#             user_nickname=user_nickname,
#             user_gender=user_gender,
#             user_age=user_age,
#             find_gender=user.gender,
#             age_from=age_from,
#             age_to=age_to,
#             redis_client=redis_client,
#         )
#     else:
#         # Ищем подходящую комнату
#         for room in all_rooms:
#             partners = room.get("partners", [])
#             if len(partners) == 1:
#                 partner_data = partners[0]
#                 if partner_data["id"] != user.id:
#                     if is_match(
#                         user_gender=user_gender,
#                         user_find_gender=find_gender,
#                         user_age=user_age,
#                         user_age_from=age_from,
#                         user_age_to=age_to,
#                         partner_gender=partner_data.get("gender"),
#                         partner_find_gender=partner_data.get("find_gender"),
#                         partner_age=partner_data.get("age"),
#                         partner_age_from=partner_data.get("age_from"),
#                         partner_age_to=partner_data.get("age_to"),
#                     ):
#                         return await add_user_to_room(
#                             room,
#                             user.id,
#                             user_nickname,
#                             user_gender,
#                             user_age,
#                             find_gender,
#                             age_from,
#                             age_to,
#                             redis_client,
#                         )
#                 else:
#                     return await refund_partner(
#                         room.get("room_key"),
#                         user.id,
#                         user_nickname,
#                         status="waiting",
#                         message="Ожидаем подходящего партнера",
#                     )
#             elif len(partners) == 2:
#                 if partners[0]["id"] == user.id or partners[1]["id"] == user.id:
#                     return await refund_partner(
#                         room.get("room_key"), user.id, user_nickname
#                     )
#             continue
#         # Если подходящая комната не найдена, создаем новую
#         return await create_new_room(
#             user_id=user.id,
#             user_nickname=user_nickname,
#             user_gender=user_gender,
#             user_age=user_age,
#             find_gender=user.gender,
#             age_from=age_from,
#             age_to=age_to,
#             redis_client=redis_client,
#         )
#
#
# @router.get("/room-status")
# async def room_status(
#     key: str, user_id: int, redis_client: CustomRedis = Depends(get_redis)
# ):
#     # Получаем данные о комнате из Redis
#     room_data = await redis_client.get(key)
#     if not room_data:
#         raise HTTPException(status_code=404, detail="Комната не найдена")
#
#     room_info = json.loads(room_data)
#     participants = room_info.get("partners", [])
#
#     # Если в комнате 2 участника, значит партнер найден
#     if len(participants) == 2:
#         # Находим партнера (не текущего пользователя)
#         partner = next(
#             (
#                 participant
#                 for participant in participants
#                 if participant["id"] != user_id
#             ),
#             None,
#         )
#         if not partner:
#             raise HTTPException(status_code=500, detail="Ошибка при поиске партнера")
#
#         return {
#             "status": "matched",
#             "room_key": key,
#             "partner": {"id": partner["id"], "nickname": partner["nickname"]},
#         }
#
#     # Если в комнате только один участник, значит ожидание
#     elif len(participants) == 1:
#         print(f"STATUS: waiting!")
#         return {
#             "room_key": key,
#             "status": "waiting",
#             "message": "Ожидаем подходящего партнера",
#         }
#
#     # Если комната пуста или участников больше 2, значит комната закрыта
#     else:
#         print(f"STATUS: closed!")
#         return {"room_key": key, "status": "closed", "message": "Комната закрыта"}
#


#
#
# @router.post("/send-msg/{room_id}")
# async def vote(room_id: str, msg: SMessge):
#     data = msg.model_dump()
#     is_sent = await send_msg(data=data, channel_name=room_id)
#     return {"status": "ok" if is_sent else "failed"}
