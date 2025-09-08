import json
from typing import Any, Dict
from app.game.redis_dao.manager import get_redis


class GameRedisDAO:
    """DAO для управления состоянием игры в Redis"""

    @staticmethod
    async def save_game_state(room_id: str, state: Dict[str, Any], ttl: int = 3600):
        """Сохраняет состояние игры"""
        redis = await get_redis()
        key = f"game:{room_id}:state"
        await redis.setex(key, ttl, json.dumps(state))

    @staticmethod
    async def get_game_state(room_id: str) -> Dict[str, Any] | None:
        """Возвращает состояние игры"""
        redis = await get_redis()
        key = f"game:{room_id}:state"
        value = await redis.get(key)
        return json.loads(value) if value else None

    @staticmethod
    async def delete_game_state(room_id: str):
        """Удаляет состояние игры"""
        redis = await get_redis()
        key = f"game:{room_id}:state"
        await redis.delete_key(key)

    @staticmethod
    async def add_player_ready(room_id: str, player_id: str, ttl: int = 600):
        """Помечает игрока как готового"""
        redis = await get_redis()
        key = f"game:{room_id}:ready"
        await redis.hset(key, player_id, "ready")
        await redis.expire(key, ttl)

    @staticmethod
    async def get_ready_players(room_id: str) -> list[str]:
        """Возвращает список игроков, которые нажали 'Готов'"""
        redis = await get_redis()
        key = f"game:{room_id}:ready"
        players = await redis.hkeys(key)
        return [p.decode() for p in players]