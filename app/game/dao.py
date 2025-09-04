from pydantic import BaseModel
from sqlalchemy import select, desc, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.base import BaseDAO
from app.game.models import GameType


class GameTypeDAO(BaseDAO):
    model = GameType

