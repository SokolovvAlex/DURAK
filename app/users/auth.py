import datetime
from datetime import timedelta

from app.database import connection
from app.users.dao import UserDAO
from passlib.context import CryptContext

from jose import jwt
from pydantic import EmailStr

from app.database import SessionDep
from app.users.dao import UserDAO
from app.config import settings


@connection()
async def get_current_user(tg_id: int, session):
    user = await UserDAO.find_one_or_none(session, tg_id=tg_id)
    return user


pwd_context = CryptContext(schemes=['bcrypt'], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=30)
    to_encode.update({'exp': expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, settings.ALGORITHM
    )
    return encoded_jwt


async def authenticate_user(email: EmailStr, password: str, session: SessionDep):
    user = await UserDAO.find_one_or_none(session, email=email)
    if not user or not verify_password(password, user.password):
        return None
    return user

