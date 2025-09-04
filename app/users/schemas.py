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
    pass


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