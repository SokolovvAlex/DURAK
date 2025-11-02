from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from typing import Optional


class TelegramIDModel(BaseModel):
    telegram_id: int

    model_config = ConfigDict(from_attributes=True)

class UserBase(BaseModel):
    name: str
    username: Optional[str] = None
    tg_id: Optional[int] = None
    is_admin: bool = False


class UserCreate(UserBase):
    balance: float

class UserUpdate(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    tg_id: Optional[int] = None
    is_admin: Optional[bool] = None


class UserOut(BaseModel):
    id: int
    tg_id: Optional[int]
    username: Optional[str]
    name: Optional[str]
    balance: Decimal
    is_admin: bool
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class UserStatsOut(BaseModel):
    id: int
    tg_id: int
    username: Optional[str]
    name: Optional[str]
    balance: float
    is_admin: bool
    is_active: bool
    created_at: datetime

    # Статистика
    total_games: int
    wins: int
    losses: int
    total_earned: float
    total_lost: float
    net_profit: float
    
    # Статистика надежности
    is_reliable: bool
    reliability: float  # Процент надежности (0.0 - 1.0)
    leaves_in_last_10: int  # Количество ливов за последние 10 игр

    class Config:
        from_attributes = True
