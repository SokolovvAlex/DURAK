from fastapi import APIRouter, HTTPException, Query
from app.database import SessionDep
from app.game.dao import GameTypeDAO
from app.game.schemas import GameTypeOut, GameTypeDetail

router = APIRouter(tags=["Game"])


@router.get("/lobby", response_model=list[GameTypeOut])
async def lobby(
    session: SessionDep
):
    """Список активных игровых типов (для лобби)."""
    gametypes = await GameTypeDAO.find_all(session, is_active=True)
    return [GameTypeOut.model_validate(gt) for gt in gametypes]


@router.get("/current_game/{game_type_id}", response_model=GameTypeDetail)
async def current_game(game_type_id: int, session: SessionDep):
    """Детальная информация о конкретном игровом типе."""
    gt = await GameTypeDAO.find_one_or_none_by_id(session, model_id=game_type_id)
    if not gt or not gt.is_active:
        raise HTTPException(status_code=404, detail="Game type not found or inactive")
    return GameTypeDetail.model_validate(gt)