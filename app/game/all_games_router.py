from fastapi import APIRouter, Depends, HTTPException, Body, Query
from loguru import logger

from app.database import SessionDep
from app.game.dao import GameTypeDAO
from app.game.game_schemas import GameTypeOut, CurrentGameOut

router = APIRouter(prefix="/games", tags=["GAMES"])


@router.get("/", response_model=list[GameTypeOut])
async def get_active_games(
        session: SessionDep
):
    """
    Получить список всех активных игр
    """
    active_games = await GameTypeDAO.find_all(session, is_active=True)

    if not active_games:
        raise HTTPException(
            status_code=404,
            detail="No active games found"
        )

    return [GameTypeOut.model_validate(game) for game in active_games]


@router.get("/{game_id}", response_model=CurrentGameOut)
async def get_game_by_id(
        game_id: int,
        session: SessionDep
):
    """
    Получить информацию о конкретной игре по ID
    """
    game = await GameTypeDAO.find_one_or_none_by_id(session, game_id)

    if not game:
        raise HTTPException(
            status_code=404,
            detail=f"Game with id {game_id} not found"
        )

    if not game.is_active:
        raise HTTPException(
            status_code=400,
            detail=f"Game with id {game_id} is not active"
        )

    return CurrentGameOut.model_validate(game)

@router.get("/")
async def get_all_games(
        session: SessionDep
):
    """
    Получить все игры (опционально включая неактивные)
    """
    games = await GameTypeDAO.find_all(session)

    if not games:
        raise HTTPException(
            status_code=404,
            detail="No games found"
        )

    return [GameTypeOut.model_validate(game) for game in games]