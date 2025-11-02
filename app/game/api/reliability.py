"""
Функции для проверки надежности игроков.
"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.game.models import GameResult, GameResultEnum
from app.users.models import User


async def check_player_reliability(session: AsyncSession, tg_id: int) -> bool:
    """
    Проверяет надежность игрока.
    Надежный игрок = не более 2 ливов за последние 10 игр.
    
    Returns:
        True если игрок надежный, False если ненадежный
    """
    # Получаем пользователя
    user = await session.scalar(select(User).where(User.tg_id == tg_id))
    if not user:
        return False
    
    # Получаем последние 10 игр пользователя
    last_games = await session.scalars(
        select(GameResult)
        .where(GameResult.user_id == user.id)
        .order_by(GameResult.created_at.desc())
        .limit(10)
    )
    
    games_list = list(last_games)
    
    # Если игр меньше 10, считаем надежным
    if len(games_list) < 10:
        return True
    
    # Считаем количество ливов
    leaves_count = sum(1 for game in games_list if game.result == GameResultEnum.LOSS_BY_LEAVE)
    
    # Надежный = не более 2 ливов
    return leaves_count <= 2


async def get_player_reliability_stats(session: AsyncSession, tg_id: int) -> dict:
    """
    Получает статистику надежности игрока.
    
    Returns:
        dict с информацией о надежности игрока
    """
    user = await session.scalar(select(User).where(User.tg_id == tg_id))
    if not user:
        return {"is_reliable": False, "total_games": 0, "leaves": 0, "reliability": 0.0}
    
    # Получаем последние 10 игр
    last_games = await session.scalars(
        select(GameResult)
        .where(GameResult.user_id == user.id)
        .order_by(GameResult.created_at.desc())
        .limit(10)
    )
    
    games_list = list(last_games)
    total_games = len(games_list)
    leaves_count = sum(1 for game in games_list if game.result == GameResultEnum.LOSS_BY_LEAVE)
    is_reliable = leaves_count <= 2 if total_games >= 10 else True
    
    return {
        "is_reliable": is_reliable,
        "total_games": total_games,
        "leaves": leaves_count,
        "reliability": (1.0 - (leaves_count / 10.0)) if total_games >= 10 else 1.0
    }

