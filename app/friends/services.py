from app.friends.dao import FriendDAO
from app.users.dao import UserDAO

async def handle_referral(session, new_user_tg_id: int, referral_param: str):
    """
    Проверка перехода по реферальной ссылке.
    referral_param = "ref5254325840"
    """
    if referral_param.startswith("ref"):
        referrer_id = int(referral_param.replace("ref", ""))
        referrer = await UserDAO.find_one_or_none(session, tg_id=referrer_id)
        new_user = await UserDAO.find_one_or_none(session, tg_id=new_user_tg_id)
        if referrer and new_user and referrer.tg_id != new_user_tg_id:
            # FriendDAO.add_friend ожидает user.id, а не tg_id
            await FriendDAO.add_friend(session, user_id=referrer.id, friend_id=new_user.id)
            return True
    return False
