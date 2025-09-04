from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from typing import Optional

class GameTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
    min_users: int
    max_users: int
    min_rate: Decimal
    max_rate: Decimal

class GameTypeDetail(GameTypeOut):
    rules: str