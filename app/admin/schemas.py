from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional
from decimal import Decimal


class AdminCreate(BaseModel):
    """Схема для создания администратора"""
    login: str
    password: str
    name: Optional[str] = None
    username: Optional[str] = None
    is_super_admin: bool = False


class AdminOut(BaseModel):
    """Схема для вывода администратора"""
    id: int
    tg_id: Optional[int]
    username: Optional[str]
    name: Optional[str]
    login: Optional[str]
    is_admin: bool
    is_super_admin: bool
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminUpdate(BaseModel):
    """Схема для обновления администратора"""
    name: Optional[str] = None
    username: Optional[str] = None
    login: Optional[str] = None
    password: Optional[str] = None
    is_admin: Optional[bool] = None
    is_super_admin: Optional[bool] = None
    is_active: Optional[bool] = None


class LoginRequest(BaseModel):
    """Схема для входа в систему"""
    login: str
    password: str


class LoginResponse(BaseModel):
    """Схема ответа при входе"""
    access_token: str
    token_type: str = "bearer"
    user: AdminOut


class UserAdminOut(BaseModel):
    """Схема для вывода пользователя в админке"""
    id: int
    tg_id: Optional[int]
    username: Optional[str]
    name: Optional[str]
    balance: Decimal
    is_admin: bool
    is_super_admin: bool
    is_active: bool
    created_at: datetime
    login: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserAdminUpdate(BaseModel):
    """Схема для обновления пользователя в админке"""
    name: Optional[str] = None
    username: Optional[str] = None
    tg_id: Optional[int] = None
    balance: Optional[float] = None
    is_admin: Optional[bool] = None
    is_super_admin: Optional[bool] = None
    is_active: Optional[bool] = None

