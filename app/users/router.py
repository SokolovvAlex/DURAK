from fastapi import APIRouter, HTTPException, Query
from app.database import SessionDep
from app.users.dao import UserDAO
from app.users.schemas import UserCreate, UserUpdate, UserOut

router = APIRouter(prefix="/users", tags=["User"])


@router.post("/add_user", response_model=UserOut)
async def user_add(user: UserCreate, session: SessionDep):
    created = await UserDAO.add(session, **user.model_dump())
    return UserOut.model_validate(created)


@router.get("/all_users", response_model=list[UserOut])
async def get_all_users(
    session: SessionDep,
    is_admin: bool | None = Query(None),
    is_active: bool | None = Query(None),
):
    filters = {}
    if is_admin is not None:
        filters["is_admin"] = is_admin
    if is_active is not None:
        filters["is_active"] = is_active

    users = await UserDAO.find_all(session, **filters)
    return [UserOut.model_validate(user) for user in users]


@router.get("/get_current_user", response_model=UserOut)
async def get_current_user(session: SessionDep, tg_id: int = Query(..., description="Telegram user id")):
    user = await UserDAO.find_one_or_none(session, tg_id=tg_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut.model_validate(user)


@router.patch("/update_user/{user_id}", response_model=UserOut)
async def update_user(user_id: int, user_update: UserUpdate, session: SessionDep):
    updated = await UserDAO.update(session, {"id": user_id}, **user_update.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut.model_validate(updated)