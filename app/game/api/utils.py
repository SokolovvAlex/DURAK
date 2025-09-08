import json
import time
import uuid
from datetime import datetime
from typing import List, Dict, Any

import httpx
import jwt
from fastapi import HTTPException
from loguru import logger

from app.config import settings
from app.users.dao import UserDAO
from app.game.redis_dao.custom_redis import CustomRedis


# ===============================
# === Centrifugo ===============
# ===============================

async def send_msg(event: str, payload: dict, channel_name: str) -> bool:
    """Публикация события в Centrifugo."""
    message = {"event": event, "payload": payload}

    data = {"method": "publish", "params": {"channel": channel_name, "data": message}}
    headers = {"X-API-Key": settings.CENTRIFUGO_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(settings.CENTRIFUGO_URL, json=data, headers=headers)
            ok = response.status_code == 200
            logger.info(f"[Centrifugo] -> channel={channel_name}, event={event}, status={ok}")
            if not ok:
                logger.error(f"[Centrifugo] Ошибка: {response.text}")
            return ok
    except Exception as e:
        logger.error(f"[Centrifugo] Ошибка отправки: {e}")
        return False


async def generate_client_token(tg_id: int, secret_key: str) -> str:
    """Сгенерировать токен для клиента Centrifugo."""
    exp = int(time.time()) + 60 * 60
    payload = {"sub": str(tg_id), "exp": exp}
    return jwt.encode(payload, secret_key, algorithm="HS256")


# ===============================
# === Комнаты ==================
# ===============================

async def create_new_room(
    tg_id: int,
    nickname: str,
    stake: int,
    redis_client: CustomRedis,
) -> dict:
    """Создать новую комнату."""
    room_id = f"{stake}_{uuid.uuid4().hex[:8]}"
    token = await generate_client_token(tg_id, settings.SECRET_KEY)

    room_data = {
        "room_id": room_id,
        "stake": stake,
        "created_at": datetime.now().isoformat(),
        "status": "waiting",
        "players": {
            str(tg_id): {
                "nickname": nickname,
                "is_ready": False,
                "token": token,
            }
        },
    }
    await redis_client.set(room_id, json.dumps(room_data))

    return {
        "status": "waiting",
        "room_id": room_id,
        "message": f"Ожидание второго игрока для ставки {stake}",
        "token": token,
        "sender": nickname,
        "tg_id": tg_id,
    }


async def add_user_to_room(
    room: dict,
    tg_id: int,
    nickname: str,
    redis_client: CustomRedis,
) -> dict:
    """Добавить второго игрока в комнату."""
    token = await generate_client_token(tg_id, settings.SECRET_KEY)

    room["players"][str(tg_id)] = {
        "nickname": nickname,
        "is_ready": False,
        "token": token,
    }

    await redis_client.set(room["room_id"], json.dumps(room))

    return {
        "status": "matched",
        "room_id": room["room_id"],
        "message": "Игрок найден",
        "token": token,
        "sender": nickname,
        "tg_id": tg_id,
    }


async def get_all_rooms(redis_client: CustomRedis) -> List[Dict[str, Any]]:
    """Вернуть список всех комнат."""
    all_keys = await redis_client.keys("*")
    rooms_data = []

    if all_keys:
        values = await redis_client.mget(all_keys)
        for key, value in zip(all_keys, values):
            if value:
                try:
                    rooms_data.append(json.loads(value))
                except json.JSONDecodeError:
                    logger.error(f"Ошибка JSON для ключа {key}")
    return rooms_data


# ===============================
# === Пользователи =============
# ===============================

async def get_user_info(session, tg_id: int) -> dict:
    """Данные о пользователе по tg_id."""
    full_user_data = await UserDAO.find_one_or_none(session, **{"tg_id": tg_id})
    if not full_user_data:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return {"username": full_user_data.username}
