from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.friends.models import Friend


class FriendDAO:
    @staticmethod
    async def add_friend(session: AsyncSession, user_id: int, friend_id: int):
        new_friend = Friend(user_id=user_id, friend_id=friend_id)
        session.add(new_friend)
        await session.commit()
        return new_friend

    @staticmethod
    async def get_friends(session: AsyncSession, tg_id: int):
        result = await session.execute(
            select(Friend).where(
                (Friend.user_id == tg_id) | (Friend.friend_id == tg_id)
            )
        )
        friends = result.scalars().all()  # здесь уже Friend-объекты

        return {
            "tg_id": tg_id,
            "friends": [
                f.friend_id if f.user_id == tg_id else f.user_id
                for f in friends
            ]
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
