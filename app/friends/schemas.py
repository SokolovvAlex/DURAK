from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserRef(BaseModel):
    tg_id: int
    username: Optional[str] = None  # Или username: str | None = None
    name: Optional[str] = None  # Или name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class FriendCreate(BaseModel):
    referee_tg_id: int  # tg_id of the referred user (will be converted to user.id in service)


class FriendOut(BaseModel):
    id: int
    created_at: datetime
    referee: UserRef  # Nested info about the referred user

    model_config = ConfigDict(from_attributes=True)


class AddFriendRequest(BaseModel):
    user_id: int
    friend_id: int
