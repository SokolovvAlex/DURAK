from fastapi import APIRouter, Depends, HTTPException
from app.database import SessionDep
from app.friends.dao import FriendDAO
from app.friends.schemas import AddFriendRequest
from app.users.dao import UserDAO

router = APIRouter(prefix="/friends", tags=["Friends"])

@router.get("/{tg_id}")
async def get_friends(tg_id: int, session: SessionDep):
    friends = await FriendDAO.get_friends(session, tg_id=tg_id)
    # print(friends)
    return friends


@router.post("/add")
async def add_friend(req: AddFriendRequest, session: SessionDep):
    """
    Добавить друга вручную (user_id -> friend_id).
    """
    if req.user_id == req.friend_id:
        raise HTTPException(status_code=400, detail="Нельзя добавить себя в друзья")

    user = await UserDAO.find_one_or_none(session, tg_id=req.user_id)
    friend = await UserDAO.find_one_or_none(session, tg_id=req.friend_id)

    if not user or not friend:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    new_friend = await FriendDAO.add_friend(session, user_id=req.user_id, friend_id=req.friend_id)
    return {"ok": True, "friend": {"user_id": req.user_id, "friend_id": req.friend_id}}
