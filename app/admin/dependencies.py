from datetime import datetime
import logging

from fastapi import Request, HTTPException, status, Depends, Query
from jose import jwt, JWTError

from app.config import settings
from app.database import SessionDep
from app.exception import IncorrectFormatTokenException, TokenExpireException, NoPermissionsException, \
    UserIsNotPresentException, NoTokenException
from app.users.dao import UserDAO
from app.users.models import User

logger = logging.getLogger(__name__)


def get_token(request: Request):
    token = request.cookies.get('durak_access_token')
    if not token:
        raise NoTokenException
    return token


async def get_current_user(session: SessionDep, token: str = Depends(get_token)) -> User:
    """Получение текущего пользователя из JWT токена"""
    try:
        logger.info(f"Decoding token: {token[:50]}...")
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        logger.info(f"Token decoded successfully. Payload: {payload}")
    except JWTError as e:
        logger.error(f"JWT decode error: {e}")
        raise IncorrectFormatTokenException

    user_id = payload.get('sub')
    if not user_id:
        logger.error("No user_id in token")
        raise UserIsNotPresentException

    logger.info(f"Fetching user with id: {user_id}")
    user = await UserDAO.find_one_or_none_by_id(session, int(user_id))
    if not user:
        logger.error(f"User with id {user_id} not found")
        raise UserIsNotPresentException

    return user


async def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Проверяем, что пользователь является администратором"""
    if not current_user.is_admin:
        raise NoPermissionsException
    return current_user

async def get_current_super_admin(current_user: User = Depends(get_current_user)) -> User:
    """Проверяем, что пользователь является суперадмином"""
    if not current_user.is_super_admin:
        raise NoPermissionsException
    return current_user


async def get_current_unbanned_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Проверяем, что пользователь не забанен.
    Суперадмины не могут быть забанены (is_super_admin = True).
    Обычные пользователи проверяются по полю is_active.
    """
    # Суперадмины не могут быть забанены
    if current_user.is_super_admin:
        return current_user
    
    # Проверяем, не забанен ли обычный пользователь
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Пользователь забанен"
        )
    
    return current_user


# ============= Новые зависимости для работы с tg_id (для Mini App) =============

async def get_current_user_by_tg_id(
    session: SessionDep,
    tg_id: int = Query(..., description="Telegram user id"),

) -> User:
    """Получение текущего пользователя по tg_id (для Mini App)"""
    logger.info(f"Fetching user with tg_id: {tg_id}")
    user = await UserDAO.find_one_or_none(session, tg_id=tg_id)
    if not user:
        logger.error(f"User with tg_id {tg_id} not found")
        raise UserIsNotPresentException
    return user


async def get_current_admin_user_by_tg_id(
    current_user: User = Depends(get_current_user_by_tg_id)
) -> User:
    """Проверяем, что пользователь является администратором (по tg_id)"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет прав администратора"
        )
    
    # Проверяем, что пользователь активен
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ваш аккаунт деактивирован"
        )
    
    return current_user


async def get_current_super_admin_by_tg_id(
    current_user: User = Depends(get_current_user_by_tg_id)
) -> User:
    """Проверяем, что пользователь является суперадмином (по tg_id)"""
    if not current_user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет прав суперадмина"
        )
    
    # Проверяем, что пользователь активен
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ваш аккаунт деактивирован"
        )
    
    return current_user
