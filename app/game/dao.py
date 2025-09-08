from app.dao.base import BaseDAO
from app.game.models import GameType


class GameTypeDAO(BaseDAO):
    model = GameType

