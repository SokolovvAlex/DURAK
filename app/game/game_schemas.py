from pydantic import BaseModel


class GameTypeOut(BaseModel):
    id: int
    name: str
    is_active: bool
    max_users: int
    min_users: int
    max_rate: float
    min_rate: float

    class Config:
        from_attributes = True

class CurrentGameOut(BaseModel):
    id: int
    name: str
    rules: str
    is_active: bool
    max_users: int
    min_users: int
    max_rate: float
    min_rate: float

    class Config:
        from_attributes = True