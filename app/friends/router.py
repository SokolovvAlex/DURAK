from fastapi import APIRouter, Depends, HTTPException, Body
from app.database import SessionDep
from app.friends.dao import FriendDAO
from app.friends.schemas import AddFriendRequest
from app.users.dao import UserDAO
from app.bot.create_bot import bot
from app.game.redis_dao.manager import get_redis
from app.game.redis_dao.custom_redis import CustomRedis
from app.config import settings
from loguru import logger
import json

router = APIRouter(prefix="/friends", tags=["Friends"])

@router.get("/{tg_id}")
async def get_friends(tg_id: int, session: SessionDep):
    friends = await FriendDAO.get_friends(session, tg_id=tg_id)
    # print(friends)
    return friends


@router.post("/add")
async def add_friend(req: AddFriendRequest, session: SessionDep):
    """
    Добавить друга вручную (user_id -> friend_id).
    Здесь user_id и friend_id - это tg_id (Telegram ID).
    """
    if req.user_id == req.friend_id:
        raise HTTPException(status_code=400, detail="Нельзя добавить себя в друзья")

    user = await UserDAO.find_one_or_none(session, tg_id=req.user_id)
    friend = await UserDAO.find_one_or_none(session, tg_id=req.friend_id)

    if not user or not friend:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # FriendDAO.add_friend ожидает user.id, а не tg_id
    new_friend = await FriendDAO.add_friend(session, user_id=user.id, friend_id=friend.id)
    return {"ok": True, "friend": {"tg_id": req.user_id, "friend_tg_id": req.friend_id}}


@router.post("/invite_to_room")
async def invite_friend_to_room(
    session: SessionDep,
    inviter_id: int = Body(..., description="ID пользователя, который приглашает"),
    friend_id: int = Body(..., description="ID друга, которого приглашают"),
    room_id: str = Body(..., description="ID комнаты, к которой приглашают"),
    redis: CustomRedis = Depends(get_redis)
):
    """
    Отправляет приглашение другу присоединиться к существующей комнате.
    
    Шаги работы:
    1. Проверяет что inviter_id и friend_id действительно друзья
    2. Проверяет существование комнаты в Redis
    3. Проверяет что приглашающий находится в комнате
    4. Проверяет что комната еще не заполнена
    5. Проверяет баланс друга (должен быть >= ставки комнаты)
    6. Формирует прямую ссылку на Mini App с параметром room_id
    7. Отправляет сообщение другу через Telegram бота с кнопкой Web App
    
    Returns:
        - ok: True если приглашение отправлено успешно
        - room_id: ID комнаты
        - invite_sent: True
        - message: Сообщение об успехе
        - game_link: Ссылка на Mini App (на случай если нужно скопировать)
    
    Exceptions:
        - 403: Пользователь не в списке друзей или не находится в комнате
        - 404: Комната или пользователь не найдены
        - 400: Комната заполнена или недостаточно средств
        - 500: Ошибка при отправке сообщения через бота
    """
    
    # ========== ШАГ 1: Проверка дружбы ==========
    logger.info(f"[INVITE] inviter_id={inviter_id}, friend_id={friend_id}, room_id={room_id}")
    
    # Получаем пользователя-приглашающего
    inviter_user = await UserDAO.find_one_or_none(session, tg_id=inviter_id)
    if not inviter_user:
        raise HTTPException(status_code=404, detail="Приглашающий пользователь не найден")
    
    friend_user = await UserDAO.find_one_or_none(session, tg_id=friend_id)
    if not friend_user:
        raise HTTPException(status_code=404, detail="Друг не найден в базе данных")
    
    # Проверяем что они друзья (дружба может быть в любую сторону)
    are_friends = await FriendDAO.exists(session, user_id=inviter_user.id, friend_id=friend_user.id)
    
    if not are_friends:
        logger.warning(f"[INVITE] Friend check failed: {friend_id} not in {inviter_id}'s friends")
        raise HTTPException(
            status_code=403, 
            detail="Пользователь не в списке друзей"
        )
    
    # ========== ШАГ 2: Проверка существования комнаты ==========
    raw = await redis.get(room_id)
    
    if not raw:
        logger.warning(f"[INVITE] Room not found: {room_id}")
        raise HTTPException(
            status_code=404, 
            detail="Комната не найдена. Возможно, игра уже началась или завершилась."
        )
    
    room = json.loads(raw)
    
    # ========== ШАГ 3: Проверка что приглашающий в комнате ==========
    players = room.get("players", {})
    
    if str(inviter_id) not in players:
        logger.warning(f"[INVITE] Inviter {inviter_id} not in room {room_id}")
        raise HTTPException(
            status_code=403, 
            detail="Вы не находитесь в этой комнате"
        )
    
    # ========== ШАГ 4: Проверка что комната еще не заполнена ==========
    capacity = int(room.get("capacity", 2))
    players_count = len(players)
    
    if players_count >= capacity:
        logger.warning(f"[INVITE] Room {room_id} is full: {players_count}/{capacity}")
        raise HTTPException(
            status_code=400, 
            detail=f"Комната уже заполнена ({players_count}/{capacity} игроков)"
        )
    
    # Проверяем что друг еще не в комнате
    if str(friend_id) in players:
        logger.info(f"[INVITE] Friend {friend_id} already in room {room_id}")
        raise HTTPException(
            status_code=400,
            detail="Этот друг уже находится в этой комнате"
        )
    
    # ========== ШАГ 5: Проверка баланса друга ==========
    # inviter и friend уже получены выше в ШАГ 1
    inviter = inviter_user
    friend = friend_user
    
    stake = room.get("stake", 0)
    
    if friend.balance < stake:
        logger.warning(f"[INVITE] Friend {friend_id} insufficient balance: {friend.balance} < {stake}")
        raise HTTPException(
            status_code=400, 
            detail=f"У друга недостаточно средств для игры. Необходимо: {stake} кристаллов, есть: {friend.balance}"
        )
    
    # ========== ШАГ 6: Формирование прямой ссылки на Mini App ==========
    # Получаем URL фронтенда из настроек
    frontend_url = settings.FRONT_URL
    
    # Формируем прямую ссылку на Mini App с параметром room
    # Формат: https://grantexpert.pro/frontend/?room={room_id}
    game_link = f"{frontend_url}/?room={room_id}"
    
    logger.info(f"[INVITE] Generated game link: {game_link}")
    
    # ========== ШАГ 7: Отправка сообщения через бота ==========
    inviter_name = inviter.username or inviter.name or f"Игрок {inviter_id}"
    
    # Формируем текст сообщения
    message_text = (
        f"🎮 <b>{inviter_name}</b> приглашает тебя присоединиться к игре!\n\n"
        f"💰 <b>Ставка:</b> {stake} кристаллов\n"
        f"👥 <b>Игроков:</b> {players_count}/{capacity}\n"
        f"🎯 <b>Режим:</b> {room.get('speed', 'normal')}\n\n"
        f"Нажми кнопку ниже, чтобы открыть игру и присоединиться:"
    )
    
    try:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
        
        # Создаем кнопку с Web App (Mini App)
        # WebAppInfo содержит URL, который откроется в Mini App
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🎮 Присоединиться к игре",
                web_app=WebAppInfo(url=game_link)
            )
        ]])
        
        # Отправляем сообщение другу через бота
        await bot.send_message(
            chat_id=friend_id,
            text=message_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        logger.success(f"[INVITE] Invite sent successfully to {friend_id} for room {room_id}")
        
    except Exception as e:
        # Обработка ошибок отправки
        error_msg = str(e)
        logger.error(f"[INVITE] Failed to send message to {friend_id}: {error_msg}")
        
        # Проверяем причину ошибки
        if "bot was blocked" in error_msg.lower() or "chat not found" in error_msg.lower():
            detail_msg = "Не удалось отправить сообщение. Возможно, пользователь заблокировал бота или не запускал его."
        elif "user is deactivated" in error_msg.lower():
            detail_msg = "Пользователь деактивирован в Telegram."
        else:
            detail_msg = f"Ошибка при отправке сообщения: {error_msg}"
        
        # Возвращаем ссылку в ответе на случай если нужно скопировать
        raise HTTPException(
            status_code=500,
            detail=f"{detail_msg} Ссылка на игру: {game_link}"
        )
    
    # ========== Возвращаем успешный ответ ==========
    return {
        "ok": True,
        "room_id": room_id,
        "invite_sent": True,
        "message": "Приглашение отправлено другу",
        "game_link": game_link,  # Возвращаем ссылку на случай если нужно
        "friend_id": friend_id,
        "stake": stake,
        "players_count": players_count,
        "capacity": capacity
    }
