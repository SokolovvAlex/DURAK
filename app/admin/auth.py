from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt
from typing import Optional

from app.users.dao import UserDAO
from app.config import settings


pwd_context = CryptContext(schemes=['bcrypt'], deprecated="auto")


def get_password_hash(password: str) -> str:
    """
    Хеширование пароля с поддержкой bcrypt (ограничение 72 байта).
    Если пароль длиннее 72 байт, обрезаем его.
    """
    # bcrypt имеет ограничение в 72 байта
    # Обрезаем пароль до 72 байт, если он длиннее
    if len(password.encode('utf-8')) > 72:
        password = password.encode('utf-8')[:72].decode('utf-8', errors='ignore')
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля с поддержкой обрезания длинных паролей"""
    # Обрезаем пароль до 72 байт при проверке, если он длиннее
    if len(plain_password.encode('utf-8')) > 72:
        plain_password = plain_password.encode('utf-8')[:72].decode('utf-8', errors='ignore')
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    """Создание JWT токена"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=30)
    to_encode.update({'exp': expire.timestamp()})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, settings.ALGORITHM
    )
    return encoded_jwt


async def authenticate_user(session, login: str, password: str):
    """Аутентификация пользователя по логину и паролю"""
    user = await UserDAO.find_one_or_none(session, login=login)
    if not user or not user.password or not verify_password(password, user.password):
        return None
    return user
