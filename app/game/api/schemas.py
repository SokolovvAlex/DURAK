from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Tuple, Dict
from datetime import datetime

# ---------- Базовые типы ----------

Card = Tuple[str, str]  # ('6', '♠')


class PlayerState(BaseModel):
    tg_id: int
    nickname: str
    cards: List[Card]        # карты игрока (только для себя)
    n_cards: int             # количество карт (оппоненту отдаём только число)
    is_ready: bool = False


class FieldState(BaseModel):
    attacking: Card
    defending: Optional[Card] = None


class GameState(BaseModel):
    room_id: str
    trump: str
    attacker_tg_id: int
    defender_tg_id: int
    deck_count: int
    field: List[FieldState]
    players: Dict[int, PlayerState]  # tg_id -> PlayerState
    winner_tg_id: Optional[int] = None
    created_at: datetime


# ---------- Работа с комнатами ----------

class FindPartnerRequest(BaseModel):
    tg_id: int
    nickname: str
    stake: int

class FindPartnerResponse(BaseModel):
    room_id: str
    status: str  # waiting | matched
    message: str
    stake: int
    opponent: Optional[str] = None  # ник оппонента, если уже matched


class ReadyRequest(BaseModel):
    room_id: str
    tg_id: int


class ReadyResponse(BaseModel):
    room_id: str
    status: Literal["ready", "started"]
    message: str


# ---------- Игровые действия ----------

class AttackRequest(BaseModel):
    room_id: str
    tg_id: int
    card: Card


class AttackResponse(BaseModel):
    status: Literal["ok", "error"]
    message: str
    game_state: Optional[GameState]


class DefendRequest(BaseModel):
    room_id: str
    tg_id: int
    attack_card: Card
    defend_card: Card


class DefendResponse(BaseModel):
    status: Literal["ok", "error"]
    message: str
    game_state: Optional[GameState]


class FinishTurnRequest(BaseModel):
    room_id: str
    tg_id: int
    action: Literal["bito", "beru"]


class FinishTurnResponse(BaseModel):
    status: Literal["ok", "error"]
    message: str
    game_state: Optional[GameState]