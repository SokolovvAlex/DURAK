from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.friends.models import Friend
from app.users.models import User


class FriendDAO:
    @staticmethod
    async def add_friend(session: AsyncSession, user_id: int, friend_id: int):
        new_friend = Friend(user_id=user_id, friend_id=friend_id)
        session.add(new_friend)
        await session.commit()
        return new_friend

    @staticmethod
    async def get_friends(session: AsyncSession, tg_id: int):
        # Сначала находим пользователя по tg_id
        user = await session.scalar(select(User).where(User.tg_id == tg_id))
        if not user:
            return {"tg_id": tg_id, "friends": []}
        
        # Теперь ищем друзей по user.id (который ссылается на users.id)
        result = await session.execute(
            select(Friend).where(
                (Friend.user_id == user.id) | (Friend.friend_id == user.id)
            )
        )
        friends = result.scalars().all()
        
        # Получаем user.id всех друзей
        friend_user_ids = []
        for f in friends:
            friend_user_id = f.friend_id if f.user_id == user.id else f.user_id
            friend_user_ids.append(friend_user_id)
        
        # Получаем полную информацию о друзьях (tg_id, name, username)
        friends_list = []
        if friend_user_ids:
            result_users = await session.execute(
                select(User.tg_id, User.name, User.username).where(User.id.in_(friend_user_ids))
            )
            friends_list = [
                {
                    "tg_id": row.tg_id,
                    "name": row.name,
                    "username": row.username
                }
                for row in result_users.all()
                if row.tg_id is not None
            ]
        
        return {
            "tg_id": tg_id,
            "friends": friends_list
        }

    @staticmethod
    async def exists(session: AsyncSession, user_id: int, friend_id: int) -> bool:
        query = select(Friend).where(
            or_(
                (Friend.user_id == user_id) & (Friend.friend_id == friend_id),
                (Friend.user_id == friend_id) & (Friend.friend_id == user_id),
            )
        )
        result = await session.execute(query)
        return result.scalar_one_or_none() is not None

